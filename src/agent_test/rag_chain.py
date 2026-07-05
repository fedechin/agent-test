import os
from dotenv import load_dotenv
from langchain_community.vectorstores import FAISS
from langchain.embeddings import OpenAIEmbeddings
from langchain.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from langchain.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_core.runnables import RunnableLambda, RunnableMap
from langchain_core.output_parsers import StrOutputParser

load_dotenv()

# === Configuration ===
DATA_DIR = os.getenv("DOCS_FOLDER", "data")
INDEX_PATH = os.path.join(DATA_DIR, "faiss_index")
CONTEXT_PATH = os.getenv("CONTEXT_FILE", "context/context.txt")

# Frase de derivación (regla 3.1 del contexto) para cuando no hay información.
# Inicia con la etiqueta [DERIVAR_HUMANO]: el webhook la detecta para escalar la
# conversación a un agente humano (request_human_takeover) y luego la elimina del
# texto antes de enviarlo al socio.
FALLBACK_MESSAGE = (
    "[DERIVAR_HUMANO] No tengo esa información, pero voy a derivar su consulta "
    "a un agente humano que se pondrá en contacto con usted a la brevedad. "
    "Si lo prefiere, también puede llamar al (021) 552631 o acercarse a "
    "cualquiera de nuestras sucursales."
)
# Umbral de relevancia: si el mejor fragmento recuperado queda por debajo, el tema
# no está en la base de conocimiento y derivamos en vez de arriesgar una respuesta.
# Conservador a propósito para no derivar preguntas válidas (se calibra con el eval).
RELEVANCE_THRESHOLD = float(os.getenv("RELEVANCE_THRESHOLD", "0.2"))

# === Helpers ===
# La base de conocimiento es markdown con estructura de preguntas/respuestas
# (## sección, ### pregunta). Dividimos por encabezados para que cada fragmento
# sea una unidad autocontenida (una pregunta con su respuesta) y un dato nunca
# quede pegado a un tema que no le corresponde (causa de la alucinación "Gs. 10.000").
MD_HEADERS = [("#", "h1"), ("##", "h2"), ("###", "h3"), ("####", "h4")]
# Tope para secciones muy largas (p.ej. el catálogo completo de créditos): se
# subdividen; las secciones cortas quedan intactas como un solo fragmento.
MAX_CHUNK_SIZE = 1500
CHUNK_OVERLAP = 150

def load_documents():
    # Load both .txt and .md files
    txt_loader = DirectoryLoader(DATA_DIR, glob="**/*.txt", loader_cls=TextLoader)
    md_loader = DirectoryLoader(DATA_DIR, glob="**/*.md", loader_cls=TextLoader)

    raw_docs = []
    raw_docs.extend(txt_loader.load())
    raw_docs.extend(md_loader.load())

    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=MD_HEADERS, strip_headers=False
    )
    size_splitter = RecursiveCharacterTextSplitter(
        chunk_size=MAX_CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )

    chunks = []
    for doc in raw_docs:
        # Remove BOM and normalize the text
        clean = doc.page_content.encode('utf-8').decode('utf-8-sig').strip()
        source = doc.metadata.get('source', 'desconocido')

        # Split by markdown headers; MarkdownHeaderTextSplitter drops the source
        # metadata, so we restore it on each resulting section.
        sections = header_splitter.split_text(clean)
        for sec in sections:
            sec.metadata['source'] = source

        # Cap oversized sections without breaking the small Q&A ones.
        chunks.extend(size_splitter.split_documents(sections))

    return chunks

def build_or_load_vectorstore(docs=None):
    embeddings = OpenAIEmbeddings()
    os.makedirs(INDEX_PATH, exist_ok=True)
    index_file = os.path.join(INDEX_PATH, "index.faiss")
    if os.path.exists(index_file):
        print("[FAISS] Loading existing vector store from disk.")
        return FAISS.load_local(INDEX_PATH, embeddings, allow_dangerous_deserialization=True)
    print("[FAISS] Building new vector store.")
    if docs is None:
        docs = load_documents()
    vectorstore = FAISS.from_documents(docs, embeddings)
    vectorstore.save_local(INDEX_PATH)
    return vectorstore

def load_context(context_path=CONTEXT_PATH):
    if not os.path.exists(context_path):
        print(f"[WARN] Context file '{context_path}' not found.")
        return ""
    with open(context_path, "r", encoding="utf-8") as f:
        return f.read()

# === Custom RAG Chain ===
def build_rag_chain(context_path=CONTEXT_PATH, model_name="gpt-4o-mini"):
    # Load the chunks once and reuse them for both retrievers.
    docs = load_documents()
    vectorstore = build_or_load_vectorstore(docs)

    # Hybrid retrieval: BM25 (sparse, exact keywords / nombres propios como
    # "Che Róga Porä") + denso (FAISS, semántico). Se combinan con fusión de
    # rangos. BM25 es local: no agrega costo de API.
    # k un poco más alto mejora la recuperación en preguntas tipo "listar todos"
    # (p.ej. todos los tipos de crédito o todos los subsidios), donde hay ~14 ítems.
    retrieval_k = int(os.getenv("RETRIEVAL_K", "8"))
    dense_retriever = vectorstore.as_retriever(search_kwargs={"k": retrieval_k})
    bm25_retriever = BM25Retriever.from_documents(docs)
    bm25_retriever.k = retrieval_k
    retriever = EnsembleRetriever(
        retrievers=[bm25_retriever, dense_retriever], weights=[0.4, 0.6]
    )
    context = load_context(context_path)

    system_prompt = SystemMessagePromptTemplate.from_template(
        """Usted es un asistente IA especializado para socios de la Cooperativa Multiactiva Nazareth.

DEBE SEGUIR EXACTAMENTE ESTAS INSTRUCCIONES:
{instructions}"""
    )

    human_prompt = HumanMessagePromptTemplate.from_template(
        """BASE DE CONOCIMIENTO (documentos relevantes):
{contextual_documents}

{conversation_history}
PREGUNTA ACTUAL DEL SOCIO:
{query}
"""
    )

    chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])
    # Temperatura 0: respuestas deterministas y sin "relleno" creativo. Con 0.2 el
    # modelo a veces inventaba condiciones no presentes en la base (p.ej. "Country
    # Club: Todos los días" o inferir que no se puede alquilar). Priorizamos evitar
    # alucinaciones por sobre la naturalidad del tono.
    llm = ChatOpenAI(model=model_name, temperature=0.0)

    def format_docs(docs):
        return "\n\n".join([
            f"{doc.page_content}\n[Archivo: {os.path.basename(doc.metadata.get('source', 'desconocido'))}]"
            for doc in docs
        ])

    def format_conversation_history(history):
        """Format conversation history for the prompt."""
        if not history:
            return ""

        formatted = "HISTORIAL DE LA CONVERSACIÓN:\n"
        for msg in history:
            role_label = "Socio" if msg["role"] == "customer" else "Asistente"
            formatted += f"{role_label}: {msg['content']}\n"
        formatted += "\n"
        return formatted

    def contextualize_query(query: str, history: list) -> str:
        """
        Reformulate the query to be standalone by incorporating conversation context.
        This ensures the retriever finds the right documents for follow-up questions.
        """
        # Skip contextualization if no history or very short history
        if not history or len(history) < 2:
            return query

        # Create a prompt to reformulate the query with context
        contextualization_prompt = f"""Dada la siguiente conversación y una pregunta de seguimiento, reformula la pregunta para que sea autocontenida (es decir, que pueda entenderse sin el historial de conversación).

HISTORIAL DE LA CONVERSACIÓN:
"""
        for msg in history[-3:]:  # Use last 3 messages for context
            role_label = "Socio" if msg["role"] == "customer" else "Asistente"
            contextualization_prompt += f"{role_label}: {msg['content']}\n"

        contextualization_prompt += f"""
PREGUNTA DE SEGUIMIENTO: {query}

PREGUNTA REFORMULADA (mantén el idioma original):"""

        # Use LLM to reformulate the query
        reformulated = llm.invoke(contextualization_prompt)
        reformulated_query = reformulated.content.strip()

        # Fallback to original if reformulation seems to have failed
        if not reformulated_query or len(reformulated_query) > len(query) * 3:
            return query

        return reformulated_query

    def answer_question(inputs):
        query = str(inputs["query"])
        instructions = inputs["instructions"]
        conversation_history = inputs.get("conversation_history", [])

        # Contextualize the query if there's conversation history
        # This ensures follow-up questions retrieve the right documents
        search_query = contextualize_query(query, conversation_history)

        # Relevance gate: si ni el mejor fragmento del índice denso es relevante,
        # el tema no está en la base de conocimiento. Derivamos directamente (sin
        # llamar al LLM) en vez de dejar que el modelo invente una respuesta.
        scored = vectorstore.similarity_search_with_relevance_scores(search_query, k=1)
        top_score = scored[0][1] if scored else 0.0
        if top_score < RELEVANCE_THRESHOLD:
            return FALLBACK_MESSAGE

        # Get relevant documents using the contextualized query
        docs = retriever.invoke(search_query)
        formatted_docs = format_docs(docs)

        # Format conversation history
        formatted_history = format_conversation_history(conversation_history)

        # Create chat prompt with all inputs
        messages = chat_prompt.format_messages(
            query=query,
            instructions=instructions,
            contextual_documents=formatted_docs,
            conversation_history=formatted_history
        )

        # Get response from LLM
        response = llm.invoke(messages)
        return response.content
    
    qa_chain = RunnableLambda(answer_question)

    return qa_chain, context

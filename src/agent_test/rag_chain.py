import os
from dotenv import load_dotenv
from langchain_community.vectorstores import FAISS
from langchain.embeddings import OpenAIEmbeddings
from langchain.document_loaders import DirectoryLoader, TextLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from langchain_core.runnables import RunnableLambda, RunnableMap
from langchain_core.output_parsers import StrOutputParser

load_dotenv()

# === Configuration ===
DATA_DIR = os.getenv("DOCS_FOLDER", "data")
INDEX_PATH = os.path.join(DATA_DIR, "faiss_index")
CONTEXT_PATH = os.getenv("CONTEXT_FILE", "context/context.txt")

# === Helpers ===
def load_documents():
    # Load both .txt and .md files
    txt_loader = DirectoryLoader(DATA_DIR, glob="**/*.txt", loader_cls=TextLoader)
    md_loader = DirectoryLoader(DATA_DIR, glob="**/*.md", loader_cls=TextLoader)

    raw_docs = []
    raw_docs.extend(txt_loader.load())
    raw_docs.extend(md_loader.load())
    
    # Clean the content of documents to remove BOM and other encoding issues
    for doc in raw_docs:
        # Remove BOM and normalize the text
        doc.page_content = doc.page_content.encode('utf-8').decode('utf-8-sig').strip()
        
    splitter = RecursiveCharacterTextSplitter(chunk_size=1200, chunk_overlap=150)
    return splitter.split_documents(raw_docs)

def build_or_load_vectorstore():
    embeddings = OpenAIEmbeddings()
    os.makedirs(INDEX_PATH, exist_ok=True)
    index_file = os.path.join(INDEX_PATH, "index.faiss")
    if os.path.exists(index_file):
        print("[FAISS] Loading existing vector store from disk.")
        return FAISS.load_local(INDEX_PATH, embeddings, allow_dangerous_deserialization=True)
    print("[FAISS] Building new vector store.")
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
    vectorstore = build_or_load_vectorstore()
    retriever = vectorstore.as_retriever(search_kwargs={"k": 6})
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
    llm = ChatOpenAI(model=model_name)

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

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
    loader = DirectoryLoader(DATA_DIR, glob="**/*.txt", loader_cls=TextLoader)
    raw_docs = loader.load()
    
    # Clean the content of documents to remove BOM and other encoding issues
    for doc in raw_docs:
        # Remove BOM and normalize the text
        doc.page_content = doc.page_content.encode('utf-8').decode('utf-8-sig').strip()
        
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
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
def build_rag_chain(context_path=CONTEXT_PATH, model_name="gpt-4-1106-preview"):
    vectorstore = build_or_load_vectorstore()
    retriever = vectorstore.as_retriever()
    context = load_context(context_path)

    system_prompt = SystemMessagePromptTemplate.from_template(
        """Usted es un asistente IA especializado para socios de la Cooperativa Multiactiva Nazareth.

DEBE SEGUIR EXACTAMENTE ESTAS INSTRUCCIONES:
{instructions}

IMPORTANTE: Siga todas las reglas especificadas en las instrucciones, especialmente:
- Use markdown para énfasis (*texto*) en nombres de la cooperativa, servicios y productos
- Estructure respuestas con listas cuando sea apropiado  
- Incluya enlaces completos tal como aparecen en los documentos
- Use emojis apropiadamente
- Termine SIEMPRE con una frase cooperativista motivacional en *cursiva*
- Cite la fuente exactamente como se indica en las instrucciones
- Responda formalmente con "usted" pero de manera simple y motivadora
- Ofrezca productos/servicios relacionados (venta cruzada)
- Use EXCLUSIVAMENTE la información de la base de conocimientos
"""
    )

    human_prompt = HumanMessagePromptTemplate.from_template(
        """BASE DE CONOCIMIENTO (documentos relevantes):
{contextual_documents}

PREGUNTA DEL SOCIO:
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

    def answer_question(inputs):
        query = str(inputs["query"])
        instructions = inputs["instructions"]
        
        # Get relevant documents
        docs = retriever.invoke(query)
        formatted_docs = format_docs(docs)
        
        # Create chat prompt with all inputs
        messages = chat_prompt.format_messages(
            query=query,
            instructions=instructions,
            contextual_documents=formatted_docs
        )
        
        # Get response from LLM
        response = llm.invoke(messages)
        return response.content
    
    qa_chain = RunnableLambda(answer_question)

    return qa_chain, context

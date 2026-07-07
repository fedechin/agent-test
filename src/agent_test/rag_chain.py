import os
import re
import glob
from dotenv import load_dotenv
from langchain.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from langchain_core.runnables import RunnableLambda

load_dotenv()

# === Configuration ===
DATA_DIR = os.getenv("DOCS_FOLDER", "data")
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


# === Base de conocimiento ===
# La base es chica (~8k tokens): entra entera en el contexto del modelo muchas
# veces. Por eso NO usamos recuperación vectorial (FAISS/BM25): buscar fragmentos
# en un corpus tan pequeño no aporta nada y, peor, introducía contaminación entre
# secciones (p.ej. traía horarios de "recepción" al preguntar por el Country Club
# y el modelo inventaba). Inyectamos TODA la base en cada llamada; así el modelo
# nunca "no encuentra" un dato ni recibe el fragmento equivocado.
def load_knowledge_base(data_dir=DATA_DIR):
    """Concatena el texto completo de todos los .md y .txt de la base, cada uno
    precedido por su nombre de archivo para que el modelo pueda ubicar la fuente."""
    paths = sorted(
        glob.glob(os.path.join(data_dir, "**", "*.md"), recursive=True)
        + glob.glob(os.path.join(data_dir, "**", "*.txt"), recursive=True)
    )
    partes = []
    for p in paths:
        with open(p, "r", encoding="utf-8-sig", errors="ignore") as f:
            texto = f.read().strip()
        if texto:
            partes.append(f"===== ARCHIVO: {os.path.basename(p)} =====\n{texto}")
    return "\n\n".join(partes)


def load_context(context_path=CONTEXT_PATH):
    if not os.path.exists(context_path):
        print(f"[WARN] Context file '{context_path}' not found.")
        return ""
    with open(context_path, "r", encoding="utf-8") as f:
        return f.read()


# === Custom RAG Chain ===
def build_rag_chain(context_path=CONTEXT_PATH, model_name="gpt-4o-mini"):
    knowledge_base = load_knowledge_base()
    context = load_context(context_path)

    # El bloque estático (instrucciones + base de conocimiento completa) va en el
    # mensaje de sistema, SIEMPRE idéntico y al principio del prompt. OpenAI cachea
    # automáticamente el prefijo (>1024 tokens), así que aunque mandemos la base
    # entera en cada llamada, el costo real de esos tokens es mínimo tras la primera.
    # Lo variable (historial + pregunta) va después, en el mensaje humano.
    system_prompt = SystemMessagePromptTemplate.from_template(
        """Usted es un asistente IA especializado para socios de la Cooperativa Multiactiva Nazareth.

DEBE SEGUIR EXACTAMENTE ESTAS INSTRUCCIONES:
{instructions}

BASE DE CONOCIMIENTO COMPLETA (use EXCLUSIVAMENTE esta información; si el dato pedido no está aquí, derive según la regla 3.1):
{knowledge_base}"""
    )

    human_prompt = HumanMessagePromptTemplate.from_template(
        """{conversation_history}PREGUNTA ACTUAL DEL SOCIO:
{query}
"""
    )

    chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])
    # Temperatura 0: respuestas deterministas y sin "relleno" creativo. Priorizamos
    # evitar alucinaciones por sobre la naturalidad del tono.
    llm = ChatOpenAI(model=model_name, temperature=0.0)

    # Tope de longitud para los mensajes del ASISTENTE en el historial. Las
    # respuestas largas previas (p.ej. un listado con formato) actúan como ejemplos
    # few-shot y el modelo copia ese formato, ignorando las reglas de formato
    # actuales (regla 3.3). Comprimir los saltos de línea y truncar destruye esa
    # "plantilla" pero conserva el contexto de qué se habló. Los mensajes del socio
    # se dejan intactos.
    HISTORY_ASSISTANT_MAXLEN = 150

    # Igual que con el formato, una derivación previa ("No tengo esa información...")
    # en el historial actúa como ejemplo y el modelo la copia: una vez que deriva,
    # sigue derivando incluso preguntas que SÍ puede responder. La reemplazamos por
    # una nota TOTALMENTE neutra: cualquier mención de "no tenía el dato" o "derivó"
    # vuelve a anclar la derivación (verificado), así que el marcador no debe
    # insinuar ni derivación ni falta de datos.
    DERIVATION_SIGNATURE = "derivar su consulta a un agente humano"
    DERIVATION_PLACEHOLDER = "(Respuesta a una consulta anterior.)"

    def format_conversation_history(history):
        """Format conversation history for the prompt."""
        if not history:
            return ""

        formatted = "HISTORIAL DE LA CONVERSACIÓN:\n"
        for msg in history:
            is_customer = msg["role"] == "customer"
            role_label = "Socio" if is_customer else "Asistente"
            content = str(msg["content"])
            if not is_customer:
                content = re.sub(r"\s+", " ", content).strip()
                if DERIVATION_SIGNATURE in content.lower():
                    # Neutralizar la derivación para que no se copie.
                    content = DERIVATION_PLACEHOLDER
                elif len(content) > HISTORY_ASSISTANT_MAXLEN:
                    # Truncar para no anclar el formato.
                    content = content[:HISTORY_ASSISTANT_MAXLEN] + " […]"
            formatted += f"{role_label}: {content}\n"
        formatted += "\n"
        return formatted

    def answer_question(inputs):
        query = str(inputs["query"])
        instructions = inputs["instructions"]
        conversation_history = inputs.get("conversation_history", [])

        # Con la base entera en contexto no hace falta reformular la pregunta ni
        # recuperar fragmentos: el modelo ve todo y resuelve los seguimientos con
        # el historial que le pasamos en el mismo prompt.
        formatted_history = format_conversation_history(conversation_history)

        messages = chat_prompt.format_messages(
            query=query,
            instructions=instructions,
            knowledge_base=knowledge_base,
            conversation_history=formatted_history,
        )

        response = llm.invoke(messages)
        return response.content

    qa_chain = RunnableLambda(answer_question)

    return qa_chain, context

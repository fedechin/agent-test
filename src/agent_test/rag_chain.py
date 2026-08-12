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

# Áreas de derivación (regla 3.1 del contexto) para cuando no hay información.
# La etiqueta va como [DERIVAR_HUMANO:<AREA>]: el webhook la detecta para escalar
# la conversación (request_human_takeover) y luego la elimina del texto antes de
# enviarlo al socio.
#
# El cliente (feedback 07jul26) pidió que ciertas consultas se deriven a un área
# concreta en lugar del conmutador general. Deliberadamente son POCAS áreas: los
# pedidos llegaron servicio por servicio (costos del centro médico, horarios de
# especialidades, canon de la precoop, extensión de alquiler...), pero agrupar los
# servicios afines evita que el socio reciba un número distinto por cada consulta
# y mantiene pocas colas en el panel. Para sumar un servicio nuevo casi siempre
# alcanza con mapearlo a un área existente, no con crear otra.
DERIVATION_AREAS = {
    # Consultas del Centro Médico que la cooperativa no publica en la base:
    # costos de especialidades, días y horarios de cada profesional.
    "CENTRO_MEDICO": {
        "label": "al Centro Médico",
        "contacto": "también puede llamar al 021 238 6777 int. 1800 o al 0981 770069",
    },
    # Consultas que gestiona el Departamento de Educación: precooperativa
    # (canon y cuota) y extensión de horario en el alquiler de salones.
    # Todavía no tenemos un número directo del área: usamos el conmutador.
    "EDUCACION": {
        "label": "al Departamento de Educación",
        "contacto": (
            "también puede llamar al (021) 552631 o acercarse a "
            "cualquiera de nuestras sucursales"
        ),
    },
    # Todo lo demás (incluidos los montos de ahorros, para los que el cliente
    # pidió derivar sin especificar área).
    "GENERAL": {
        "label": "a un agente humano",
        "contacto": (
            "también puede llamar al (021) 552631 o acercarse a "
            "cualquiera de nuestras sucursales"
        ),
    },
}

DEFAULT_DERIVATION_AREA = "GENERAL"


def derivation_message(area: str = DEFAULT_DERIVATION_AREA) -> str:
    """Frase de derivación completa, con la etiqueta que consume el webhook."""
    area = area.upper()
    if area not in DERIVATION_AREAS:
        area = DEFAULT_DERIVATION_AREA
    datos = DERIVATION_AREAS[area]
    return (
        f"[DERIVAR_HUMANO:{area}] No tengo esa información, pero voy a "
        f"derivar su consulta {datos['label']}, que se pondrá en contacto con "
        f"usted a la brevedad. Si lo prefiere, {datos['contacto']}."
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
    # Debe matchear las TRES variantes de la regla 3.1.1 (general, centro médico,
    # educación), por eso corta antes del área: "...derivar su consulta al Centro
    # Médico" y "...a un agente humano" comparten solo este prefijo.
    DERIVATION_SIGNATURE = "derivar su consulta"
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

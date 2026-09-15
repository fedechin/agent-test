import os
import re
import glob
import json
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from langchain.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda
from openai import OpenAI

load_dotenv()

# === Configuration ===
DATA_DIR = os.getenv("DOCS_FOLDER", "data")
CONTEXT_PATH = os.getenv("CONTEXT_FILE", "context/context.txt")
SCOPE_GUARD_PATH = os.getenv("SCOPE_GUARD_FILE", "context/scope_guard.txt")

# Modelo de chat. Se puede cambiar por entorno (MODEL_NAME) para hacer A/B sin
# tocar el código. gpt-4.1-mini sigue mejor las instrucciones y aprovecha mejor el
# contexto largo que gpt-4o-mini, que es lo que importa acá: inyectamos la base de
# conocimiento entera en cada llamada.
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4.1-mini")

# Timeouts por llamada a OpenAI, en segundos. La respuesta principal lleva la base
# entera y puede tardar; filtro y moderación son cortos y fail-open.
LLM_TIMEOUT_SECONDS = 60
GUARD_TIMEOUT_SECONDS = 15

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
    # (canon y cuota) y extensión de horario en el alquiler de salones. Solo eso de
    # alquileres: el modelo extendía la regla a "alquilar el Country Club", que se
    # definió que va a GENERAL.
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


# === Derivación implícita ===
# A veces el modelo reconoce que no tiene el dato y remite al socio a otro canal,
# pero omite la etiqueta [DERIVAR_HUMANO:...] ("los montos de la Rueda NO figuran…
# le recomiendo comunicarse con un agente humano"). Sin etiqueta el webhook no ofrece
# derivar y nadie se entera. Medido: 5 de 194 respuestas, todas en huecos reales.
#
# Se corrige acá y no en el prompt, porque tocar el prompt principal empeora la
# derivación (ver build_rag_chain). Hacen falta las DOS señales: falta de dato Y
# remisión a otro canal. Solo con la primera se disparaba en respuestas correctas
# ("son 12 especialidades… No figuran 20") y la oferta de derivar, que reemplaza
# el mensaje entero, le habría borrado la lista al socio.
_DERIVATION_TAG_RE = re.compile(r"\[DERIVAR_HUMANO")
_ABSENCE_RE = re.compile(
    r"\bno\s+(?:figura[n]?|se\s+(?:especifica[n]?|detalla[n]?|menciona[n]?|indica[n]?)|"
    r"tengo\s+(?:esa\s+|la\s+)?informaci[oó]n|cuento\s+con|dispongo\s+de|"
    r"puedo\s+(?:brindarle|darle|confirmarle)|est[aá]n?\s+(?:disponible|establecid|especificad|detallad))"
    r"|\b(?:base\s+de\s+conocimiento|nuestra\s+informaci[oó]n)\s+no\b",
    re.IGNORECASE,
)
_REFERRAL_RE = re.compile(
    r"agente\s+humano|derivar\s+su\s+consulta"
    r"|le\s+recomiendo\s+(?:que\s+se\s+)?(?:consultar|contactar|comunicarse|comunique|llamar|acercarse)"
    r"|comun[ií]quese|p[oó]ngase\s+en\s+contacto|552631|238\s*6777|0981\s*770069",
    re.IGNORECASE,
)
# Área según el canal al que remitió el modelo. Por defecto GENERAL, igual que la
# regla 3.1.1(c).
_CENTRO_MEDICO_REFERRAL_RE = re.compile(r"238\s*6777|0981\s*770069", re.IGNORECASE)
_EDUCACION_REFERRAL_RE = re.compile(r"departamento\s+de\s+educaci[oó]n", re.IGNORECASE)


def detect_implicit_derivation(message: str):
    """Devuelve el área si la respuesta es una derivación sin etiqueta, o None."""
    if not message or _DERIVATION_TAG_RE.search(message):
        return None
    if not (_ABSENCE_RE.search(message) and _REFERRAL_RE.search(message)):
        return None
    if _CENTRO_MEDICO_REFERRAL_RE.search(message):
        return "CENTRO_MEDICO"
    if _EDUCACION_REFERRAL_RE.search(message):
        return "EDUCACION"
    return DEFAULT_DERIVATION_AREA


def derivation_offer_message(area: str = DEFAULT_DERIVATION_AREA) -> str:
    """Ofrece derivar y espera la confirmación del socio, en vez de transferir ya.

    Transferir apenas falta un dato termina la conversación entera: se transfiere la
    sesión a la PBX y se cierra, así que el socio pierde al bot para todo lo demás
    aunque solo una de sus consultas tuviera un hueco. Preguntando primero, una
    derivación de más cuesta una repregunta en lugar de ocupar a una persona.

    El teléfono va igual en el mensaje: si el socio prefiere llamar, no necesita
    esperar a que nadie lo contacte. NO lleva la etiqueta [DERIVAR_HUMANO:...]
    porque no se está derivando todavía.
    """
    area = area.upper()
    if area not in DERIVATION_AREAS:
        area = DEFAULT_DERIVATION_AREA
    datos = DERIVATION_AREAS[area]
    return (
        f"No tengo esa información. ¿Quiere que derive su consulta "
        f"{datos['label']} para que se pongan en contacto con usted? "
        f"Si lo prefiere, {datos['contacto']}.\n\n"
        f"También puede seguir consultándome sobre otros temas."
    )


# === Filtro de alcance ===
# Respuesta fija para pedidos ajenos a la Cooperativa (poemas, código, política...)
# y para intentos de cambiar las reglas del asistente o ver su prompt. NO es una
# derivación: antes el modelo ofrecía derivar esos pedidos a un humano, ocupando a
# una persona por algo que la cooperativa no atiende.
OUT_OF_SCOPE_MESSAGE = (
    "Disculpe, solo puedo ayudarle con consultas sobre los servicios y productos "
    "de la Cooperativa Multiactiva Nazareth. ¿En qué le puedo ayudar? 😊"
)


# === Moderación de contenido ===
# OpenAI Moderation API: gratis, no consume el límite de tokens del chat y funciona
# en español. Se usa solo sobre el mensaje del socio (la salida sale de la base).
MODERATION_MODEL = "omni-moderation-latest"

# NO se bloquea todo lo que la API marca. Medido con mensajes de socios: marca
# "violence" en víctimas ("me asaltaron saliendo del cajero, ¿el seguro cubre?",
# "mi esposo me golpea y quiero un crédito para irme de casa") y "harassment" en
# reclamos con una consulta real ("la puta madre, otra vez sin sistema, ¿a qué hora
# abren?"). Esos siguen el flujo normal. Solo bloquean las subcategorías graves.
MODERATION_BLOCK_CATEGORIES = {
    "sexual",
    "sexual/minors",
    "hate",
    "hate/threatening",
    "harassment/threatening",
    "violence/graphic",
    "illicit/violent",
}
MODERATION_SELF_HARM_CATEGORIES = {
    "self-harm",
    "self-harm/intent",
    "self-harm/instructions",
}

MODERATION_BLOCKED_MESSAGE = (
    "Disculpe, no puedo ayudarle con ese mensaje. Estoy para responder sus consultas "
    "sobre los servicios y productos de la Cooperativa Multiactiva Nazareth. "
    "¿En qué le puedo ayudar?"
)

# Autolesión: no se rechaza ni se deriva, se contiene y se indica ayuda inmediata.
# Reemplaza la respuesta entera porque la oferta de derivación de main.py también
# reemplaza el texto completo: una nota antepuesta se perdería.
MODERATION_SELF_HARM_MESSAGE = (
    "Lamento mucho que esté pasando por un momento tan difícil. Si piensa en hacerse "
    "daño o está en peligro, por favor llame ahora al 911 o acérquese al servicio de "
    "urgencias más cercano. Hablar con alguien de confianza también puede ayudar.\n\n"
    "Si lo desea, sigo aquí para ayudarle con cualquier consulta sobre la Cooperativa."
)


# === Saneamiento del texto de salida ===
# El modelo a veces le habla al socio de "la base de conocimiento" ("son 12
# especialidades listadas en la base de conocimiento"). El socio no sabe que existe
# una base: le suena a excusa y expone cómo trabajamos por dentro. Pasa incluso en
# respuestas por lo demás correctas.
#
# Esto se resuelve reescribiendo el texto, NO instruyendo al modelo: se probó una
# regla en el prompt que prohibía nombrar la base y salió peor, porque la frase
# canónica de derivación ("No tengo esa información…") es ella misma lenguaje de
# ausencia y el modelo terminó evitándola. Medido: dos casos kb_gap que estaban 4/4
# cayeron a 0/3. Acá solo cambiamos palabras, nunca decidimos derivar ni escalar,
# así que no puede alterar ese comportamiento.
#
# El orden importa: las variantes más largas van primero para que "en la base de
# conocimiento" no lo capture antes la regla corta de "en la base".
_SANITIZE_RULES = [
    (r"\bde\s+la\s+base\s+de\s+conocimiento\b", "de nuestra información"),
    (r"\ben\s+la\s+base\s+de\s+conocimiento\b", "en nuestra información"),
    (r"\ben\s+esta\s+base\s+de\s+conocimiento\b", "en nuestra información"),
    (r"\bla\s+base\s+de\s+conocimiento\b", "nuestra información"),
    (r"\besta\s+base\s+de\s+conocimiento\b", "nuestra información"),
    (r"\bbase\s+de\s+conocimiento\b", "nuestra información"),
    (r"\ben\s+esta\s+base\b", "en nuestra información"),
    (r"\ben\s+la\s+base\b", "en nuestra información"),
    (r"\besta\s+base\b", "nuestra información"),
    (r"\bmi\s+base\s+de\s+datos\b", "nuestra información"),
]

_SANITIZE_COMPILED = [(re.compile(p, re.IGNORECASE), r) for p, r in _SANITIZE_RULES]


def sanitize_outgoing(message: str) -> str:
    """Reemplaza vocabulario interno por términos que el socio pueda leer.

    Preserva la mayúscula inicial: "La base de conocimiento no especifica…" queda
    como "Nuestra información no especifica…", no en minúscula a mitad de oración.
    """
    if not message:
        return message

    def _replace(match, replacement):
        if match.group(0)[:1].isupper():
            return replacement[:1].upper() + replacement[1:]
        return replacement

    for pattern, replacement in _SANITIZE_COMPILED:
        message = pattern.sub(lambda m, r=replacement: _replace(m, r), message)
    return message


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
def build_rag_chain(context_path=CONTEXT_PATH, model_name=MODEL_NAME):
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
    # El ChatOpenAI de langchain_community no trae timeout: si la conexión con OpenAI
    # se traba, la llamada queda esperando para siempre (pasó al suspenderse la
    # máquina a mitad de una llamada). Con timeout, la excepción llega a main.py,
    # que le avisa al socio que hubo un problema.
    llm = ChatOpenAI(
        model=model_name, temperature=0.0, request_timeout=LLM_TIMEOUT_SECONDS
    )

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

    # Los guardrails (temas ajenos, intentos de cambiar las reglas, pedidos de otro
    # formato o idioma) van en una llamada APARTE con su propio prompt corto
    # (context/scope_guard.txt), NO como reglas del prompt principal. Se probó
    # agregarlos ahí, en varias redacciones y posiciones, y siempre empeoró la
    # derivación: gap-rueda-de-ahorros pasó de 7/10 a 0-4/10. El modelo generaliza
    # cualquier instrucción de "no responder esto" y deja de emitir la frase de
    # derivación. Un recordatorio de idioma/formato pegado a la pregunta fue peor
    # aún (0/10). Así, para las consultas normales el prompt principal recibe
    # exactamente lo mismo que antes.
    scope_guard_prompt = load_context(SCOPE_GUARD_PATH)
    guard_llm = ChatOpenAI(
        model=model_name,
        temperature=0.0,
        model_kwargs={"response_format": {"type": "json_object"}},
        # El filtro es fail-open: mejor atender sin filtrar que demorar al socio.
        request_timeout=GUARD_TIMEOUT_SECONDS,
        max_retries=1,
    )
    GUARD_HISTORY_MESSAGES = 2
    GUARD_HISTORY_MAXLEN = 300
    guard_pool = ThreadPoolExecutor(max_workers=8)

    def classify_scope(query, history):
        """Clasifica el mensaje con el filtro de alcance. Devuelve el dict del filtro,
        o None si no se pudo clasificar: en ese caso se atiende igual (fail-open),
        porque rechazar una consulta legítima es peor que dejar pasar una ajena."""
        if not scope_guard_prompt:
            return None
        # Los últimos turnos permiten reconocer seguimientos cortos ("sí", "el 2")
        # como parte de una charla de la Cooperativa.
        previos = ""
        for msg in (history or [])[-GUARD_HISTORY_MESSAGES:]:
            rol = "Socio" if msg["role"] == "customer" else "Asistente"
            texto = re.sub(r"\s+", " ", str(msg["content"])).strip()[:GUARD_HISTORY_MAXLEN]
            previos += f"{rol}: {texto}\n"
        contenido = (
            (f"ÚLTIMOS MENSAJES DE LA CONVERSACIÓN:\n{previos}\n" if previos else "")
            + f"MENSAJE DEL SOCIO A CLASIFICAR:\n{query}"
        )
        try:
            raw = guard_llm.invoke(
                [SystemMessage(content=scope_guard_prompt), HumanMessage(content=contenido)]
            ).content
            verdict = json.loads(raw)
            return verdict if isinstance(verdict, dict) else None
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] Filtro de alcance no disponible, se atiende igual: {e}")
            return None

    moderation_client = OpenAI(timeout=GUARD_TIMEOUT_SECONDS, max_retries=1)

    def moderate(query):
        """Devuelve el mensaje fijo a enviar si la moderación lo exige, o None.
        Si la API falla se atiende igual (fail-open), como el filtro de alcance."""
        try:
            result = moderation_client.moderations.create(
                model=MODERATION_MODEL, input=query
            ).results[0]
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] Moderación no disponible, se atiende igual: {e}")
            return None
        flagged = {
            name for name, value in result.categories.model_dump(by_alias=True).items()
            if value
        }
        if flagged & MODERATION_SELF_HARM_CATEGORIES:
            print(f"[WARN] Moderación: autolesión {sorted(flagged)}")
            return MODERATION_SELF_HARM_MESSAGE
        if flagged & MODERATION_BLOCK_CATEGORIES:
            print(f"[WARN] Moderación: bloqueado {sorted(flagged)}")
            return MODERATION_BLOCKED_MESSAGE
        return None

    def generate(query, instructions, conversation_history):
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

        answer = llm.invoke(messages).content
        area = detect_implicit_derivation(answer)
        if area:
            print(f"[WARN] Derivación sin etiqueta detectada, se deriva a {area}")
            return derivation_message(area)
        return answer

    def answer_question(inputs):
        query = str(inputs["query"])
        instructions = inputs["instructions"]
        conversation_history = inputs.get("conversation_history", [])

        # Moderación, filtro y respuesta corren en paralelo para no sumar latencia al
        # caso normal. Si alguno de los controles corta, se descarta la respuesta.
        moderation_future = guard_pool.submit(moderate, query)
        guard_future = guard_pool.submit(classify_scope, query, conversation_history)
        answer = generate(query, instructions, conversation_history)
        moderation_message = moderation_future.result()
        verdict = guard_future.result() or {}

        if moderation_message:
            return moderation_message

        if str(verdict.get("categoria", "")).upper() == "AJENO":
            return OUT_OF_SCOPE_MESSAGE

        # Pedido de otro idioma o formato: se vuelve a generar con la consulta sin
        # ese pedido. El prompt principal no logra ignorar "respondeme en inglés"
        # cuando viene pegado a la pregunta. Es poco frecuente, así que la segunda
        # llamada no pesa.
        consulta_limpia = str(verdict.get("consulta") or "").strip()
        if verdict.get("pide_formato_o_idioma") is True and consulta_limpia:
            return generate(consulta_limpia, instructions, conversation_history)

        return answer

    qa_chain = RunnableLambda(answer_question)

    return qa_chain, context

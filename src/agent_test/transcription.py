"""
Transcripción de notas de voz a texto, para que el socio pueda preguntar hablando.

Antes, cualquier audio se escalaba a un humano sin siquiera saber qué decía. La
mayoría de esas notas son preguntas que el bot ya sabe contestar, así que
transcribirlas y meterlas por el camino de texto de siempre evita ocupar a una
persona. Si la transcripción falla, se vuelve al comportamiento anterior.
"""
import logging
import os
from typing import Optional

from openai import OpenAI

logger = logging.getLogger("rag_agent")

# gpt-4o-mini-transcribe es el modelo de transcripción de OpenAI: más barato y
# rápido que whisper-1 y suficiente para notas de voz cortas de WhatsApp.
TRANSCRIPTION_MODEL = os.getenv("TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe")

# Interruptor por si hay que desactivarlo sin desplegar.
ENABLE_AUDIO_TRANSCRIPTION = os.getenv("ENABLE_AUDIO_TRANSCRIPTION", "true").lower() in (
    "1", "true", "yes", "si", "sí",
)

# El endpoint de transcripción deduce el formato de la EXTENSIÓN del nombre de
# archivo que le pasamos, y el nombre que manda Yeastar no es confiable: las notas
# de voz de WhatsApp llegan como "audio/ogg; codecs=opus", que puede mapear a
# ".oga" (rechazado) o directamente a nada. Por eso el formato se deduce de los
# magic bytes del contenido, no del nombre.
_MAGIC_EXT = (
    (b"OggS", ".ogg"),
    (b"RIFF", ".wav"),
    (b"\x1aE\xdf\xa3", ".webm"),
    (b"fLaC", ".flac"),
    (b"ID3", ".mp3"),
)

# Tope de tamaño: el límite de OpenAI es 25 MB. Una nota de voz normal pesa muy
# poco, así que algo mucho más grande es señal de otra cosa (un video, p.ej.).
MAX_AUDIO_BYTES = 25 * 1024 * 1024

_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


def detect_audio_ext(data: bytes) -> Optional[str]:
    """Identifica el contenedor de audio por sus magic bytes, o None."""
    if not data:
        return None
    for magic, ext in _MAGIC_EXT:
        if data[: len(magic)] == magic:
            return ext
    if data[4:8] == b"ftyp":  # ISO base media (MP4 / M4A)
        return ".m4a"
    if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:  # frame sync MP3
        return ".mp3"
    return None


def api_filename(data: bytes, fallback_name: str = "") -> str:
    """Nombre con la extensión REAL del audio, que es lo que mira la API."""
    ext = detect_audio_ext(data)
    if ext is None:
        suffix = os.path.splitext(fallback_name or "")[1].lower()
        # ".oga" es lo que suele traer WhatsApp y la API lo rechaza; ogg sí sirve.
        ext = ".ogg" if suffix in ("", ".oga") else suffix
    return f"audio{ext}"


def is_audio(content_type: str = "", filename: str = "", data: bytes = b"") -> bool:
    """¿Este adjunto es una nota de voz? Se mira el tipo declarado, la extensión y,
    como criterio más confiable, el contenido."""
    if content_type and content_type.lower().startswith("audio"):
        return True
    if filename and os.path.splitext(filename)[1].lower() in (
        ".ogg", ".oga", ".opus", ".mp3", ".m4a", ".wav", ".amr", ".webm", ".flac",
    ):
        return True
    return detect_audio_ext(data) is not None


def transcribe_audio(data: bytes, filename: str = "") -> Optional[str]:
    """Transcribe una nota de voz a texto en español.

    Devuelve el texto, o None si falla o sale vacío. Quien llama trata None como
    "no se pudo entender" y escala a un humano, que es el comportamiento previo.
    """
    if not ENABLE_AUDIO_TRANSCRIPTION:
        logger.info("Transcripción de audio desactivada por configuración")
        return None
    if not data:
        return None
    if len(data) > MAX_AUDIO_BYTES:
        logger.warning(
            f"Audio de {len(data)} bytes supera el máximo de {MAX_AUDIO_BYTES}; no se transcribe"
        )
        return None

    try:
        nombre = api_filename(data, filename)
        response = _get_client().audio.transcriptions.create(
            model=TRANSCRIPTION_MODEL,
            file=(nombre, data),
            language="es",
        )
        texto = (getattr(response, "text", "") or "").strip()
        if not texto:
            logger.warning(f"Transcripción vacía para {nombre}")
            return None
        logger.info(f"🎤 Audio transcripto ({nombre}, {len(texto)} chars): {texto[:120]}")
        return texto
    except Exception as e:  # noqa: BLE001
        logger.exception(f"Falló la transcripción del audio: {e}")
        return None

"""
Conversation management and human handover logic.
"""
import os
import re
import unicodedata
from typing import Optional, List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from .models import Conversation, Message, ConversationStatus, ConversationSource, HumanAgent
from .database import get_db

# Corte de sesión por inactividad. Sin esto una conversación es PERMANENTE: se crea
# con el primer mensaje del socio y se reutiliza para siempre, porque
# get_or_create_conversation solo excluye las RESOLVED y nada las marcaba así por su
# cuenta. En producción llegamos a tener una conversación de 170 mensajes a lo largo
# de 4 meses; el historial que se le inyecta al modelo salía de ahí, mezclando temas
# de meses distintos. Al pasar el corte cerramos la vieja y abrimos una nueva, así
# "la conversación actual" existe de verdad.
SESSION_TIMEOUT_HOURS = float(os.getenv("CONVERSATION_SESSION_TIMEOUT_HOURS", "12"))

class ConversationManager:
    """Manages conversation state and human handover."""

    def __init__(self):
        self.human_takeover_keywords = [
            # Usted form (formal)
            "hablar con humano", "hablar con una persona", "hablar con alguien",
            "quiero hablar con humano", "necesito hablar con persona",
            "quiero hablar con un representante", "necesito ayuda humana",
            "puede transferirme", "puede pasarme", "puede conectarme",
            "puedo hablar con", "puedo hablar con un operador", "puedo hablar con una persona",
            "transferir a humano", "transferir a una persona",
            "contacto humano", "persona real", "agente humano",
            "atención al cliente", "soporte humano", "ayuda humana",
            "hablar con operador", "hablar con un operador",

            # Vos form (Paraguayan/Rioplatense)
            "querés transferirme", "podés transferirme", "podés pasarme",
            "podes transferir", "podes pasar", "transferime", "pasame",
            "quiero hablar con vos", "necesito hablar con vos",
            "conectame con", "pasame con", "hablá con",
            "querés conectarme", "necesitás ayudarme",

            # General phrases
            "hablar con alguien", "hablar con operador",
            "no entiendo", "esto no funciona", "problema grave",
            "ayuda por favor", "necesito ayuda", "ayuda urgente",
            "un humano", "una persona", "alguien que me ayude",

            # English
            "speak to human", "talk to human", "human agent", "transfer to human"
        ]

        # Respuestas con las que el socio ACEPTA que lo derivemos. Se comparan sobre
        # el mensaje completo normalizado (sin tildes ni signos), no por substring:
        # "si" como substring aparece en "necesito", "siempre", "servicio"...
        self.affirmative_replies = {
            "si", "sii", "siii", "sip", "si por favor", "si porfa", "si porfavor",
            "si gracias", "si dale", "si quiero", "si necesito", "claro", "claro que si",
            "dale", "dale gracias", "ok", "oka", "okey", "okay", "bueno", "buenisimo",
            "perfecto", "listo", "de una", "obvio", "por favor", "porfa", "porfavor",
            "quiero", "necesito", "me gustaria", "comunicame", "comunicame por favor",
            "transferime", "pasame", "conectame", "yes", "sure",
            "si quiero hablar con un agente", "si comunicame", "si transferime",
        }

        # Respuestas con las que el socio RECHAZA la derivación. Se listan aparte
        # (en vez de tratar "todo lo que no es sí" como no) para poder loguear la
        # diferencia entre un no explícito y un cambio de tema.
        self.negative_replies = {
            "no", "nop", "no gracias", "no por ahora", "ahora no", "todavia no",
            "despues", "mas tarde", "luego", "no hace falta", "no es necesario",
            "esta bien asi", "no quiero", "nada mas", "no nada", "listo gracias",
            "gracias", "muchas gracias", "ok gracias", "no thanks", "no thank you",
        }

    @staticmethod
    def _normalize_reply(text: Optional[str]) -> str:
        """Minúsculas, sin tildes, sin signos ni espacios de más."""
        if not text:
            return ""
        text = unicodedata.normalize("NFD", text.lower().strip())
        text = "".join(c for c in text if unicodedata.category(c) != "Mn")
        text = re.sub(r"[^\w\s]", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def interpret_derivation_reply(self, message_text: Optional[str]) -> str:
        """Interpreta la respuesta del socio a "¿quiere que lo derive?".

        Devuelve "yes", "no" u "other" (el socio ignoró la pregunta y consultó otra
        cosa). Ante la duda devuelve "other", NUNCA "yes": transferir de más ocupa a
        una persona y corta la conversación, mientras que no transferir solo cuesta
        que el socio lo pida de nuevo. Ese es el error barato.
        """
        norm = self._normalize_reply(message_text)
        if not norm:
            return "other"
        if norm in self.affirmative_replies:
            return "yes"
        if norm in self.negative_replies:
            return "no"
        # Mensajes cortos que arrancan afirmando ("si por favor derivame", "dale
        # gracias"). El tope de palabras evita capturar una pregunta nueva que
        # casualmente empiece con "si" ("si tengo 3 créditos, cuánto pago?").
        palabras = norm.split()
        if len(palabras) <= 4 and palabras[0] in {"si", "sii", "dale", "ok", "okey", "claro", "bueno"}:
            return "yes"
        if len(palabras) <= 4 and palabras[0] in {"no", "nop"}:
            return "no"
        return "other"

    def set_pending_derivation(self, conversation_id: int, area: str, db: Session) -> None:
        """Registra que se le ofreció al socio derivar al área indicada."""
        conversation = db.query(Conversation).filter(
            Conversation.id == conversation_id
        ).first()
        if conversation:
            conversation.pending_derivation_area = area
            db.commit()

    def clear_pending_derivation(self, conversation_id: int, db: Session) -> None:
        """Descarta la derivación ofrecida (el socio dijo que no o cambió de tema)."""
        conversation = db.query(Conversation).filter(
            Conversation.id == conversation_id
        ).first()
        if conversation and conversation.pending_derivation_area:
            conversation.pending_derivation_area = None
            db.commit()

    def get_or_create_conversation(self, whatsapp_number: str, db: Session,
                                    source: ConversationSource = ConversationSource.TWILIO,
                                    yeastar_session_id: Optional[int] = None) -> Conversation:
        """Get existing conversation or create new one."""
        conversation = db.query(Conversation).filter(
            Conversation.whatsapp_number == whatsapp_number,
            Conversation.status.in_([
                ConversationStatus.ACTIVE_AI,
                ConversationStatus.PENDING_HUMAN,
                ConversationStatus.ACTIVE_HUMAN
            ])
        ).first()

        # Si la sesión quedó inactiva más que el corte, se cierra y se arranca una
        # nueva. El filtro de arriba ya deja fuera las RESOLVED, así que basta con
        # marcarla y soltar la referencia para caer en la rama de creación.
        if conversation and self.is_session_stale(conversation.id, db):
            conversation.status = ConversationStatus.RESOLVED
            db.commit()
            conversation = None

        if not conversation:
            conversation = Conversation(
                whatsapp_number=whatsapp_number,
                status=ConversationStatus.ACTIVE_AI,
                source=source,
                yeastar_session_id=yeastar_session_id
            )
            db.add(conversation)
            db.commit()
            db.refresh(conversation)
        elif yeastar_session_id and conversation.yeastar_session_id != yeastar_session_id:
            # Update session ID if it changed (new Yeastar session for same conversation)
            conversation.yeastar_session_id = yeastar_session_id
            db.commit()

        return conversation

    def is_session_stale(self, conversation_id: int, db: Session,
                         timeout_hours: Optional[float] = None) -> bool:
        """True si el último mensaje de la conversación es más viejo que el corte.

        Una conversación sin mensajes (recién creada) NUNCA es stale: si no, el
        registro se cerraría antes de poder usarse.

        Se compara contra datetime.utcnow() porque Message.timestamp lo escribe el
        servidor de base de datos con func.now() y en producción (Postgres en
        Railway) esa columna guarda UTC. Si algún día la DB corriera en otro huso,
        este cálculo se iría por esa diferencia.
        """
        if timeout_hours is None:
            timeout_hours = SESSION_TIMEOUT_HOURS
        if timeout_hours <= 0:
            return False

        last_ts = db.query(func.max(Message.timestamp)).filter(
            Message.conversation_id == conversation_id
        ).scalar()

        if last_ts is None:
            return False

        return (datetime.utcnow() - last_ts) > timedelta(hours=timeout_hours)

    def save_message(self, conversation_id: int, whatsapp_number: str,
                    message_text: str, is_from_customer: bool,
                    sender_type: str, db: Session, num_media: int = 0,
                    media_urls: Optional[str] = None,
                    media_content_types: Optional[str] = None) -> Message:
        """Save message to database."""
        message = Message(
            conversation_id=conversation_id,
            whatsapp_number=whatsapp_number,
            message_text=message_text,
            is_from_customer=is_from_customer,
            sender_type=sender_type,
            num_media=num_media,
            media_urls=media_urls,
            media_content_types=media_content_types
        )
        db.add(message)
        db.commit()
        db.refresh(message)
        return message

    def should_handover_to_human(self, message_text: Optional[str]) -> bool:
        """Check if message indicates customer wants to speak to human."""
        if not message_text:
            return False
        message_lower = message_text.lower()
        return any(keyword in message_lower for keyword in self.human_takeover_keywords)

    def request_human_takeover(self, conversation_id: int, db: Session) -> bool:
        """Request human takeover for conversation."""
        conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if conversation and conversation.status == ConversationStatus.ACTIVE_AI:
            conversation.status = ConversationStatus.PENDING_HUMAN
            db.commit()
            return True
        return False

    def assign_human_agent(self, conversation_id: int, agent_id: str, db: Session) -> bool:
        """Assign human agent to conversation."""
        conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if conversation and conversation.status == ConversationStatus.PENDING_HUMAN:
            conversation.status = ConversationStatus.ACTIVE_HUMAN
            conversation.human_agent_id = agent_id
            db.commit()
            return True
        return False

    def get_conversation_history(self, conversation_id: int, db: Session, limit: int = 50) -> List[Dict]:
        """Get conversation history for human agent."""
        messages = db.query(Message).filter(
            Message.conversation_id == conversation_id
        ).order_by(Message.timestamp.desc()).limit(limit).all()

        return [
            {
                "id": msg.id,
                "message": msg.message_text,
                "sender_type": msg.sender_type,
                "is_from_customer": msg.is_from_customer,
                "timestamp": msg.timestamp.isoformat(),
                "num_media": msg.num_media,
                "media_urls": msg.media_urls,
                "media_content_types": msg.media_content_types
            }
            for msg in reversed(messages)
        ]

    def get_recent_messages_for_context(self, conversation_id: int, db: Session, limit: int = 10) -> List[Dict]:
        """
        Get recent messages formatted for RAG context.
        Returns list of messages with role and content for conversation memory.
        """
        messages = db.query(Message).filter(
            Message.conversation_id == conversation_id
        ).order_by(Message.timestamp.desc()).limit(limit).all()

        # Format messages for RAG context (chronological order)
        formatted_messages = []
        for msg in reversed(messages):
            role = "customer" if msg.is_from_customer else msg.sender_type
            formatted_messages.append({
                "role": role,
                "content": msg.message_text,
                "timestamp": msg.timestamp.isoformat()
            })

        return formatted_messages

    def get_pending_conversations(self, db: Session) -> List[Dict]:
        """Get conversations pending human takeover (Twilio only - Yeastar uses Linkus)."""
        conversations = db.query(Conversation).filter(
            Conversation.status == ConversationStatus.PENDING_HUMAN,
            Conversation.source != ConversationSource.YEASTAR
        ).order_by(Conversation.updated_at.asc()).all()

        result = []
        for conv in conversations:
            # Get last few messages for context
            last_messages = db.query(Message).filter(
                Message.conversation_id == conv.id
            ).order_by(Message.timestamp.desc()).limit(3).all()

            result.append({
                "conversation_id": conv.id,
                "whatsapp_number": conv.whatsapp_number,
                "created_at": conv.created_at.isoformat(),
                "updated_at": conv.updated_at.isoformat(),
                "last_messages": [
                    {
                        "message": msg.message_text,
                        "sender_type": msg.sender_type,
                        "timestamp": msg.timestamp.isoformat()
                    }
                    for msg in reversed(last_messages)
                ]
            })

        return result

    def get_active_conversations(self, agent_id: str, db: Session) -> List[Dict]:
        """Get conversations currently assigned to a human agent (Twilio only - Yeastar uses Linkus)."""
        conversations = db.query(Conversation).filter(
            Conversation.status == ConversationStatus.ACTIVE_HUMAN,
            Conversation.human_agent_id == agent_id,
            Conversation.source != ConversationSource.YEASTAR
        ).order_by(Conversation.updated_at.desc()).all()

        result = []
        for conv in conversations:
            # Get last few messages for context
            last_messages = db.query(Message).filter(
                Message.conversation_id == conv.id
            ).order_by(Message.timestamp.desc()).limit(3).all()

            result.append({
                "conversation_id": conv.id,
                "whatsapp_number": conv.whatsapp_number,
                "created_at": conv.created_at.isoformat(),
                "updated_at": conv.updated_at.isoformat(),
                "last_messages": [
                    {
                        "message": msg.message_text,
                        "sender_type": msg.sender_type,
                        "timestamp": msg.timestamp.isoformat()
                    }
                    for msg in reversed(last_messages)
                ]
            })

        return result

    def end_conversation(self, conversation_id: int, db: Session) -> bool:
        """Mark conversation as resolved."""
        conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if conversation:
            conversation.status = ConversationStatus.RESOLVED
            db.commit()
            return True
        return False
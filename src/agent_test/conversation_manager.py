"""
Conversation management and human handover logic.
"""
import re
from typing import Optional, List, Dict
from sqlalchemy.orm import Session
from datetime import datetime
from .models import Conversation, Message, ConversationStatus, HumanAgent
from .database import get_db

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

    def get_or_create_conversation(self, whatsapp_number: str, db: Session) -> Conversation:
        """Get existing conversation or create new one."""
        conversation = db.query(Conversation).filter(
            Conversation.whatsapp_number == whatsapp_number,
            Conversation.status.in_([
                ConversationStatus.ACTIVE_AI,
                ConversationStatus.PENDING_HUMAN,
                ConversationStatus.ACTIVE_HUMAN
            ])
        ).first()

        if not conversation:
            conversation = Conversation(
                whatsapp_number=whatsapp_number,
                status=ConversationStatus.ACTIVE_AI
            )
            db.add(conversation)
            db.commit()
            db.refresh(conversation)

        return conversation

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
        """Get conversations pending human takeover."""
        conversations = db.query(Conversation).filter(
            Conversation.status == ConversationStatus.PENDING_HUMAN
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
        """Get conversations currently assigned to a human agent."""
        conversations = db.query(Conversation).filter(
            Conversation.status == ConversationStatus.ACTIVE_HUMAN,
            Conversation.human_agent_id == agent_id
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
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
            "hablar con humano", "hablar con una persona", "hablar con alguien",
            "quiero hablar con humano", "necesito hablar con persona",
            "speak to human", "talk to human", "human agent",
            "atención al cliente", "soporte humano", "ayuda humana",
            "no entiendo", "esto no funciona", "problema grave",
            "quiero hablar con un representante", "necesito ayuda humana",
            "contacto humano", "persona real", "agente humano"
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
                    sender_type: str, db: Session) -> Message:
        """Save message to database."""
        message = Message(
            conversation_id=conversation_id,
            whatsapp_number=whatsapp_number,
            message_text=message_text,
            is_from_customer=is_from_customer,
            sender_type=sender_type
        )
        db.add(message)
        db.commit()
        db.refresh(message)
        return message

    def should_handover_to_human(self, message_text: str) -> bool:
        """Check if message indicates customer wants to speak to human."""
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
                "timestamp": msg.timestamp.isoformat()
            }
            for msg in reversed(messages)
        ]

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
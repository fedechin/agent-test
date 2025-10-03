"""
Database models for conversation history and human handover system.
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
import enum

Base = declarative_base()

class ConversationStatus(enum.Enum):
    ACTIVE_AI = "active_ai"
    PENDING_HUMAN = "pending_human"
    ACTIVE_HUMAN = "active_human"
    RESOLVED = "resolved"

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    whatsapp_number = Column(String(20), nullable=False, index=True)
    status = Column(Enum(ConversationStatus), default=ConversationStatus.ACTIVE_AI)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    human_agent_id = Column(String(50), nullable=True)

class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, nullable=False, index=True)
    whatsapp_number = Column(String(20), nullable=False)
    message_text = Column(Text, nullable=False)
    is_from_customer = Column(Boolean, nullable=False)
    sender_type = Column(String(20), nullable=False)  # 'customer', 'ai', 'human'
    timestamp = Column(DateTime, server_default=func.now())

class HumanAgent(Base):
    __tablename__ = "human_agents"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String(50), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    email = Column(String(100), nullable=False)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    max_concurrent_conversations = Column(Integer, default=5)
    created_at = Column(DateTime, server_default=func.now())
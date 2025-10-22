"""
Authentication utilities for the admin dashboard.
"""
import os
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException, status, Cookie
from fastapi.security import HTTPBearer
from .models import HumanAgent, AgentRole
from .database import get_db

# Security configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 hours

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str) -> Optional[str]:
    """Verify JWT token and return agent_id if valid."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        agent_id: str = payload.get("sub")
        if agent_id is None:
            return None
        return agent_id
    except JWTError:
        return None

def authenticate_agent(agent_id: str, password: str, db: Session) -> Optional[HumanAgent]:
    """Authenticate an agent with agent_id and password."""
    agent = db.query(HumanAgent).filter(
        HumanAgent.agent_id == agent_id,
        HumanAgent.is_active == True
    ).first()

    if not agent or not verify_password(password, agent.password_hash):
        return None
    return agent

def get_current_agent(
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db)
) -> HumanAgent:
    """Get current authenticated agent from cookie token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not access_token:
        raise credentials_exception

    agent_id = verify_token(access_token)
    if agent_id is None:
        raise credentials_exception

    agent = db.query(HumanAgent).filter(
        HumanAgent.agent_id == agent_id,
        HumanAgent.is_active == True
    ).first()

    if agent is None:
        raise credentials_exception

    return agent

def get_current_admin(
    current_agent: HumanAgent = Depends(get_current_agent)
) -> HumanAgent:
    """Verify that the current agent has admin role."""
    if current_agent.role != AgentRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return current_agent
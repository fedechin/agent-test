from fastapi import FastAPI, Form, Depends, HTTPException, Request, Response as FastAPIResponse
from fastapi.responses import Response, JSONResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.runnables import Runnable
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from sqlalchemy.orm import Session
from dotenv import load_dotenv
import logging
from logging.handlers import RotatingFileHandler
import os
from typing import List, Dict
from datetime import timedelta

from .rag_chain import build_rag_chain
from .database import get_db, create_tables
from .conversation_manager import ConversationManager
from .models import ConversationStatus, HumanAgent
from .auth import authenticate_agent, create_access_token, get_current_agent, get_password_hash, ACCESS_TOKEN_EXPIRE_MINUTES
from .security import validate_webhook_request

load_dotenv()

# === Logging Setup ===
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("rag_agent")
logger.setLevel(logging.INFO)

handler = RotatingFileHandler(
    filename=f"{LOG_DIR}/rag_agent.log",
    maxBytes=5_000_000,
    backupCount=5
)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

# === FastAPI App ===
app = FastAPI(title="Cooperativa Nazareth RAG Agent", description="RAG agent for Cooperativa Multiactiva Nazareth with human handover")

# === Create directories for static files and templates ===
os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)

# === Static files and templates ===
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# === Optional: CORS for dev/frontend integration ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TIP: Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Initialize components ===
conversation_manager = ConversationManager()

# === Configuration ===
CONVERSATION_HISTORY_LIMIT = int(os.getenv("CONVERSATION_HISTORY_LIMIT", "10"))

# === Twilio setup ===
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM")

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN) if TWILIO_ACCOUNT_SID else None

# === Build RAG chain once and store globally ===
qa_chain, context = build_rag_chain()

# === Create database tables on startup ===
@app.on_event("startup")
async def startup_event():
    create_tables()
    logger.info("🚀 Cooperativa Nazareth RAG Agent started successfully")

# === WhatsApp Endpoint ===
@app.post("/whatsapp")
async def whatsapp_reply(
    request: Request,
    Body: str = Form(...),
    From: str = Form(...),
    db: Session = Depends(get_db)
):
    # Validate webhook security (IP whitelist + Twilio signature)
    await validate_webhook_request(request)

    whatsapp_number = From.replace("whatsapp:", "")
    logger.info(f"📩 Received WhatsApp message from {whatsapp_number}: {Body}")

    try:
        # Get or create conversation
        conversation = conversation_manager.get_or_create_conversation(whatsapp_number, db)

        # Get conversation history BEFORE saving current message
        # This way, history contains previous context but not the current query
        conversation_history = conversation_manager.get_recent_messages_for_context(
            conversation.id, db, limit=CONVERSATION_HISTORY_LIMIT
        )

        # Save incoming message
        conversation_manager.save_message(
            conversation.id, whatsapp_number, Body,
            is_from_customer=True, sender_type="customer", db=db
        )

        twiml = MessagingResponse()

        # Check if conversation is already with human
        if conversation.status == ConversationStatus.ACTIVE_HUMAN:
            # Forward to human agent (handled by separate system)
            message = "Tu mensaje ha sido enviado a nuestro agente humano. Te responderá en breve."
            logger.info(f"🧑 Message forwarded to human agent for conversation {conversation.id}")

        elif conversation.status == ConversationStatus.PENDING_HUMAN:
            # Waiting for human agent
            message = "Gracias por contactarnos. Un agente humano se comunicará contigo pronto. ⏳"

        else:
            # Check if customer wants to speak to human
            if conversation_manager.should_handover_to_human(Body):
                conversation_manager.request_human_takeover(conversation.id, db)
                message = "Entiendo que querés hablar con una persona. Te estoy conectando con un agente humano. Por favor esperá un momento. 🧑‍💼"
                logger.info(f"🔄 Human handover requested for conversation {conversation.id}")
            else:
                # Process with AI - include conversation history for context
                response = qa_chain.invoke({
                    "query": Body,
                    "instructions": context,
                    "conversation_history": conversation_history
                })
                message = str(response)
                logger.info(f"🤖 RAG response: {message}")
                logger.debug(f"💬 Used {len(conversation_history)} messages from history")

        # Save AI/system response
        conversation_manager.save_message(
            conversation.id, whatsapp_number, message,
            is_from_customer=False, sender_type="ai", db=db
        )

        twiml.message(message)

        # Debug: Log the exact TwiML response being sent
        twiml_content = str(twiml)
        logger.info(f"📤 TwiML Response: {twiml_content}")
        logger.info(f"📏 Response length: {len(twiml_content)} characters")

        return Response(content=twiml_content, media_type="application/xml")

    except Exception as e:
        logger.exception("❌ Error processing WhatsApp message")
        twiml = MessagingResponse()
        error_message = "⚠️ Disculpá, algo salió mal. Por favor intentá de nuevo más tarde."
        twiml.message(error_message)

        # Debug: Log error TwiML response
        twiml_content = str(twiml)
        logger.info(f"📤 Error TwiML Response: {twiml_content}")

        return Response(content=twiml_content, media_type="application/xml")

# === Authentication Endpoints ===

@app.get("/admin/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Serve the login page."""
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/admin/login")
async def login(agent_id: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    """Handle login form submission."""
    agent = authenticate_agent(agent_id, password, db)
    if not agent:
        raise HTTPException(
            status_code=400,
            detail="Incorrect agent ID or password"
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": agent.agent_id}, expires_delta=access_token_expires
    )

    response = RedirectResponse(url="/admin", status_code=302)
    response.set_cookie(
        key="access_token",
        value=access_token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=False  # Set to True in production with HTTPS
    )

    logger.info(f"✅ Agent {agent.agent_id} logged in successfully")
    return response

@app.post("/admin/logout")
async def logout():
    """Handle logout."""
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie(key="access_token")
    return response

# === Human Agent Dashboard UI ===

@app.get("/admin", response_class=HTMLResponse)
async def agent_dashboard(request: Request, current_agent: HumanAgent = Depends(get_current_agent)):
    """Serve the agent dashboard UI."""
    return templates.TemplateResponse("agent_dashboard.html", {
        "request": request,
        "agent": current_agent
    })

# === Human Agent Endpoints ===

@app.get("/admin/conversations/pending")
async def get_pending_conversations(current_agent: HumanAgent = Depends(get_current_agent), db: Session = Depends(get_db)):
    """Get conversations waiting for human takeover."""
    try:
        pending = conversation_manager.get_pending_conversations(db)
        return JSONResponse(content={"pending_conversations": pending})
    except Exception as e:
        logger.exception("❌ Error getting pending conversations")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/admin/conversations/active")
async def get_active_conversations(current_agent: HumanAgent = Depends(get_current_agent), db: Session = Depends(get_db)):
    """Get conversations currently assigned to the logged-in agent."""
    try:
        active = conversation_manager.get_active_conversations(current_agent.agent_id, db)
        return JSONResponse(content={"active_conversations": active})
    except Exception as e:
        logger.exception("❌ Error getting active conversations")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/admin/conversations/{conversation_id}/history")
async def get_conversation_history(conversation_id: int, current_agent: HumanAgent = Depends(get_current_agent), db: Session = Depends(get_db)):
    """Get conversation history for human agent."""
    try:
        history = conversation_manager.get_conversation_history(conversation_id, db)
        return JSONResponse(content={"conversation_id": conversation_id, "history": history})
    except Exception as e:
        logger.exception(f"❌ Error getting history for conversation {conversation_id}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/admin/conversations/{conversation_id}/assign")
async def assign_conversation(conversation_id: int, current_agent: HumanAgent = Depends(get_current_agent), db: Session = Depends(get_db)):
    """Assign conversation to the current human agent."""
    try:
        success = conversation_manager.assign_human_agent(conversation_id, current_agent.agent_id, db)
        if success:
            logger.info(f"✅ Conversation {conversation_id} assigned to agent {current_agent.agent_id}")
            return JSONResponse(content={"success": True, "message": "Conversation assigned successfully"})
        else:
            raise HTTPException(status_code=400, detail="Failed to assign conversation")
    except Exception as e:
        logger.exception(f"❌ Error assigning conversation {conversation_id}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/admin/conversations/{conversation_id}/send")
async def send_human_message(
    conversation_id: int,
    message: str = Form(...),
    current_agent: HumanAgent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """Send message from human agent to customer."""
    try:
        # Get conversation details
        from .models import Conversation
        conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        if conversation.status != ConversationStatus.ACTIVE_HUMAN or conversation.human_agent_id != current_agent.agent_id:
            raise HTTPException(status_code=400, detail="Conversation not assigned to current agent")

        # Save human message to database
        conversation_manager.save_message(
            conversation_id, conversation.whatsapp_number, message,
            is_from_customer=False, sender_type="human", db=db
        )

        # Send message via Twilio
        if twilio_client:
            # Ensure phone number has proper format for Twilio
            phone_number = conversation.whatsapp_number
            if not phone_number.startswith("+"):
                phone_number = f"+{phone_number}"

            try:
                twilio_client.messages.create(
                    body=message,
                    from_=TWILIO_WHATSAPP_FROM,
                    to=f"whatsapp:{phone_number}"
                )
                logger.info(f"📤 Human agent {current_agent.agent_id} sent message to {phone_number}")
            except Exception as twilio_error:
                logger.error(f"❌ Twilio error: {twilio_error}")
                # Continue without failing - message was saved to DB
                logger.info(f"💾 Message saved to database for {phone_number}, but Twilio send failed")

        return JSONResponse(content={"success": True, "message": "Message sent successfully"})

    except Exception as e:
        logger.exception(f"❌ Error sending human message for conversation {conversation_id}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/admin/conversations/{conversation_id}/resolve")
async def resolve_conversation(conversation_id: int, current_agent: HumanAgent = Depends(get_current_agent), db: Session = Depends(get_db)):
    """Mark conversation as resolved."""
    try:
        success = conversation_manager.end_conversation(conversation_id, db)
        if success:
            logger.info(f"✅ Conversation {conversation_id} marked as resolved by agent {current_agent.agent_id}")
            return JSONResponse(content={"success": True, "message": "Conversation resolved"})
        else:
            raise HTTPException(status_code=400, detail="Failed to resolve conversation")
    except Exception as e:
        logger.exception(f"❌ Error resolving conversation {conversation_id}")
        raise HTTPException(status_code=500, detail="Internal server error")

# === Admin Management Endpoints ===

@app.post("/admin/agents/create")
async def create_agent(
    agent_id: str = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    current_agent: HumanAgent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """Create a new human agent (for admin use)."""
    try:
        # Check if agent already exists
        existing_agent = db.query(HumanAgent).filter(HumanAgent.agent_id == agent_id).first()
        if existing_agent:
            raise HTTPException(status_code=400, detail="Agent ID already exists")

        # Create new agent
        password_hash = get_password_hash(password)
        new_agent = HumanAgent(
            agent_id=agent_id,
            name=name,
            email=email,
            password_hash=password_hash
        )

        db.add(new_agent)
        db.commit()
        db.refresh(new_agent)

        logger.info(f"✅ New agent {agent_id} created by {current_agent.agent_id}")
        return JSONResponse(content={"success": True, "message": "Agent created successfully"})

    except Exception as e:
        logger.exception(f"❌ Error creating agent {agent_id}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/setup/create-first-admin")
async def create_first_admin(
    agent_id: str = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    One-time setup endpoint to create the first admin user.
    Only works if no admins exist yet. No authentication required for first admin.
    """
    try:
        # Check if any admin already exists
        existing_admins = db.query(HumanAgent).count()
        if existing_admins > 0:
            raise HTTPException(
                status_code=403,
                detail="Setup already complete. Admin users already exist. Use /admin/agents/create instead."
            )

        # Create first admin
        password_hash = get_password_hash(password)
        first_admin = HumanAgent(
            agent_id=agent_id,
            name=name,
            email=email,
            password_hash=password_hash
        )

        db.add(first_admin)
        db.commit()
        db.refresh(first_admin)

        logger.info(f"✅ First admin {agent_id} created via setup endpoint")
        return JSONResponse(content={
            "success": True,
            "message": f"First admin '{agent_id}' created successfully! You can now login at /admin"
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"❌ Error creating first admin")
        raise HTTPException(status_code=500, detail="Internal server error")
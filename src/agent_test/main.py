from fastapi import FastAPI, Form, Depends, HTTPException, Request, Response as FastAPIResponse, status as http_status, BackgroundTasks
from fastapi.responses import Response, JSONResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from langchain_core.runnables import Runnable
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from sqlalchemy.orm import Session
from dotenv import load_dotenv
import logging
from logging.handlers import RotatingFileHandler
import os
from typing import List, Dict, Optional
from datetime import timedelta, datetime
import re
import csv
import io
import json
import httpx
from urllib.parse import urlparse

from .rag_chain import build_rag_chain
from .database import get_db, create_tables
from .conversation_manager import ConversationManager
from .models import ConversationStatus, HumanAgent, AgentRole, Conversation, Message
from .auth import authenticate_agent, create_access_token, get_current_agent, get_current_admin, get_password_hash, ACCESS_TOKEN_EXPIRE_MINUTES
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

# === Heavy Query Detection ===
def is_heavy_query(query: str) -> bool:
    """
    Detect queries that require listing multiple items or complex responses.
    These queries typically take 15+ seconds and should be processed asynchronously.
    """
    query_lower = query.lower().strip()

    # Patterns that indicate "list all" type queries
    heavy_patterns = [
        r'\b(todas?|todos?)\s+(las?|los?)\s+(promo|convenio|beneficio|servicio)',  # "todas las promos"
        r'\b(qu[eé]|cuales?|cuantas?)\s+(promo|convenio|beneficio|servicio)',  # "que promos hay"
        r'\b(hay|tienen?|ofrecen?)\s+(alguna?s?)?\s*(promo|convenio|beneficio)',  # "hay promos"
        r'\b(alg[uú]n)\s+(convenio|promo|beneficio)',  # "algún convenio"
        r'\b(lista|listar|mostrar|decir)\s+(las?|los?|todas?|todos?)',  # "lista todos"
        r'\b(que|cuales)\s+(son|hay)\s+(las?|los?)',  # "que son los convenios"
    ]

    for pattern in heavy_patterns:
        if re.search(pattern, query_lower):
            logger.info(f"🔍 Heavy query detected: '{query}' (pattern: {pattern})")
            return True

    return False

# === Background Task for Heavy Queries ===
def process_heavy_query_background(
    conversation_id: int,
    whatsapp_number: str,
    query: str,
    conversation_history: list,
):
    """
    Process heavy query in background and send response via Twilio API.
    """
    from .database import SessionLocal

    db = SessionLocal()
    try:
        logger.info(f"⚙️ Processing heavy query in background for {whatsapp_number}: {query}")

        # Process with RAG chain
        response = qa_chain.invoke({
            "query": query,
            "instructions": context,
            "conversation_history": conversation_history
        })
        message = str(response)

        logger.info(f"✅ Heavy query processed: {len(message)} characters")

        # Save AI response to database
        conversation_manager.save_message(
            conversation_id, whatsapp_number, message,
            is_from_customer=False, sender_type="ai", db=db
        )

        # Send message via Twilio API
        if twilio_client:
            phone_number = whatsapp_number if whatsapp_number.startswith("+") else f"+{whatsapp_number}"
            try:
                twilio_message = twilio_client.messages.create(
                    body=message,
                    from_=TWILIO_WHATSAPP_FROM,
                    to=f"whatsapp:{phone_number}"
                )
                logger.info(f"📤 Heavy query response sent via Twilio API. SID: {twilio_message.sid}")
            except Exception as twilio_error:
                logger.error(f"❌ Twilio API error: {twilio_error}")
        else:
            logger.warning(f"⚠️ Twilio client not configured - response saved to DB only")

    except Exception as e:
        logger.exception(f"❌ Error processing heavy query in background")
        # Send error message to user
        if twilio_client:
            try:
                phone_number = whatsapp_number if whatsapp_number.startswith("+") else f"+{whatsapp_number}"
                twilio_client.messages.create(
                    body="⚠️ Disculpá, hubo un problema procesando tu consulta. Por favor intentá de nuevo.",
                    from_=TWILIO_WHATSAPP_FROM,
                    to=f"whatsapp:{phone_number}"
                )
            except:
                pass
    finally:
        db.close()

# === Exception handlers ===
@app.exception_handler(FastAPIHTTPException)
async def custom_http_exception_handler(request: Request, exc: FastAPIHTTPException):
    """Handle HTTP exceptions with custom redirects for auth failures."""
    # Redirect to login for 401 errors on panel pages
    if exc.status_code == 401 and request.url.path.startswith("/panel"):
        # Don't redirect if already on login page
        if request.url.path != "/panel/login":
            return RedirectResponse(url="/panel/login", status_code=302)

    # For API endpoints, return JSON error
    if request.url.path.startswith("/panel/") and not request.url.path.startswith("/panel/login"):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail}
        )

    # Default behavior for other errors
    raise exc

# === Create database tables on startup ===
@app.on_event("startup")
async def startup_event():
    create_tables()
    logger.info("🚀 Cooperativa Nazareth RAG Agent started successfully")

# === WhatsApp Endpoint ===
@app.post("/whatsapp")
async def whatsapp_reply(
    request: Request,
    background_tasks: BackgroundTasks,
    Body: Optional[str] = Form(""),
    From: str = Form(...),
    NumMedia: Optional[int] = Form(0),
    db: Session = Depends(get_db)
):
    # Validate webhook security (IP whitelist + Twilio signature)
    await validate_webhook_request(request)

    whatsapp_number = From.replace("whatsapp:", "")
    logger.info(f"📩 Received WhatsApp message from {whatsapp_number}: {Body}")
    logger.info(f"📎 NumMedia parameter received: {NumMedia} (type: {type(NumMedia)})")

    # Extract media information if present
    media_urls = []
    media_content_types = []

    if NumMedia and NumMedia > 0:
        logger.info(f"📎 Message contains {NumMedia} media file(s)")
        form_data = await request.form()

        for i in range(NumMedia):
            media_url = form_data.get(f"MediaUrl{i}")
            media_content_type = form_data.get(f"MediaContentType{i}")

            if media_url:
                media_urls.append(str(media_url))
                media_content_types.append(str(media_content_type) if media_content_type else "unknown")
                logger.info(f"📎 Media {i}: {media_content_type} - {media_url}")

    # Convert to JSON strings for database storage
    media_urls_json = json.dumps(media_urls) if media_urls else None
    media_content_types_json = json.dumps(media_content_types) if media_content_types else None

    try:
        # Get or create conversation
        conversation = conversation_manager.get_or_create_conversation(whatsapp_number, db)

        # Get conversation history BEFORE saving current message
        # This way, history contains previous context but not the current query
        conversation_history = conversation_manager.get_recent_messages_for_context(
            conversation.id, db, limit=CONVERSATION_HISTORY_LIMIT
        )

        # Save incoming message with media info
        conversation_manager.save_message(
            conversation.id, whatsapp_number, Body,
            is_from_customer=True, sender_type="customer", db=db,
            num_media=NumMedia or 0,
            media_urls=media_urls_json,
            media_content_types=media_content_types_json
        )

        twiml = MessagingResponse()

        # Check if message contains media - auto-escalate to human
        logger.info(f"🔍 Checking media: NumMedia={NumMedia}, has media_urls={len(media_urls) > 0 if media_urls else False}")
        if NumMedia and NumMedia > 0:
            logger.info(f"✅ Media detected! Escalating to human agent")
            # Determine media type for user-friendly message
            media_type = "archivo(s)"
            if media_urls and media_content_types:
                first_type = media_content_types[0].lower()
                if "image" in first_type:
                    media_type = "imagen(es)" if NumMedia == 1 else "imágenes"
                elif "video" in first_type:
                    media_type = "video(s)"
                elif "audio" in first_type:
                    media_type = "audio(s)"
                elif "pdf" in first_type or "document" in first_type:
                    media_type = "documento(s)"

            conversation_manager.request_human_takeover(conversation.id, db)
            message = f"Recibí tu {media_type}. Un agente humano lo revisará y te responderá pronto. Por favor esperá un momento. 🧑‍💼"
            logger.info(f"📎 Media detected - human handover requested for conversation {conversation.id}")

        # Check if conversation is already with human
        elif conversation.status == ConversationStatus.ACTIVE_HUMAN:
            # Forward to human agent (handled by separate system)
            # No automatic response - human agent will respond directly
            logger.info(f"🧑 Message forwarded to human agent for conversation {conversation.id}")
            # Return empty TwiML response (no automatic message)
            return Response(content=str(twiml), media_type="application/xml")

        elif conversation.status == ConversationStatus.PENDING_HUMAN:
            # Waiting for human agent
            message = "Gracias por contactarnos. Un agente humano se comunicará contigo pronto. ⏳"

        else:
            # Check if customer wants to speak to human
            if conversation_manager.should_handover_to_human(Body):
                conversation_manager.request_human_takeover(conversation.id, db)
                message = "Entiendo que querés hablar con una persona. Te estoy conectando con un agente humano. Por favor esperá un momento. 🧑‍💼"
                logger.info(f"🔄 Human handover requested for conversation {conversation.id}")
            # Check if this is a heavy query that needs async processing
            elif is_heavy_query(Body):
                # Schedule background processing
                background_tasks.add_task(
                    process_heavy_query_background,
                    conversation.id,
                    whatsapp_number,
                    Body,
                    conversation_history
                )
                # Return immediate acknowledgment
                message = "Estoy buscando toda la información para vos. Te respondo en un momento... ⏳"
                logger.info(f"⚡ Heavy query scheduled for background processing: {Body}")
            else:
                # Normal query - process synchronously for fast response
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

@app.get("/panel/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Serve the login page."""
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/panel/login")
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

    response = RedirectResponse(url="/panel", status_code=302)
    response.set_cookie(
        key="access_token",
        value=access_token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=False  # Set to True in production with HTTPS
    )

    logger.info(f"✅ Agent {agent.agent_id} logged in successfully")
    return response

@app.post("/panel/logout")
async def logout():
    """Handle logout."""
    response = RedirectResponse(url="/panel/login", status_code=302)
    response.delete_cookie(key="access_token")
    return response

# === Human Agent Dashboard UI ===

@app.get("/panel", response_class=HTMLResponse)
async def agent_dashboard(request: Request, current_agent: HumanAgent = Depends(get_current_agent)):
    """Serve the agent dashboard UI."""
    return templates.TemplateResponse("agent_dashboard.html", {
        "request": request,
        "agent": current_agent
    })

# === Human Agent Endpoints ===

@app.get("/panel/conversations/pending")
async def get_pending_conversations(current_agent: HumanAgent = Depends(get_current_agent), db: Session = Depends(get_db)):
    """Get conversations waiting for human takeover."""
    try:
        pending = conversation_manager.get_pending_conversations(db)
        return JSONResponse(content={"pending_conversations": pending})
    except Exception as e:
        logger.exception("❌ Error getting pending conversations")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/panel/conversations/active")
async def get_active_conversations(current_agent: HumanAgent = Depends(get_current_agent), db: Session = Depends(get_db)):
    """Get conversations currently assigned to the logged-in agent."""
    try:
        active = conversation_manager.get_active_conversations(current_agent.agent_id, db)
        return JSONResponse(content={"active_conversations": active})
    except Exception as e:
        logger.exception("❌ Error getting active conversations")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/panel/conversations/{conversation_id}/history")
async def get_conversation_history(conversation_id: int, current_agent: HumanAgent = Depends(get_current_agent), db: Session = Depends(get_db)):
    """Get conversation history for human agent."""
    try:
        history = conversation_manager.get_conversation_history(conversation_id, db)
        return JSONResponse(content={"conversation_id": conversation_id, "history": history})
    except Exception as e:
        logger.exception(f"❌ Error getting history for conversation {conversation_id}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/panel/media/proxy")
async def proxy_media(url: str, current_agent: HumanAgent = Depends(get_current_agent)):
    """Proxy media from Twilio with authentication."""
    try:
        # Validate URL is from Twilio
        parsed_url = urlparse(url)
        if not parsed_url.hostname or 'twilio.com' not in parsed_url.hostname:
            raise HTTPException(status_code=400, detail="Invalid media URL")

        # Fetch media from Twilio with authentication
        twilio_account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        twilio_auth_token = os.getenv("TWILIO_AUTH_TOKEN")

        if not twilio_account_sid or not twilio_auth_token:
            raise HTTPException(status_code=500, detail="Twilio credentials not configured")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url,
                auth=(twilio_account_sid, twilio_auth_token),
                follow_redirects=True
            )

            if response.status_code != 200:
                logger.error(f"Failed to fetch media from Twilio: {response.status_code}")
                raise HTTPException(status_code=response.status_code, detail="Failed to fetch media")

            # Return media with proper content type
            return StreamingResponse(
                iter([response.content]),
                media_type=response.headers.get("content-type", "application/octet-stream"),
                headers={
                    "Cache-Control": "public, max-age=86400",  # Cache for 24 hours
                }
            )

    except httpx.RequestError as e:
        logger.exception(f"❌ Error fetching media from Twilio: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch media from Twilio")
    except Exception as e:
        logger.exception(f"❌ Error proxying media: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/panel/conversations/{conversation_id}/assign")
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

@app.post("/panel/conversations/{conversation_id}/send")
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
                twilio_message = twilio_client.messages.create(
                    body=message,
                    from_=TWILIO_WHATSAPP_FROM,
                    to=f"whatsapp:{phone_number}"
                )
                logger.info(f"📤 Human agent {current_agent.agent_id} sent message to {phone_number}")
                logger.info(f"📱 Twilio Message SID: {twilio_message.sid}, Status: {twilio_message.status}")
            except Exception as twilio_error:
                logger.error(f"❌ Twilio error: {twilio_error}")
                # Continue without failing - message was saved to DB
                logger.info(f"💾 Message saved to database for {phone_number}, but Twilio send failed")
        else:
            logger.warning(f"⚠️ Twilio client not configured! Message saved to DB but not sent to WhatsApp.")
            logger.warning(f"⚠️ Check TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_WHATSAPP_FROM environment variables")

        return JSONResponse(content={"success": True, "message": "Message sent successfully"})

    except Exception as e:
        logger.exception(f"❌ Error sending human message for conversation {conversation_id}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/panel/conversations/{conversation_id}/resolve")
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

@app.get("/panel/agents/list")
async def list_agents(
    current_admin: HumanAgent = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """List all human agents (admin only)."""
    try:
        agents = db.query(HumanAgent).order_by(HumanAgent.created_at.desc()).all()
        agents_data = [
            {
                "id": agent.id,
                "agent_id": agent.agent_id,
                "name": agent.name,
                "email": agent.email,
                "role": agent.role.value,
                "is_active": agent.is_active,
                "max_concurrent_conversations": agent.max_concurrent_conversations,
                "created_at": str(agent.created_at)
            }
            for agent in agents
        ]
        return JSONResponse(content={"agents": agents_data})
    except Exception as e:
        logger.exception("❌ Error listing agents")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/panel/agents/create")
async def create_agent(
    agent_id: str = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form("agent"),
    max_concurrent_conversations: int = Form(5),
    current_admin: HumanAgent = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Create a new human agent (admin only)."""
    try:
        # Check if agent already exists
        existing_agent = db.query(HumanAgent).filter(HumanAgent.agent_id == agent_id).first()
        if existing_agent:
            raise HTTPException(status_code=400, detail="Agent ID already exists")

        # Validate role
        try:
            agent_role = AgentRole(role)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid role. Must be 'admin' or 'agent'")

        # Create new agent
        password_hash = get_password_hash(password)
        new_agent = HumanAgent(
            agent_id=agent_id,
            name=name,
            email=email,
            password_hash=password_hash,
            role=agent_role,
            max_concurrent_conversations=max_concurrent_conversations
        )

        db.add(new_agent)
        db.commit()
        db.refresh(new_agent)

        logger.info(f"✅ New agent {agent_id} created by {current_admin.agent_id}")
        return JSONResponse(content={"success": True, "message": "Agent created successfully"})

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"❌ Error creating agent {agent_id}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/panel/agents/{agent_id}/toggle-active")
async def toggle_agent_active(
    agent_id: str,
    current_admin: HumanAgent = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Toggle agent active status (admin only)."""
    try:
        agent = db.query(HumanAgent).filter(HumanAgent.agent_id == agent_id).first()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Prevent deactivating yourself
        if agent.agent_id == current_admin.agent_id:
            raise HTTPException(status_code=400, detail="Cannot deactivate your own account")

        agent.is_active = not agent.is_active
        db.commit()

        logger.info(f"✅ Agent {agent_id} {'activated' if agent.is_active else 'deactivated'} by {current_admin.agent_id}")
        return JSONResponse(content={
            "success": True,
            "message": f"Agent {'activated' if agent.is_active else 'deactivated'}",
            "is_active": agent.is_active
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"❌ Error toggling agent {agent_id}")
        raise HTTPException(status_code=500, detail="Internal server error")

# === Reports Endpoints (Admin Only) ===

@app.get("/panel/reports", response_class=HTMLResponse)
async def reports_page(
    request: Request,
    current_admin: HumanAgent = Depends(get_current_admin)
):
    """Serve the reports page (admin only)."""
    return templates.TemplateResponse("reports.html", {
        "request": request,
        "agent": current_admin
    })

@app.get("/panel/api/reports/stats")
async def get_reports_stats(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    current_admin: HumanAgent = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get summary statistics for reports (admin only)."""
    try:
        # Build base query
        query = db.query(Conversation)

        # Apply date filters if provided
        if date_from:
            date_from_obj = datetime.fromisoformat(date_from)
            query = query.filter(Conversation.created_at >= date_from_obj)
        if date_to:
            date_to_obj = datetime.fromisoformat(date_to)
            query = query.filter(Conversation.created_at <= date_to_obj)

        # Calculate statistics
        total_conversations = query.count()
        ai_only = query.filter(Conversation.status == ConversationStatus.ACTIVE_AI).count()
        pending_human = query.filter(Conversation.status == ConversationStatus.PENDING_HUMAN).count()
        active_human = query.filter(Conversation.status == ConversationStatus.ACTIVE_HUMAN).count()
        resolved = query.filter(Conversation.status == ConversationStatus.RESOLVED).count()

        return JSONResponse(content={
            "total_conversations": total_conversations,
            "ai_only": ai_only,
            "pending_human": pending_human,
            "active_human": active_human,
            "resolved": resolved
        })
    except Exception as e:
        logger.exception("❌ Error getting stats")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/panel/api/reports/conversations")
async def get_all_conversations(
    page: int = 1,
    per_page: int = 10,
    status: Optional[str] = None,
    phone: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    agent_id: Optional[str] = None,
    current_admin: HumanAgent = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get paginated list of all conversations with filters (admin only)."""
    try:
        # Build base query
        query = db.query(Conversation)

        # Apply filters
        if status:
            try:
                status_enum = ConversationStatus(status)
                query = query.filter(Conversation.status == status_enum)
            except ValueError:
                pass  # Invalid status, ignore filter

        if phone:
            query = query.filter(Conversation.whatsapp_number.like(f"%{phone}%"))

        if date_from:
            date_from_obj = datetime.fromisoformat(date_from)
            query = query.filter(Conversation.created_at >= date_from_obj)

        if date_to:
            date_to_obj = datetime.fromisoformat(date_to)
            query = query.filter(Conversation.created_at <= date_to_obj)

        if agent_id:
            query = query.filter(Conversation.human_agent_id == agent_id)

        # Get total count before pagination
        total_count = query.count()

        # Apply sorting (most recent first)
        query = query.order_by(Conversation.updated_at.desc())

        # Apply pagination
        offset = (page - 1) * per_page
        conversations = query.offset(offset).limit(per_page).all()

        # Calculate total pages
        total_pages = (total_count + per_page - 1) // per_page

        # Format response
        conversations_data = []
        for conv in conversations:
            # Get message count
            message_count = db.query(Message).filter(Message.conversation_id == conv.id).count()

            # Get last message
            last_message = db.query(Message).filter(
                Message.conversation_id == conv.id
            ).order_by(Message.timestamp.desc()).first()

            # Get agent name if applicable
            agent_name = "AI Only"
            if conv.human_agent_id:
                agent = db.query(HumanAgent).filter(HumanAgent.agent_id == conv.human_agent_id).first()
                if agent:
                    agent_name = agent.name

            conversations_data.append({
                "id": conv.id,
                "whatsapp_number": conv.whatsapp_number,
                "status": conv.status.value,
                "created_at": conv.created_at.isoformat(),
                "updated_at": conv.updated_at.isoformat(),
                "message_count": message_count,
                "agent_name": agent_name,
                "last_message": last_message.message_text[:100] if last_message else "No messages",
                "last_message_sender": last_message.sender_type if last_message else None
            })

        return JSONResponse(content={
            "conversations": conversations_data,
            "total_count": total_count,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages
        })
    except Exception as e:
        logger.exception("❌ Error getting conversations")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/panel/api/reports/conversations/{conversation_id}")
async def get_conversation_details(
    conversation_id: int,
    current_admin: HumanAgent = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get detailed information about a specific conversation (admin only)."""
    try:
        # Get conversation
        conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Get all messages
        messages = db.query(Message).filter(
            Message.conversation_id == conversation_id
        ).order_by(Message.timestamp.asc()).all()

        # Get agent info if applicable
        agent_name = "AI Only"
        if conversation.human_agent_id:
            agent = db.query(HumanAgent).filter(HumanAgent.agent_id == conversation.human_agent_id).first()
            if agent:
                agent_name = agent.name

        # Count messages by type
        customer_messages = sum(1 for m in messages if m.sender_type == "customer")
        ai_messages = sum(1 for m in messages if m.sender_type == "ai")
        human_messages = sum(1 for m in messages if m.sender_type == "human")

        # Calculate duration
        duration = None
        if messages:
            first_msg = messages[0]
            last_msg = messages[-1]
            duration_delta = last_msg.timestamp - first_msg.timestamp
            duration = str(duration_delta)

        # Format messages
        messages_data = [
            {
                "id": msg.id,
                "message": msg.message_text,
                "sender_type": msg.sender_type,
                "timestamp": msg.timestamp.isoformat(),
                "is_from_customer": msg.is_from_customer
            }
            for msg in messages
        ]

        return JSONResponse(content={
            "conversation": {
                "id": conversation.id,
                "whatsapp_number": conversation.whatsapp_number,
                "status": conversation.status.value,
                "created_at": conversation.created_at.isoformat(),
                "updated_at": conversation.updated_at.isoformat(),
                "agent_name": agent_name,
                "duration": duration,
                "total_messages": len(messages),
                "customer_messages": customer_messages,
                "ai_messages": ai_messages,
                "human_messages": human_messages
            },
            "messages": messages_data
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"❌ Error getting conversation {conversation_id} details")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/panel/api/reports/export")
async def export_conversations(
    status: Optional[str] = None,
    phone: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    agent_id: Optional[str] = None,
    current_admin: HumanAgent = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Export conversations to CSV (admin only)."""
    try:
        # Build query with same filters as list endpoint
        query = db.query(Conversation)

        if status:
            try:
                status_enum = ConversationStatus(status)
                query = query.filter(Conversation.status == status_enum)
            except ValueError:
                pass

        if phone:
            query = query.filter(Conversation.whatsapp_number.like(f"%{phone}%"))

        if date_from:
            date_from_obj = datetime.fromisoformat(date_from)
            query = query.filter(Conversation.created_at >= date_from_obj)

        if date_to:
            date_to_obj = datetime.fromisoformat(date_to)
            query = query.filter(Conversation.created_at <= date_to_obj)

        if agent_id:
            query = query.filter(Conversation.human_agent_id == agent_id)

        conversations = query.order_by(Conversation.created_at.desc()).all()

        # Create CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow([
            "Conversation ID",
            "WhatsApp Number",
            "Status",
            "Agent",
            "Created At",
            "Updated At",
            "Total Messages",
            "Customer Messages",
            "AI Messages",
            "Human Messages",
            "Last Message"
        ])

        # Write data rows
        for conv in conversations:
            # Get message counts
            messages = db.query(Message).filter(Message.conversation_id == conv.id).all()
            customer_msgs = sum(1 for m in messages if m.sender_type == "customer")
            ai_msgs = sum(1 for m in messages if m.sender_type == "ai")
            human_msgs = sum(1 for m in messages if m.sender_type == "human")

            # Get last message
            last_msg = messages[-1].message_text[:100] if messages else "No messages"

            # Get agent name
            agent_name = "AI Only"
            if conv.human_agent_id:
                agent = db.query(HumanAgent).filter(HumanAgent.agent_id == conv.human_agent_id).first()
                if agent:
                    agent_name = agent.name

            writer.writerow([
                conv.id,
                conv.whatsapp_number,
                conv.status.value,
                agent_name,
                conv.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                conv.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
                len(messages),
                customer_msgs,
                ai_msgs,
                human_msgs,
                last_msg
            ])

        # Prepare response
        output.seek(0)
        filename = f"conversations_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
    except Exception as e:
        logger.exception("❌ Error exporting conversations")
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
            password_hash=password_hash,
            role=AgentRole.ADMIN
        )

        db.add(first_admin)
        db.commit()
        db.refresh(first_admin)

        logger.info(f"✅ First admin {agent_id} created via setup endpoint")
        return JSONResponse(content={
            "success": True,
            "message": f"First admin '{agent_id}' created successfully! You can now login at /panel"
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"❌ Error creating first admin")
        raise HTTPException(status_code=500, detail="Internal server error")
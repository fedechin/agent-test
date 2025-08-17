from fastapi import FastAPI, Form, Depends
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.runnables import Runnable
from twilio.twiml.messaging_response import MessagingResponse
from dotenv import load_dotenv
import logging
from logging.handlers import RotatingFileHandler
import os

from .rag_chain import build_rag_chain

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
app = FastAPI()

# === Optional: CORS for dev/frontend integration ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TIP: Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Build RAG chain once and store globally ===
qa_chain, context = build_rag_chain()

# === WhatsApp Endpoint ===
@app.post("/whatsapp")
async def whatsapp_reply(Body: str = Form(...)):
    logger.info(f"📩 Received WhatsApp message: {Body}")
    try:
        response = qa_chain.invoke({
            "query": Body,
            "instructions": context
        })
        logger.info(f"🤖 RAG response: {response}")

        message = str(response)

        twiml = MessagingResponse()
        twiml.message(message)
        return Response(content=str(twiml), media_type="application/xml")

    except Exception as e:
        print("Exception:", e)  # Debug print
        logger.exception("❌ Error processing WhatsApp message")
        twiml = MessagingResponse()
        twiml.message("⚠️ Sorry, something went wrong. Please try again later.")
        return Response(content=str(twiml), media_type="application/xml")
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from agent_test.rag_chain import build_rag_chain
from agent_test.local_fallback import local_qa
from openai._exceptions import RateLimitError, OpenAIError

import os
from dotenv import load_dotenv
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse

twilio_client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
twilio_from = os.getenv("TWILIO_WHATSAPP_FROM")

load_dotenv()

templates = Jinja2Templates(directory="templates")

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

qa_chain = None  # Lazy-loaded on first request
cache = {}
chat_history = []


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "chat": chat_history})


@app.post("/ask", response_class=HTMLResponse)
def ask(request: Request, query: str = Form(...)):
    global qa_chain

    if qa_chain is None:
        try:
            qa_chain = build_rag_chain()
        except RateLimitError:
            qa_chain = None
            raise HTTPException(status_code=503, detail="OpenAI quota exceeded during initialization. Try again later.")
        except OpenAIError as e:
            qa_chain = None
            raise HTTPException(status_code=500, detail=f"OpenAI error during initialization: {str(e)}")

    if query in cache:
        answer = cache[query]
    else:
        try:
            answer = qa_chain.run(query)
        except RateLimitError:
            with open("data/docs.txt", "r") as f:
                context = f.read()
            answer = local_qa(query, context)
            answer += " (fallback mode: quota limit)"
        except OpenAIError as e:
            raise HTTPException(status_code=500, detail=f"OpenAI error: {str(e)}")

        cache[query] = answer

    chat_history.append({"role": "user", "text": query})
    chat_history.append({"role": "bot", "text": answer})
    return templates.TemplateResponse("index.html", {"request": request, "chat": chat_history})

@app.post("/whatsapp")
async def whatsapp_reply(request: Request, Body: str = Form(...)):
    global qa_chain
    if qa_chain is None:
        qa_chain = build_rag_chain()

    rag_response = qa_chain.invoke({"query": Body})

    if isinstance(rag_response, dict) and "result" in rag_response:
        answer = rag_response["result"]
    else:
        answer = str(rag_response)

    # Construct Twilio reply
    twiml = MessagingResponse()
    twiml.message(answer)

    return Response(content=str(twiml), media_type="application/xml")

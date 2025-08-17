# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

**Poetry Commands:**
- `poetry install` - Install dependencies
- `poetry run uvicorn src.agent_test.main:app --host 0.0.0.0 --port 8000 --reload` - Run development server with hot reload
- `poetry run pytest` - Run tests

**Docker Commands:**
- `docker-compose up --build` - Build and run the entire application stack
- `docker-compose down` - Stop the application

## Architecture Overview

This is a production-ready RAG (Retrieval-Augmented Generation) agent built for WhatsApp integration with the following components:

### Core Architecture
- **FastAPI Backend** (`src/agent_test/main.py`): Web server with WhatsApp webhook endpoint
- **RAG Chain** (`src/agent_test/rag_chain.py`): LangChain-based retrieval system using FAISS vector store and OpenAI
- **Local Fallback** (`src/agent_test/local_fallback.py`): Transformers-based backup Q&A system

### Key Components
1. **Vector Store**: FAISS index stored in `data/faiss_index/` for document embeddings
2. **Document Loading**: Processes all `.txt` files in `data/` directory with 500-character chunks
3. **WhatsApp Integration**: Twilio webhook at `/whatsapp` endpoint returning TwiML responses
4. **Context Instructions**: Agent behavior defined in `context/context.txt` for Cooperativa Multiactiva Nazareth

### Data Flow
1. WhatsApp message received at `/whatsapp` endpoint
2. RAG chain retrieves relevant documents from FAISS vector store
3. OpenAI GPT-4 generates response using retrieved context and system instructions
4. Response returned as TwiML for WhatsApp delivery

## Environment Setup

Required environment variables:
- `OPENAI_API_KEY` - OpenAI API key for embeddings and chat completion
- `DOCS_FOLDER` - Document directory (defaults to "data")
- `CONTEXT_FILE` - Context instructions file (defaults to "context/context.txt")

## Domain-Specific Context

This agent serves members of Cooperativa Multiactiva Nazareth with:
- Spanish language responses using formal "usted" address
- Financial services information (savings, credit, cards)
- Cooperative philosophy and motivation
- Strict adherence to knowledge base without speculation
- Source attribution for all responses
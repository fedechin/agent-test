# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

**Poetry Commands:**
- `poetry install` - Install dependencies
- `poetry run uvicorn src.agent_test.main:app --host 0.0.0.0 --port 8000 --reload` - Run development server with hot reload
- `poetry run pytest` - Run tests
- `python3 create_admin.py` - Create first admin user (run after setting up database)
- `python3 migrate_add_role.py` - Migrate existing database to add role column (run once if upgrading)
- `python3 test_system.py` - Run system integration tests

**Docker Commands:**
- `docker-compose up --build` - Build and run the entire application stack (includes PostgreSQL database)
- `docker-compose down` - Stop the application

**Deployment:**
- Automatic migrations run on startup via `start.sh` script
- Railway deployment configured in `railway.json`
- Migrations are idempotent and safe to run multiple times

## Architecture Overview

This is a production-ready RAG (Retrieval-Augmented Generation) agent built for WhatsApp integration with the following components:

### Core Architecture
- **FastAPI Backend** (`src/agent_test/main.py`): Web server with WhatsApp webhook endpoint and admin dashboard
- **RAG Chain** (`src/agent_test/rag_chain.py`): LangChain-based retrieval system using FAISS vector store and OpenAI
- **Database Layer** (`src/agent_test/database.py`, `src/agent_test/models.py`): SQLAlchemy-based conversation history storage
- **Conversation Manager** (`src/agent_test/conversation_manager.py`): Handles human handover logic and conversation state
- **Authentication** (`src/agent_test/auth.py`): JWT-based authentication for human agents
- **Admin Interface** (`templates/`): Secure web dashboard for human agents

### Key Components
1. **Vector Store**: FAISS index stored in `data/faiss_index/` for document embeddings
2. **Document Loading**: Processes all `.txt` files in `data/` directory with 500-character chunks
3. **WhatsApp Integration**: Twilio webhook at `/whatsapp` endpoint returning TwiML responses
4. **Context Instructions**: Agent behavior defined in `context/context.txt` for Cooperativa Multiactiva Nazareth
5. **Conversation History**: PostgreSQL database storing all conversations and messages
6. **Human Handover**: Automatic detection of requests for human assistance
7. **Agent Panel**: Secure interface at `/panel` for human agents to manage conversations
8. **Role-Based Access Control**: Admin and agent roles with restricted access to agent management features

### Data Flow
1. WhatsApp message received at `/whatsapp` endpoint
2. Conversation record created/retrieved from database
3. Message saved to conversation history
4. System checks if human handover is requested
5. If AI handling: RAG chain retrieves relevant documents and generates response
6. If human handling: Message queued for human agent in admin dashboard
7. Response returned as TwiML for WhatsApp delivery and saved to database

## Environment Setup

Required environment variables:
- `OPENAI_API_KEY` - OpenAI API key for embeddings and chat completion
- `TWILIO_ACCOUNT_SID` - Twilio Account SID for WhatsApp integration
- `TWILIO_AUTH_TOKEN` - Twilio Auth Token
- `TWILIO_WHATSAPP_FROM` - Twilio WhatsApp phone number (format: whatsapp:+1234567890)
- `DATABASE_URL` - Database connection string (defaults to SQLite for development)
- `SECRET_KEY` - JWT secret key for authentication (generate a strong random string)
- `DOCS_FOLDER` - Document directory (defaults to "data")
- `CONTEXT_FILE` - Context instructions file (defaults to "context/context.txt")

Copy `.env.example` to `.env` and configure your values.

## Admin and Agent Management

### Roles
- **Admin**: Full access to create/manage agents, view all conversations, and handle customer inquiries
- **Agent**: Can only handle customer conversations (no access to agent management)

### Creating Agents
1. **First Admin**: Use `python3 create_admin.py` to create the first admin user
2. **Additional Agents**: Admins can create more agents through the agent panel at `/panel`
   - Click "Ver Agentes" to view all agents
   - Click "Crear Nuevo Agente" to add new agents
   - Set role as "Admin" or "Agente"
   - Configure max concurrent conversations (default: 5)

### Agent Management Features (Admin Only)
- View all agents with their roles and status
- Create new agents with admin or agent roles
- Activate/deactivate agents
- Configure maximum concurrent conversations per agent

### Database Migration
If upgrading from a version without roles, run `python3 migrate_add_role.py` to add the role column to existing agents. The first agent will be automatically promoted to admin.

## Domain-Specific Context

This agent serves members of Cooperativa Multiactiva Nazareth with:
- Spanish language responses using formal "usted" address
- Financial services information (savings, credit, cards)
- Cooperative philosophy and motivation
- Strict adherence to knowledge base without speculation
- Source attribution for all responses
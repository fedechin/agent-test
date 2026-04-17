#!/bin/bash
set -e

echo "🚀 Starting Cooperativa Nazareth RAG Agent..."

# Run database migrations with Alembic
echo "📊 Running database migrations with Alembic..."
alembic upgrade head

# Clear FAISS index to force rebuild from current data files
echo "🔄 Clearing FAISS index cache..."
rm -rf data/faiss_index

# Start the FastAPI application
echo "✅ Starting application..."
exec uvicorn src.agent_test.main:app --host 0.0.0.0 --port ${PORT:-8000}

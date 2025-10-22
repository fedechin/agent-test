#!/bin/bash
set -e

echo "🚀 Starting Cooperativa Nazareth RAG Agent..."

# Run database migrations with Alembic
echo "📊 Running database migrations with Alembic..."

# Check if alembic_version table exists and has any revisions
if alembic current 2>&1 | grep -q "Can't locate revision"; then
    echo "⚠️  Alembic not initialized. Checking database state..."

    # Check if role column already exists (from old migration scripts)
    python3 -c "
import os
import sys
sys.path.insert(0, 'src')
from sqlalchemy import inspect
from agent_test.database import engine

inspector = inspect(engine)
columns = [col['name'] for col in inspector.get_columns('human_agents')]

if 'role' in columns:
    print('Column exists')
    sys.exit(0)
else:
    print('Column does not exist')
    sys.exit(1)
" && {
        echo "✅ Role column already exists from previous migration. Marking as applied..."
        alembic stamp head
    } || {
        echo "📝 Running initial migration..."
        alembic upgrade head
    }
else
    # Normal migration path
    alembic upgrade head
fi

# Start the FastAPI application
echo "✅ Starting application..."
exec uvicorn src.agent_test.main:app --host 0.0.0.0 --port ${PORT:-8000}

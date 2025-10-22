#!/bin/bash
set -e

echo "🚀 Starting Cooperativa Nazareth RAG Agent..."

# Run database migrations
echo "📊 Running database migrations..."
python3 migrate_add_role.py || echo "⚠️  Migration already applied or not needed"

# Fix enum values if needed (for existing deployments with lowercase values)
echo "🔧 Checking enum values..."
python3 fix_role_enum.py || echo "⚠️  Enum fix not needed or already applied"

# Start the FastAPI application
echo "✅ Starting application..."
exec uvicorn src.agent_test.main:app --host 0.0.0.0 --port ${PORT:-8000}

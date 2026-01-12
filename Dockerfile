# syntax=docker/dockerfile:1.4
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y build-essential curl && rm -rf /var/lib/apt/lists/*

# Install Poetry
ENV POETRY_VERSION=2.1.3
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="/root/.local/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy pyproject and lock file first
COPY pyproject.toml poetry.lock ./

# Install dependencies
RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi

# Copy source code and required files
COPY src/ ./src/
COPY context/ ./context/
COPY templates/ ./templates/
COPY data/ ./data/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY start.sh ./

# Create folders for volume mounts (optional but safe)
RUN mkdir -p ./data ./logs

# Build FAISS index at build time (requires OPENAI_API_KEY as build arg)
ARG OPENAI_API_KEY
RUN if [ -n "$OPENAI_API_KEY" ]; then \
    echo "Building FAISS index..." && \
    python -c "from src.agent_test.rag_chain import build_or_load_vectorstore; build_or_load_vectorstore()" && \
    echo "FAISS index built successfully"; \
    else echo "Skipping FAISS build (no API key)"; fi

# Make startup script executable
RUN chmod +x start.sh

# Expose the port
EXPOSE 8000

# Run startup script (handles migrations + starts app)
CMD ["./start.sh"]

# syntax=docker/dockerfile:1.4
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y build-essential curl && rm -rf /var/lib/apt/lists/*

# Install Poetry
ENV POETRY_VERSION=1.8.2
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

# Create folders for volume mounts (optional but safe)
RUN mkdir -p ./data ./logs

# Expose the port
EXPOSE 8000

# Run FastAPI app (Railway uses $PORT environment variable)
CMD uvicorn src.agent_test.main:app --host 0.0.0.0 --port ${PORT:-8000}

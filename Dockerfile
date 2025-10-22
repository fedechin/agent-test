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
COPY pyproject.toml poetry.lock README.md ./

# Install dependencies
RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi

# Copy source code and required files
COPY src/ ./src/
COPY context/ ./context/
COPY templates/ ./templates/
COPY data/ ./data/
COPY migrate_add_role.py ./
COPY start.sh ./

# Create folders for volume mounts (optional but safe)
RUN mkdir -p ./data ./logs

# Make startup script executable
RUN chmod +x start.sh

# Expose the port
EXPOSE 8000

# Run startup script (handles migrations + starts app)
CMD ["./start.sh"]

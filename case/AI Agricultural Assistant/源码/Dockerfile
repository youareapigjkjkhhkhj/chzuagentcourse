# AgriGPT Backend - for Render (repo root) and docker-compose
# Build context: repo root
FROM python:3.11-slim

WORKDIR /app

# Install system deps for sentence-transformers (cmake for sentencepiece if built from source)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
ENV PYTHONPATH=/app

EXPOSE 8000

# Render injects PORT; default 8000 for local/docker-compose
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

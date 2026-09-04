FROM python:3.11-slim

WORKDIR /app

# If your host needs build tools for a source wheel, uncomment:
#   RUN apt-get update && apt-get install -y --no-install-recommends gcc g++
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY pyproject.toml ./
COPY src ./src
COPY config ./config
RUN pip install --no-cache-dir .

# Sample documents so a fresh volume can be seeded (scripts/ingest.py).
COPY data/sample ./data/sample
COPY scripts ./scripts
COPY .env.example ./

EXPOSE 8000

# Mount a persistent volume at /app/data for ChromaDB, SQLite stores and
# uploads. The app's settings default all data paths under ./data.
VOLUME ["/app/data"]

CMD ["sh", "-c", "uvicorn src.api.main:app --host 0.0.0.0 --port \"${PORT:-8000}\""]

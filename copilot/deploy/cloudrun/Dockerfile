# BETA AID card copilot for Cloud Run, one image per region. The build context is staged by stage.sh: the copilot code,
# the governed knowledge documents, the Grain Atlas, and ONLY this region's snapshot plus the knowledge index (data
# never enters git; it lives in this region's Artifact Registry repository).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.hf PYTHONPATH=/app/copilot/src

RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.8.0 \
 && pip install "anthropic>=0.69" "duckdb>=1.5.6" "fastapi>=0.115" "numpy>=2.0" "pyyaml>=6.0" \
      "scikit-learn>=1.9.1" "sentence-transformers>=3.0" "uvicorn>=0.32" \
 && python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-small')"

WORKDIR /app
COPY copilot/src /app/copilot/src
COPY copilot/corpus /app/copilot/corpus
COPY knowledge /app/knowledge
COPY atlas.html /app/atlas.html
COPY data /app/data

ENV COPILOT_SNAPSHOT=/app/data/snapshot.duckdb \
    COPILOT_KB_INDEX=/app/data/kb_index \
    COPILOT_STORE=/var/copilot/operations.sqlite \
    COPILOT_AUDIT=/var/copilot/audit.jsonl \
    COPILOT_ATLAS=/app/atlas.html \
    COPILOT_KNOWLEDGE=/app/knowledge \
    PORT=8080

RUN useradd --create-home --uid 10001 copilot && mkdir -p /var/copilot && chown -R copilot /var/copilot /app
USER copilot
CMD ["sh", "-c", "exec uvicorn copilot.app:app --host 0.0.0.0 --port ${PORT}"]

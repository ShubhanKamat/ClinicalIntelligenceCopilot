FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/opt/hf-cache
ENV AWS_REGION=us-east-1

WORKDIR /app


# ------------------------------------------------------------
# Native dependency required by PyTorch / sklearn stack
# ------------------------------------------------------------

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*


# ------------------------------------------------------------
# Python dependencies
# ------------------------------------------------------------

COPY requirements-deploy.txt .

RUN python -m pip install \
    --no-cache-dir \
    --upgrade pip \
    && python -m pip install \
    --no-cache-dir \
    -r requirements-deploy.txt


# ------------------------------------------------------------
# Bake the frozen BGE query encoder into the image.
#
# This prevents the deployed service from downloading the
# embedding model every time the container starts.
# ------------------------------------------------------------

RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-base-en-v1.5'); print('BGE MODEL CACHED')"


# ------------------------------------------------------------
# Application
# ------------------------------------------------------------

COPY src ./src


# ------------------------------------------------------------
# Frozen V3 data artifacts only
# ------------------------------------------------------------

RUN mkdir -p \
    ./data/processed \
    ./data/retrieval

COPY data/processed/obesity_development_core_stage5_semantics.parquet \
     ./data/processed/obesity_development_core_stage5_semantics.parquet

COPY data/retrieval/retrieval_chunks.parquet \
     ./data/retrieval/retrieval_chunks.parquet

COPY data/retrieval/bge_base_en_v1_5_chunk_embeddings.npy \
     ./data/retrieval/bge_base_en_v1_5_chunk_embeddings.npy


# ------------------------------------------------------------
# Non-root runtime user
# ------------------------------------------------------------

RUN useradd \
    --create-home \
    --shell /bin/bash \
    appuser \
    && chown -R appuser:appuser \
        /app \
        /opt/hf-cache

USER appuser


EXPOSE 8000


CMD ["python", "-m", "uvicorn", "src.copilot.api:app", "--host", "0.0.0.0", "--port", "8000"]



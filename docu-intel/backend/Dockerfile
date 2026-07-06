FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=5

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --default-timeout=120 --retries=5 --prefix=/install -r /app/requirements.txt \
    && python -m pip install --no-deps --prefix=/install paddlepaddle==3.3.1 \
    && python -m pip install --default-timeout=120 --retries=5 --prefix=/install 'paddlex[ocr]==3.5.2'

# --- Runtime stage ---
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgl1 \
    libgomp1 \
    poppler-utils \
    # `libreoffice-core` alone ships the soffice binary under
    # /usr/lib/libreoffice/program/ but NOT a /usr/bin/soffice symlink
    # and NOT the writer module needed for .doc -> .docx conversion
    # (see app/parsers/doc.py). `libreoffice-writer` adds the writer
    # module; `libreoffice-common` adds the /usr/bin/soffice symlink
    # so shutil.which("soffice") works in the parser's _find_libreoffice.
    libreoffice-core \
    libreoffice-writer \
    libreoffice-common \
    # H-2: gosu is used by docker-entrypoint.sh to drop privileges
    # from root (which performs the bind-mount chown) to the non-root
    # appuser before exec'ing the actual worker / uvicorn process.
    gosu \
    curl \
    tesseract-ocr \
    tesseract-ocr-spa \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

RUN groupadd --system --gid 10001 appuser \
    && useradd --system --uid 10001 --gid appuser --home /app appuser \
    && mkdir -p /app/data/files /app/data/input \
    && chown -R appuser:appuser /app

# H-2: install the entrypoint that fixes bind-mount ownership on
# Linux/Windows hosts and then drops to the non-root appuser. See
# docker-entrypoint.sh for the full design.
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

COPY app /app/app
COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini
COPY scripts /app/scripts

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

# H-1: pull the alembic step OUT of the backend CMD. Running migrations
# at container start is not race-safe when two backend replicas come up
# at the same time (rolling deploy, autoscale); the previous behaviour
# could corrupt ``alembic_version``. The migrations now live in a
# dedicated ``migrate`` sidecar (see docker-compose.yml and
# docker-compose.prod.yml) that operators run once per deploy.
#
# The CMD stays a one-shot ``uvicorn`` for backwards compatibility — if
# the operator forgets to run ``migrate`` first, the backend will fail
# fast at the first DB query with a clear "table does not exist" error
# (no silent corruption).
#
# SEC-RL-1 (Sprint 0): pass --proxy-headers so uvicorn populates
# ``request.client.host`` from a trusted reverse proxy. The list of
# trusted proxy IPs is injected via the UVICORN_FORWARDED_ALLOW_IPS
# env var (set in .env.production). Default "*" is intentionally
# permissive in local dev; in production the operator MUST pin it to
# the actual reverse-proxy CIDR (e.g. "10.0.0.0/8").
#
# NOTE: do NOT wrap ${UVICORN_FORWARDED_ALLOW_IPS:-*} in single quotes
# inside this sh -c string — single quotes prevent shell variable
# expansion, and uvicorn would receive the literal placeholder text.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=${UVICORN_FORWARDED_ALLOW_IPS:-127.0.0.1}"]

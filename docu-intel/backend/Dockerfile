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
    && python -m pip install --no-deps --prefix=/install paddlepaddle==3.3.1

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

COPY app /app/app
COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini
COPY scripts /app/scripts
# Make the migration entrypoint executable in the image.
# ``COPY`` from Windows or from a git checkout does not always
# preserve the executable bit; the ``migrate`` compose service
# invokes this script via ``entrypoint:`` so it must be +x.
RUN chmod +x /app/scripts/entrypoint-migrate.sh

USER appuser

# SEC-RL-1 (Sprint 0): pass --proxy-headers so uvicorn populates
# ``request.client.host`` from a trusted reverse proxy. The list of
# trusted proxy IPs is injected via the UVICORN_FORWARDED_ALLOW_IPS
# env var (set in .env.production).
#
# SEC-BLOCK-7: the default is now the RFC1918 private network ranges
# (``10.0.0.0/8``, ``172.16.0.0/12``, ``192.168.0.0/16``) plus the
# loopback (``127.0.0.0/8``) so the default is not wide open (``*``).
# Operators should still pin ``UVICORN_FORWARDED_ALLOW_IPS`` to the
# actual reverse-proxy CIDR in ``.env.production``; the default
# is a safety net for the case where the env var is missing.
#
# NOTE: do NOT wrap ${UVICORN_FORWARDED_ALLOW_IPS:-...} in single
# quotes inside this sh -c string — single quotes prevent shell
# variable expansion, and uvicorn would receive the literal placeholder text.
#
# Migrations are NOT run from the CMD. A separate ``migrate`` service
# in docker-compose.yml / docker-compose.prod.yml runs
# ``scripts/entrypoint-migrate.sh`` once at stack start and the
# backend / workers declare ``depends_on.migrate.condition:
# service_completed_successfully``. Running ``alembic upgrade head``
# from every uvicorn replica was racing on ``alembic_version`` when
# more than one replica booted at the same time.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=${UVICORN_FORWARDED_ALLOW_IPS:-127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16}"]

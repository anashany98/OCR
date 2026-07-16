# vLLM remains in this image only.  The tag is intentionally explicit; pin a
# digest in the deployment lockfile after validating the target CUDA driver.
# vLLM/FlashInfer compiles architecture-specific CUDA kernels on first boot;
# the runtime image does not ship nvcc, so use the matching devel variant.
FROM nvidia/cuda:12.8.0-cudnn-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models/huggingface \
    TRANSFORMERS_CACHE=/models/huggingface

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential python3 python3-dev python3-pip python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 ovis \
    && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/ovis --shell /usr/sbin/nologin ovis \
    && mkdir -p /app /models/huggingface \
    && chown -R ovis:ovis /app /models /home/ovis

WORKDIR /app
COPY requirements.txt .
RUN python3 -m pip install --upgrade pip \
    && python3 -m pip install -r requirements.txt
COPY --chown=ovis:ovis . .
RUN chmod 0755 /app/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

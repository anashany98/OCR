#!/bin/sh
set -eu

# Named Docker volumes are initialised as root. Repair the cache ownership once
# and then drop privileges before vLLM or FastAPI start; model files are never
# written by the root process that receives the container signal.
mkdir -p /models/huggingface
chown -R ovis:ovis /models/huggingface
exec runuser -u ovis -- "$@"

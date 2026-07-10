#!/bin/bash
# Load vision model on LM Studio
echo "=== Loading qwen3-vl-8b-instruct ==="
curl -s -X POST "http://host.docker.internal:1234/v1/models/qwen3-vl-8b-instruct/load" \
  -H "Content-Type: application/json" \
  -d '{}'
echo ""
echo "=== Checking loaded models ==="
curl -s "http://host.docker.internal:1234/v1/models" | python3 -m json.tool

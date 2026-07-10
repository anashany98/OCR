#!/bin/bash
curl -s -X POST http://host.docker.internal:1235/load \
  -H "Content-Type: application/json" \
  -d '{"model": "qwen3-vl-8b-instruct"}'

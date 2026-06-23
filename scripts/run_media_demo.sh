#!/usr/bin/env bash
set -euo pipefail

exec python3 -m uvicorn backend.media_production.main:app --host 127.0.0.1 --port 8766 --reload

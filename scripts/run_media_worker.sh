#!/usr/bin/env bash
set -euo pipefail

exec python3 -m backend.media_production.worker

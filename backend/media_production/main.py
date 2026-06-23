from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import load_env_file
from backend.media_production.orchestrator import MediaProductionOrchestrator
from backend.media_production.router import router


ROOT_DIR = Path(__file__).resolve().parents[2]
MEDIA_APP_DIR = ROOT_DIR / "media_app"
# The media system deliberately loads only its own local configuration. It must
# not inherit the financial app's .env file, which contains the signing private key.
load_env_file(ROOT_DIR / ".env.media.production")
storage_dir = Path(os.getenv("MEDIA_PRODUCTION_STORAGE_DIR", str(ROOT_DIR / "backend" / "media_storage")))
origins = [item.strip() for item in os.getenv("MEDIA_ALLOWED_ORIGINS", "http://localhost:8765").split(",") if item.strip()]

app = FastAPI(title="财报掘金音视频生产服务", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-Media-Access-Token", "X-Media-Admin-Token"])
app.state.media_orchestrator = MediaProductionOrchestrator(storage_dir)
app.include_router(router)

if MEDIA_APP_DIR.exists():
    app.mount("/", StaticFiles(directory=str(MEDIA_APP_DIR), html=True), name="media-frontend")

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse

from backend.media_production.schema import CreateRequestPayload, ImportBriefRequest, ReviewPayload
from backend.media_production.security import env_multiline, verify_payload


router = APIRouter(prefix="/api/media", tags=["media-production"])


def orchestrator(request: Request):
    return request.app.state.media_orchestrator


def admin_token(value: str = Header(default="", alias="X-Media-Admin-Token")):
    expected = os.getenv("MEDIA_ADMIN_TOKEN", "").strip()
    if not expected or value != expected:
        raise HTTPException(status_code=403, detail="需要有效的媒体管理员凭证。")
    return "admin"


def requester_token(value: str = Header(default="", alias="X-Media-Access-Token")):
    return value


@router.get("/health")
def health(request: Request):
    return {"ok": True, "service": "media-production", "mode": request.app.state.media_orchestrator.mode}


@router.post("/briefs")
def import_brief(payload: ImportBriefRequest, svc=Depends(orchestrator)):
    public_key = env_multiline("MEDIA_BRIEF_PUBLIC_KEY")
    brief = payload.brief
    if not public_key:
        raise HTTPException(status_code=503, detail="未配置 MEDIA_BRIEF_PUBLIC_KEY，无法验证脚本来源。")
    if not verify_payload(brief.unsigned_payload(), brief.signature, public_key):
        raise HTTPException(status_code=401, detail="VideoBrief 签名无效。")
    try:
        return svc.import_brief(brief.dict())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/briefs/{brief_id}/requests")
def create_request(brief_id: str, payload: CreateRequestPayload, svc=Depends(orchestrator)):
    try:
        return svc.create_request(brief_id, payload.output_profile)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/requests/{request_id}")
def get_request(request_id: str, token=Depends(requester_token), svc=Depends(orchestrator)):
    try:
        return svc.get_request(request_id, token)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@router.get("/admin/requests")
def review_queue(_admin=Depends(admin_token), svc=Depends(orchestrator)):
    return {"items": svc.list_review_queue()}


@router.post("/admin/requests/{request_id}/review")
def review_request(request_id: str, payload: ReviewPayload, actor=Depends(admin_token), svc=Depends(orchestrator)):
    try:
        return svc.review(request_id, payload.action, payload.note, actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/requests/{request_id}/assets/{asset_id}")
def download_asset(request_id: str, asset_id: str, token=Depends(requester_token), svc=Depends(orchestrator)):
    try:
        path, mime_type = svc.asset_path(request_id, asset_id, token)
        return FileResponse(path, media_type=mime_type, filename=Path(path).name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

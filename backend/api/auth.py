from fastapi import APIRouter, Depends, Header, HTTPException

from backend.api.deps import services
from backend.schemas.models import LoginRequest, RegisterRequest
from backend.services.auth_service import AuthError


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register")
def register(request: RegisterRequest, svc=Depends(services)):
    try:
        return svc.auth_service.register(request.username, request.password, request.phone)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/login")
def login(request: LoginRequest, svc=Depends(services)):
    try:
        return svc.auth_service.login(request.username, request.password)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


@router.get("/me")
def me(authorization: str = Header(default=""), svc=Depends(services)):
    try:
        return {"user": svc.auth_service.me(_token_from_header(authorization))}
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


@router.post("/logout")
def logout(authorization: str = Header(default=""), svc=Depends(services)):
    svc.auth_service.logout(_token_from_header(authorization))
    return {"ok": True}


def _token_from_header(value: str) -> str:
    prefix = "Bearer "
    if value.startswith(prefix):
        return value[len(prefix) :].strip()
    return ""

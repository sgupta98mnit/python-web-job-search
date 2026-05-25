"""Authentication routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from api.auth import SESSION_COOKIE, SESSION_DAYS, make_cookie, verify_password
from api.deps import require_auth
from api.schemas import LoginRequest, OkResponse

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/auth/login", response_model=OkResponse)
def login(body: LoginRequest, response: Response) -> OkResponse:
    if not verify_password(body.password):
        raise HTTPException(status_code=401, detail="invalid password")

    response.set_cookie(
        SESSION_COOKIE,
        make_cookie(),
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        path="/",
    )
    return OkResponse()


@router.post("/auth/logout", response_model=OkResponse)
def logout(response: Response, _: dict = Depends(require_auth)) -> OkResponse:
    response.delete_cookie(SESSION_COOKIE, path="/")
    return OkResponse()


@router.get("/me", response_model=OkResponse)
def me(_: dict = Depends(require_auth)) -> OkResponse:
    return OkResponse()

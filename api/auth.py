"""Cookie auth helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Any

from fastapi import HTTPException

import config  # noqa: F401  # loads .env

log = logging.getLogger(__name__)

SESSION_DAYS = 30
SESSION_COOKIE = "app_session"

_APP_SECRET: str | None = None


def configure_auth() -> None:
    if not os.getenv("APP_PASSWORD"):
        raise RuntimeError("APP_PASSWORD is required for the API")

    secret = os.getenv("APP_SECRET")
    if not secret:
        secret = secrets.token_hex(32)
        log.warning("APP_SECRET is unset; generated a dev-only secret for this process")

    global _APP_SECRET
    _APP_SECRET = secret


def verify_password(plain: str) -> bool:
    expected = os.getenv("APP_PASSWORD", "")
    return secrets.compare_digest(plain, expected)


def make_cookie() -> str:
    expires = int(time.time()) + SESSION_DAYS * 24 * 60 * 60
    payload = _b64encode(json.dumps({"sub": "me", "exp": expires}, separators=(",", ":")).encode())
    signature = _sign(payload)
    return f"{payload}.{signature}"


def parse_cookie(cookie: str | None) -> dict[str, Any]:
    if not cookie:
        raise HTTPException(status_code=401, detail="not authenticated")

    parts = cookie.split(".", 1)
    if len(parts) != 2:
        raise HTTPException(status_code=401, detail="invalid session")

    payload, signature = parts
    if not secrets.compare_digest(signature, _sign(payload)):
        raise HTTPException(status_code=401, detail="invalid session")

    try:
        claims = json.loads(_b64decode(payload))
    except ValueError as e:
        raise HTTPException(status_code=401, detail="invalid session") from e
    if int(claims.get("exp", 0)) < int(time.time()):
        raise HTTPException(status_code=401, detail="session expired")
    return claims


def _secret() -> bytes:
    if _APP_SECRET is None:
        configure_auth()
    return str(_APP_SECRET).encode()


def _sign(payload: str) -> str:
    return hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode())

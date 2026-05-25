"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from api.auth import SESSION_COOKIE, parse_cookie
from db.session import SessionLocal


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def require_auth(request: Request) -> dict[str, Any]:
    return parse_cookie(request.cookies.get(SESSION_COOKIE))

"""FastAPI app entrypoint."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.auth import configure_auth
from api.routes import applications, auth, resumes, search_boost, stats


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    configure_auth()

    app = FastAPI(title="Job Search Control Plane")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz", tags=["health"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(applications.router)
    app.include_router(resumes.router)
    app.include_router(search_boost.router)
    app.include_router(stats.router)
    return app


def _cors_origins() -> list[str]:
    raw = os.getenv("APP_CORS_ORIGINS", "http://localhost:3000")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app = create_app()

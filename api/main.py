"""FastAPI app entrypoint."""

from __future__ import annotations

import logging

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
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth.router)
    app.include_router(applications.router)
    app.include_router(resumes.router)
    app.include_router(search_boost.router)
    app.include_router(stats.router)
    return app


app = create_app()

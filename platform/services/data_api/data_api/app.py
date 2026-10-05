"""HTTP surface of the read-only BETA AID Data API."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from data_api import __version__


def cors_origins() -> list[str]:
    raw = os.environ.get("DATA_API_CORS_ORIGINS", "http://localhost:3000")
    return [part.strip() for part in raw.split(",") if part.strip()]


def create_app() -> FastAPI:
    app = FastAPI(title="BETA AID Data API", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "service": "beta-aid-data-api"}

    return app


app = create_app()

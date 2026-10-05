"""HTTP surface of the read-only BETA AID Data API."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from data_api import __version__
from data_api.db import DataApiError
from data_api.store import PostgresStore


def cors_origins() -> list[str]:
    raw = os.environ.get("DATA_API_CORS_ORIGINS", "http://localhost:3000")
    return [part.strip() for part in raw.split(",") if part.strip()]


def create_app(store: Any = None) -> FastAPI:
    app = FastAPI(title="BETA AID Data API", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.state.store = store if store is not None else PostgresStore()

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "service": "beta-aid-data-api"}

    @app.get("/serving/publications")
    def publications() -> dict:
        return {"publications": _call(app.state.store.publications)}

    @app.get("/serving/tables")
    def tables() -> dict:
        return {"tables": _call(app.state.store.tables)}

    return app


def _call(method: Any) -> Any:
    try:
        return method()
    except DataApiError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


app = create_app()

"""
Factored AI & Data Hackathon 2026
AI-First Banking Customer Service System - FastAPI Backend

Main application entry point.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from backend.app.routers import analytics, chat, health, models

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown events."""
    logger.info("Starting AI-First Banking Service")
    # TODO: Initialize database connections
    # TODO: Load ML models into memory
    # TODO: Initialize agent graph
    # TODO: Connect to Redis for session management
    yield
    logger.info("Shutting down AI-First Banking Service")
    # TODO: Cleanup connections


app = FastAPI(
    title="AI-First Banking Customer Service",
    description=(
        "Intelligent customer service system for LATAM banking operations. "
        "Handles transaction disputes, card support, account inquiries, "
        "and credit product information with multilingual support (ES/PT)."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# === CORS ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Prometheus Metrics ===
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# === Routers ===
app.include_router(health.router, tags=["Health"])
app.include_router(chat.router, prefix="/api/v1", tags=["Chat"])
app.include_router(analytics.router, prefix="/api/v1", tags=["Analytics"])
app.include_router(models.router, prefix="/api/v1", tags=["ML Models"])

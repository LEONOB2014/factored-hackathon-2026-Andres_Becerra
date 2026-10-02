"""Health check router."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint for Docker and load balancer probes."""
    return {"status": "healthy", "service": "ai-banking-api", "version": "0.1.0"}


@router.get("/ready")
async def readiness_check() -> dict[str, str]:
    """Readiness check - verifies all dependencies are available."""
    # TODO: Check database, Redis, Neo4j, MLflow connectivity
    return {"status": "ready"}

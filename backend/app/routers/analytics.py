"""Analytics router - Dashboard data endpoints."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/analytics/overview")
async def get_overview() -> dict:
    """Get system overview metrics for the dashboard."""
    # TODO: Query from analytics.* dbt marts
    return {
        "total_conversations": 0,
        "resolution_rate": 0.0,
        "avg_response_time_ms": 0,
        "escalation_rate": 0.0,
        "active_sessions": 0,
    }


@router.get("/analytics/disputes")
async def get_dispute_analytics() -> dict:
    """Get dispute resolution analytics."""
    # TODO: Query from analytics.mart_dispute_analytics
    return {"disputes_today": 0, "avg_resolution_days": 0, "sla_compliance_rate": 0.0}


@router.get("/analytics/sentiment")
async def get_sentiment_trends() -> dict:
    """Get customer sentiment trend data."""
    # TODO: Query from analytics.mart_sentiment_trends
    return {"positive_rate": 0.0, "negative_rate": 0.0, "neutral_rate": 0.0, "trend": []}

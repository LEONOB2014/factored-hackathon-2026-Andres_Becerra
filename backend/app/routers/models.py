"""ML Models router - Model inference endpoints."""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class FraudScoreRequest(BaseModel):
    """Request for fraud score prediction."""

    transaction_id: str
    amount: float
    currency: str
    channel: str
    merchant_category: str | None = None
    customer_id: str | None = None


class FraudScoreResponse(BaseModel):
    """Fraud score prediction response."""

    transaction_id: str
    fraud_score: float
    is_fraud: bool
    confidence: float
    risk_factors: list[str]


class IntentRequest(BaseModel):
    """Request for intent classification."""

    text: str
    language: str = "es"


class IntentResponse(BaseModel):
    """Intent classification response."""

    intent: str
    confidence: float
    all_intents: dict[str, float]


class SentimentRequest(BaseModel):
    """Request for sentiment analysis."""

    text: str
    language: str = "es"


class SentimentResponse(BaseModel):
    """Sentiment analysis response."""

    sentiment: str
    score: float
    confidence: float


@router.post("/models/fraud-score")
async def predict_fraud_score(request: FraudScoreRequest) -> FraudScoreResponse:
    """Predict fraud risk score for a transaction."""
    # TODO: Load XGBoost model from MLflow, run inference
    return FraudScoreResponse(
        transaction_id=request.transaction_id,
        fraud_score=0.15,
        is_fraud=False,
        confidence=0.92,
        risk_factors=[],
    )


@router.post("/models/intent")
async def classify_intent(request: IntentRequest) -> IntentResponse:
    """Classify customer intent from text."""
    # TODO: Load ONNX intent classifier, run inference
    return IntentResponse(
        intent="transaction_dispute",
        confidence=0.87,
        all_intents={
            "transaction_dispute": 0.87,
            "card_support": 0.05,
            "account_inquiry": 0.04,
            "credit_info": 0.02,
            "general": 0.02,
        },
    )


@router.post("/models/sentiment")
async def analyze_sentiment(request: SentimentRequest) -> SentimentResponse:
    """Analyze sentiment of customer text."""
    # TODO: Load ONNX sentiment model, run inference
    return SentimentResponse(sentiment="neutral", score=0.1, confidence=0.78)

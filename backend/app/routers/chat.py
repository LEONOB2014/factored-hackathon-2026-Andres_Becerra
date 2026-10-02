"""Chat router - WebSocket and REST endpoints for AI customer service."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

router = APIRouter()


class ChatRequest(BaseModel):
    """Chat request from customer."""

    message: str
    session_id: str
    customer_id: str | None = None
    language: str = "es"  # es, pt


class ChatResponse(BaseModel):
    """Chat response from AI agent."""

    message: str
    session_id: str
    intent: str | None = None
    confidence: float | None = None
    actions_taken: list[dict] | None = None
    escalated: bool = False
    metadata: dict | None = None


@router.post("/chat")
async def chat_message(request: ChatRequest) -> ChatResponse:
    """Handle a single chat message (REST endpoint for simple integrations)."""
    # TODO: Route through LangGraph agent orchestrator
    return ChatResponse(
        message="Sistema de atención bancaria en desarrollo. ¿En qué puedo ayudarle?",
        session_id=request.session_id,
        intent="greeting",
        confidence=0.95,
    )


@router.websocket("/chat/ws/{session_id}")
async def chat_websocket(websocket: WebSocket, session_id: str) -> None:
    """WebSocket endpoint for real-time chat conversations."""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            # TODO: Route through LangGraph agent orchestrator
            # TODO: Stream responses back via WebSocket
            response = {
                "message": "Procesando su solicitud...",
                "session_id": session_id,
                "type": "response",
            }
            await websocket.send_json(response)
    except WebSocketDisconnect:
        pass  # TODO: Persist conversation state

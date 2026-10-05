"""The HTTP surface: the one-page UI, the chat API and the control-plane atlas.

cd copilot && uv run uvicorn copilot.app:app --reload
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from copilot import tracing
from copilot.config import REPO, Settings
from copilot.engine import Engine
from copilot.identity import AuthError
from copilot.llm import LLM
from copilot.scenarios import resolve
from copilot.tools import Tools

STATIC = Path(__file__).with_name("static")
ATLAS = Path(
    __import__("os").environ.get(
        "COPILOT_ATLAS",
        REPO / "eda" / "reports" / "dashboards" / "grain_atlas" / "grain_atlas.html",
    )
)

app = FastAPI(title="LATAM Bank card copilot", version="0.1.0")


@lru_cache(maxsize=1)
def engine() -> Engine:
    s = Settings()
    tracing.setup()
    tools = Tools(s.snapshot, s.store, s.secret, s.confirm_ttl_s)
    llm = LLM(s.llm_model, s.llm_timeout_s) if s.llm_available else None
    return Engine(s, tools, llm=llm)


class LoginIn(BaseModel):
    customer_id: str
    otp: str


class MessageIn(BaseModel):
    text: str


class ConfirmIn(BaseModel):
    yes: bool


class StepUpIn(BaseModel):
    otp: str


def _token(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:]
    return None


def _out(reply) -> dict:
    return {
        "text": reply.text,
        "outcome": reply.outcome,
        "lang": reply.lang,
        "buttons": reply.buttons,
        "handoff": reply.handoff,
        "trace": reply.trace,
    }


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/atlas", response_class=HTMLResponse)
def atlas() -> FileResponse:
    if not ATLAS.is_file():
        raise HTTPException(404, "atlas not bundled")
    return FileResponse(ATLAS)


@app.get("/api/health")
def health() -> dict:
    e = engine()
    return {
        "ok": True,
        "policy_version": e.policy.version,
        "llm": e.llm is not None,
        "llm_model": e.s.llm_model if e.llm else None,
        "breaker": e.llm.breaker.state if e.llm else None,
        "intent_params": e.intent.params,
    }


@app.get("/api/demo")
def demo() -> dict:
    e = engine()
    return {
        "customers": list(resolve(e.s.snapshot).values()),
        "otp": e.s.otp_fixture,
        "stepup": e.s.stepup_fixture,
    }


@app.post("/api/session")
def session(body: LoginIn) -> dict:
    try:
        return {"token": engine().login(body.customer_id, body.otp)}
    except AuthError as err:
        raise HTTPException(401, err.code) from err


@app.post("/api/message")
def message(body: MessageIn, authorization: str | None = Header(default=None)) -> dict:
    return _out(engine().message(_token(authorization), body.text[:1000]))


@app.post("/api/confirm")
def confirm(body: ConfirmIn, authorization: str | None = Header(default=None)) -> dict:
    return _out(engine().confirm(_token(authorization), body.yes))


@app.post("/api/stepup")
def stepup(body: StepUpIn, authorization: str | None = Header(default=None)) -> dict:
    token, reply = engine().step_up(_token(authorization), body.otp)
    return {"token": token, **_out(reply)}


@app.get("/api/policy")
def policy() -> dict:
    e = engine()
    return {"version": e.policy.version, "intents": e.policy.intents, "vetoes": e.policy.vetoes}


@app.get("/api/audit/verify")
def audit_verify() -> dict:
    return engine().audit.verify()

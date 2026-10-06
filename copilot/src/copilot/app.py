"""The HTTP surface: the one-page UI, the chat API and the control-plane atlas.

cd copilot && uv run uvicorn copilot.app:app --reload
"""

from __future__ import annotations

import csv
import json
import os
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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

app = FastAPI(title="BETA AID card copilot", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(Settings().cors_origins),
    allow_methods=["GET", "POST"],
    allow_headers=["authorization", "content-type", "x-staff-code"],
)


@lru_cache(maxsize=1)
def engine() -> Engine:
    s = Settings()
    tracing.setup()
    tools = Tools(s.snapshot, s.store, s.secret, s.confirm_ttl_s, sandbox=s.sandbox)
    llm = LLM(s.llm_model, s.llm_timeout_s) if s.llm_available else None
    kb, kb_threshold = _knowledge()
    return Engine(s, tools, llm=llm, kb=kb, kb_threshold=kb_threshold)


def _knowledge():
    """The bundled knowledge-base retriever, when its index is built and the embedder is installed."""
    import json
    import logging

    from copilot.config import PROJECT
    from copilot.kb import INDEX, BundledRetriever

    try:
        kb = BundledRetriever(INDEX)
        kb.search("warm up", 1)  # loads the embedding model now, not on a customer's first question
    except Exception as e:  # noqa: BLE001 - the copilot runs without it (policy questions go out of scope)
        logging.getLogger(__name__).warning("knowledge base unavailable: %s", e)
        return None, 0.0
    thr = PROJECT / "corpus" / "kb_threshold.json"
    return kb, json.loads(thr.read_text())["threshold"] if thr.is_file() else 0.0


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
        "deployment": _deployment(e),
        "intent_params": e.intent.params,
        "knowledge_base": {
            "active_set_hash": e.kb.active_set_hash,
            "chunks": len(e.kb.chunks),
            "threshold": e.kb_threshold,
        }
        if e.kb
        else None,
    }


@app.get("/api/demo")
def demo() -> dict:
    e = engine()
    return {
        "customers": list(resolve(e.s.snapshot).values()),
        "otp": e.s.otp_fixture,
        "stepup": e.s.stepup_fixture,
        "staff": e.s.staff_fixture,
        "deployment": _deployment(e),
    }


def _deployment(e: Engine) -> dict:
    """Where this instance runs and which countries' data it holds (residency is visible, not just claimed)."""
    import duckdb

    con = duckdb.connect(str(e.s.snapshot), read_only=True)
    countries = [
        r[0] for r in con.execute("select distinct country_code from cards order by 1").fetchall()
    ]
    con.close()
    return {
        "name": os.environ.get("COPILOT_DEPLOYMENT", "local"),
        "region": os.environ.get("COPILOT_REGION"),
        "countries": countries,
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


# --- control plane (read-only aggregates from committed reports; no customer rows) ----------------------------------
NUM = ("value", "benchmark_value", "delta", "delta_lo", "delta_hi", "material", "mde")


@app.get("/api/control/readiness")
def control_readiness() -> dict:
    """The readiness scorecard (ADR-018): every candidate model, its out-of-time gain and its verdict."""
    path = engine().s.readiness_csv
    if not path.is_file():
        raise HTTPException(404, "readiness scorecard not bundled")
    with path.open(newline="") as f:
        rows = [
            {k: (float(v) if k in NUM and v not in ("", None) else v) for k, v in r.items()}
            for r in csv.DictReader(f)
        ]
    counts = {v: sum(r["verdict"] == v for r in rows) for v in ("green", "amber", "red")}
    return {"source": path.name, "counts": counts, "models": rows}


@app.get("/api/control/evaluation")
def control_evaluation() -> dict:
    """The frozen challenge-set results (headline and labelled re-runs), intent model and retrieval summaries."""
    d = engine().s.eval_dir
    out: dict = {"runs": []}
    for name in ("challenge.json", "challenge_after_fix.json"):
        f = d / name
        if f.is_file():
            r = json.loads(f.read_text())
            out["runs"].append(
                {
                    "label": r.get("label", "first scored run"),
                    "n_cases": r["n_cases"],
                    "manifest_ok": r["manifest_ok"],
                    "variants": {k: v["summary"] for k, v in r["variants"].items()},
                }
            )
    for key, name in (("intent_model", "intent_model.json"), ("retrieval", "kb_retrieval.json")):
        f = d / name
        if f.is_file():
            r = json.loads(f.read_text())
            if key == "intent_model":
                out[key] = {
                    "tuning": r["tuning"],
                    "held_out": [
                        {k: v for k, v in m.items() if k != "errors"} for m in r["held_out"]
                    ],
                }
            else:
                out[key] = {n: {k: v for k, v in m.items() if k != "rows"} for n, m in r.items()}
    return out


# --- staff: the agent desk (test staff code; four eyes on approvals) ------------------------------------------------
class HandoffStatusIn(BaseModel):
    status: str
    actor: str
    note: str = ""


def _staff(code: str | None) -> Engine:
    e = engine()
    if code != e.s.staff_fixture:
        raise HTTPException(401, "staff_code_required")
    return e


@app.get("/api/handoffs")
def handoffs(x_staff_code: str | None = Header(default=None)) -> dict:
    e = _staff(x_staff_code)
    cases = sorted(e.handoffs.values(), key=lambda c: c["packet"]["created_at"], reverse=True)
    return {"cases": cases}


@app.post("/api/handoffs/{handoff_id}/status")
def handoff_status(
    handoff_id: str, body: HandoffStatusIn, x_staff_code: str | None = Header(default=None)
) -> dict:
    e = _staff(x_staff_code)
    try:
        return e.update_handoff(handoff_id, body.status, body.actor, body.note)
    except KeyError as err:
        raise HTTPException(404, "unknown_handoff") from err
    except PermissionError as err:
        raise HTTPException(409, str(err)) from err
    except ValueError as err:
        raise HTTPException(422, str(err)) from err

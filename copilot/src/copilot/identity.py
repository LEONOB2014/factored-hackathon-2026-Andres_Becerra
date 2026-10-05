"""A test identity service: HMAC-signed session tokens with a TTL, and a step-up second factor.

Permissions live here and in the tool layer, never in the model: every tool call takes the customer from the verified
session, so no message can name another customer's data into scope.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass


class AuthError(Exception):
    """A missing, expired, tampered or insufficient credential."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign(payload: dict, key: bytes) -> str:
    body = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    mac = _b64(hmac.new(key, body.encode(), hashlib.sha256).digest())
    return f"{body}.{mac}"


def verify(token: str | None, key: bytes, now: float | None = None) -> dict:
    if not token or token.count(".") != 1:
        raise AuthError("missing")
    body, mac = token.split(".")
    want = _b64(hmac.new(key, body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(mac, want):
        raise AuthError("tampered")
    payload = json.loads(_unb64(body))
    if payload.get("exp", 0) < (now if now is not None else time.time()):
        raise AuthError("expired")
    return payload


@dataclass(frozen=True)
class Session:
    session_id: str
    customer_id: str
    level: str  # "otp" | "stepup"
    stepup_until: float
    exp: float

    @property
    def stepped_up(self) -> bool:
        return self.level == "stepup" and self.stepup_until >= time.time()


class Identity:
    def __init__(self, key: bytes, otp: str, stepup_otp: str, ttl_s: int, stepup_ttl_s: int, known):
        self.key, self.otp, self.stepup_otp = key, otp, stepup_otp
        self.ttl_s, self.stepup_ttl_s = ttl_s, stepup_ttl_s
        self.known = known  # callable: customer_id -> bool

    def login(self, customer_id: str, otp: str) -> str:
        if not self.known(customer_id):
            raise AuthError("unknown_customer")
        if not hmac.compare_digest(otp, self.otp):
            raise AuthError("bad_otp")
        now = time.time()
        return sign(
            {
                "sid": secrets.token_hex(8),
                "cid": customer_id,
                "lvl": "otp",
                "su": 0,
                "exp": now + self.ttl_s,
            },
            self.key,
        )

    def step_up(self, token: str, otp: str) -> str:
        p = verify(token, self.key)
        if not hmac.compare_digest(otp, self.stepup_otp):
            raise AuthError("bad_stepup")
        p.update(lvl="stepup", su=time.time() + self.stepup_ttl_s)
        return sign(p, self.key)

    def session(self, token: str | None, now: float | None = None) -> Session:
        p = verify(token, self.key, now)
        return Session(p["sid"], p["cid"], p["lvl"], p["su"], p["exp"])

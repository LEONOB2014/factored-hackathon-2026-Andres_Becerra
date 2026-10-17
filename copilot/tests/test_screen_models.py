"""The hosted-model speed screening (eval/screen_models.py), with a fake transport: no network."""

import importlib.util
import io
import urllib.error
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "screen_models", Path(__file__).resolve().parents[1] / "eval" / "screen_models.py"
)
screen_models = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(screen_models)

TIMES = {"ttft_ms": 412.34, "total_ms": 530.06, "tokens_in": 340, "tokens_out": 9}


def test_judge_accepts_only_a_json_object_with_a_known_intent():
    assert screen_models.judge('{"intent": "balance_limit"}') == (True, True)
    assert screen_models.judge('{"intent": "pizza"}') == (True, False)
    assert screen_models.judge("balance_limit") == (False, False)
    assert screen_models.judge("[1, 2]") == (False, False)


def test_screen_stores_a_warmup_and_every_timed_call():
    seen = []

    def send(model, user):
        seen.append(user)
        return '{"intent": "reissue_card"}', dict(TIMES)

    r = screen_models.screen(send, "prov", "org/model", 7)
    assert len(seen) == 8 and len(r["calls"]) == 7
    assert [c["i"] for c in r["calls"]] == list(range(7))
    assert r["calls"][5]["message"] == screen_models.MESSAGES[0][1]  # the messages cycle
    assert r["calls"][0]["total_ms"] == 530.1 and r["calls"][0]["valid_label"] is True
    assert r["provider"] == "prov" and r["model"] == "org/model"


def test_a_model_the_provider_refuses_is_stored_with_its_status_and_not_retried():
    calls = []

    def send(model, user):
        calls.append(model)
        raise urllib.error.HTTPError("u", 403, "gated", {}, io.BytesIO())

    r = screen_models.screen(send, "prov", "org/gated", 20)
    assert r["warmup"]["error"] == "HTTP 403" and r["calls"] == [] and len(calls) == 1


def test_a_timeout_is_a_result_not_a_crash():
    def send(model, user):
        raise TimeoutError

    r = screen_models.screen(send, "prov", "m", 3)
    assert r["warmup"]["error"] == "TimeoutError"


def test_slug_is_a_safe_file_name():
    assert screen_models.slug("tokenfactory", "Qwen/Qwen3-30B-A3B-Instruct-2507") == (
        "tokenfactory__Qwen_Qwen3-30B-A3B-Instruct-2507"
    )

"""A hosted OpenAI-compatible model (for example Featherless) as the copilot's language model.

No network: urlopen is replaced by a fake that records the request and streams a canned answer.
"""

import io
import json
from dataclasses import replace

import pytest

from copilot import llm_local
from copilot.config import Settings
from copilot.llm import PRICES, Usage

BASE = "https://api.example.test/v1"


@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.setenv("COPILOT_LLM_BACKEND", "openai")
    monkeypatch.setenv("COPILOT_LLM_BASE_URL", BASE)
    monkeypatch.setenv("COPILOT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("COPILOT_LLM_MODEL", "Qwen/Qwen2.5-14B-Instruct")


class FakeStream(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(captured, text='{"intent": "balance_limit"}', usage=(120, 9)):
    events = [
        {"choices": [{"delta": {"content": text[: len(text) // 2]}}]},
        {"choices": [{"delta": {"content": text[len(text) // 2 :]}}]},
        {"choices": [], "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1]}},
    ]
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"

    def _open(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = {k.lower(): v for k, v in req.header_items()}
        captured["body"] = json.loads(req.data)
        captured["timeout"] = timeout
        return FakeStream(body.encode())

    return _open


def test_available_only_with_a_base_url_and_a_key(monkeypatch):
    monkeypatch.setenv("COPILOT_LLM_BACKEND", "openai")
    monkeypatch.delenv("COPILOT_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("COPILOT_LLM_API_KEY", raising=False)
    assert not Settings().llm_available
    monkeypatch.setenv("COPILOT_LLM_BASE_URL", BASE)
    assert not Settings().llm_available
    monkeypatch.setenv("COPILOT_LLM_API_KEY", "test-key")
    assert Settings().llm_available
    assert not replace(Settings(), use_llm=False).llm_available


def test_one_streamed_call_to_the_hosted_endpoint(hosted, monkeypatch):
    captured = {}
    monkeypatch.setattr(llm_local.urllib.request, "urlopen", fake_urlopen(captured))
    text, t = llm_local.chat_any(
        "Qwen/Qwen2.5-14B-Instruct",
        "system",
        "user",
        fmt={"type": "object"},
        max_tokens=64,
        timeout_s=6,
    )
    assert captured["url"] == f"{BASE}/chat/completions"
    assert captured["headers"]["authorization"] == "Bearer test-key"
    assert captured["body"]["model"] == "Qwen/Qwen2.5-14B-Instruct"
    assert captured["body"]["stream"] is True and captured["body"]["temperature"] == 0
    assert captured["body"]["max_tokens"] == 64
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["messages"][0] == {"role": "system", "content": "system"}
    assert captured["timeout"] == 6
    assert text == '{"intent": "balance_limit"}'
    assert (t["tokens_in"], t["tokens_out"]) == (120, 9) and t["ttft_ms"] <= t["total_ms"]


def test_the_copilot_builds_the_hosted_client(hosted):
    from copilot import app as appmod

    client = appmod._llm(replace(Settings(), llm_model="Qwen/Qwen2.5-14B-Instruct"))
    assert isinstance(client, llm_local.LocalLLM) and client.model == "Qwen/Qwen2.5-14B-Instruct"


def test_classify_through_the_hosted_client(hosted, monkeypatch):
    monkeypatch.setattr(llm_local.urllib.request, "urlopen", fake_urlopen({}))
    intent, usage = llm_local.LocalLLM("Qwen/Qwen2.5-14B-Instruct", 6).classify("¿cuánto debo?")
    assert intent == "balance_limit" and usage.calls == 1


def test_prices_from_the_environment_feed_the_cost_report(hosted, monkeypatch):
    monkeypatch.setenv("COPILOT_LLM_PRICE_IN", "0.11")
    monkeypatch.setenv("COPILOT_LLM_PRICE_OUT", "0.28")
    monkeypatch.delitem(PRICES, "Qwen/Qwen2.5-14B-Instruct", raising=False)
    llm_local.LocalLLM("Qwen/Qwen2.5-14B-Instruct", 6)
    u = Usage("Qwen/Qwen2.5-14B-Instruct", 1_000_000, 1_000_000, 1, 0.0)
    assert u.cost_usd == pytest.approx(0.39)


def test_the_blaxel_gateway_keeps_its_url_header_and_model(monkeypatch):
    monkeypatch.delenv("COPILOT_LLM_BACKEND", raising=False)
    monkeypatch.setenv("BLAXEL_TOKEN", "blx-test")
    monkeypatch.setenv("BLAXEL_WORKSPACE", "ws")
    monkeypatch.setenv("COPILOT_GATEWAY_MODEL", "gpt-4o-mini")
    captured = {}
    monkeypatch.setattr(llm_local.urllib.request, "urlopen", fake_urlopen(captured, text="hola"))
    text, _ = llm_local.chat_any("blaxel/sandbox-openai", "system", "user", max_tokens=32)
    assert captured["url"] == "https://run.blaxel.ai/ws/models/sandbox-openai/v1/chat/completions"
    assert captured["headers"]["authorization"] == "Bearer blx-test"
    assert captured["headers"]["x-blaxel-workspace"] == "ws"
    assert captured["body"]["model"] == "gpt-4o-mini" and "response_format" not in captured["body"]
    assert text == "hola"

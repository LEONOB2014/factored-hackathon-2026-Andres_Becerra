"""The demo page: signing in never fails silently.

The page is plain HTML with inline JavaScript and no build step, so these checks read the served source. A browser
session was used to confirm the behaviour (choose nothing and press Sign in; then the pre-selected customer signs in).
"""

import re

from fastapi.testclient import TestClient


def page(engine, monkeypatch) -> str:
    from copilot import app as appmod

    monkeypatch.setattr(appmod, "engine", lambda: engine)
    return TestClient(appmod.app).get("/").text


def test_sign_in_without_a_customer_says_what_to_do(engine, monkeypatch):
    html = page(engine, monkeypatch)
    handler = re.search(r'\$\("#login"\)\.onclick=async\(\)=>\{(.*?)try\{', html, re.S).group(1)
    assert "if(!pick)return;" not in handler, "Sign in must not return silently without a customer"
    assert '$("#who").textContent=' in handler and "customer" in handler


def test_the_customer_list_is_labelled_as_a_choice(engine, monkeypatch):
    html = page(engine, monkeypatch)
    form = html[html.index("<h2>Sign in") : html.index('id="customers"')]
    assert 'for="customers"' in form or "Choose a demo customer" in form


def test_the_first_customer_is_preselected(engine, monkeypatch):
    html = page(engine, monkeypatch)
    loader = html[html.index('demo=await api("/api/demo")') :]
    assert re.search(r'if\(!pick\)\{?c\.querySelector\("\.cust"\)\??\.click\(\)', loader)

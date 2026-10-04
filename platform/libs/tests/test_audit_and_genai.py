"""Audit ledger + GenAI audit: append-only, chained, tamper-evident, crypto-shreddable, fully attributable."""

import psycopg
import pytest

from latam_platform import audit_ledger, genai_audit


def test_events_are_chained_and_immutable(writer_conn):
    for i in range(3):
        audit_ledger.append_event(writer_conn, "svc-test", "test.event", f"s{i}", {"i": i})
    assert all(not p for p in audit_ledger.verify_all(writer_conn).values())
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        writer_conn.execute("UPDATE ledger.event SET actor = 'x'")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        writer_conn.execute("DELETE FROM ledger.event")


def test_owner_cannot_mutate_and_bypass_is_detected(audit_db, writer_conn):
    audit_ledger.append_event(
        writer_conn, "svc-test", "test.event", "tamper-target", {"amount": 100}
    )
    with psycopg.connect(audit_db["superuser"], autocommit=True) as su:
        with pytest.raises(psycopg.errors.RaiseException):
            su.execute("UPDATE ledger.event SET payload = '{}' WHERE subject_ref = 'tamper-target'")
        su.execute("ALTER TABLE ledger.event DISABLE TRIGGER no_update_delete")
        su.execute(
            """UPDATE ledger.event SET payload = '{"amount": 1}' WHERE subject_ref = 'tamper-target'"""
        )
        su.execute("ALTER TABLE ledger.event ENABLE TRIGGER no_update_delete")
    problems = audit_ledger.verify_all(writer_conn)["ledger.event"]
    assert any("content hash mismatch" in p for _, p in problems)


def test_crypto_shredding_makes_pii_unreadable_but_chain_valid(audit_db):
    with psycopg.connect(audit_db["writer"], autocommit=True) as c:
        audit_ledger.append_event(
            c,
            "svc-test",
            "dispute.opened",
            "cust-tok-1",
            {"case": "K1"},
            pii_fields={"phone": "+52 55 1234 5678"},
            subject_token="cust-tok-1",
        )
        blob = c.execute(
            "SELECT payload->'encrypted'->>'phone' FROM ledger.event WHERE subject_ref='cust-tok-1'"
        ).fetchone()[0]
        assert "1234" not in blob
        assert audit_ledger.decrypt_for_subject(c, "cust-tok-1", blob) == "+52 55 1234 5678"
        assert audit_ledger.shred_subject(c, "cust-tok-1", actor="dpo")
        assert audit_ledger.decrypt_for_subject(c, "cust-tok-1", blob) is None
        assert not audit_ledger.verify_all(c)["dsar.request"]


def test_merkle_root_is_order_independent():
    assert audit_ledger.merkle_root(["a", "b", "c"]) == audit_ledger.merkle_root(["c", "a", "b"])


def test_genai_call_records_every_layer_and_blocks_ungrounded_numbers(audit_db):
    model = genai_audit.ModelVersion("local", "stub-llm", "rev-1", quantization="none")
    prompt = genai_audit.PromptVersion(
        "card_support",
        "1.0.0",
        "You explain card declines using only the context.",
        "Customer asks: {input}",
    )
    docs = [
        genai_audit.RetrievedItem(
            "pgvector",
            "card-policy",
            "2.0",
            "chunk-1",
            "Cards expire after 48 months; reissue takes 5 business days.",
            0.83,
        )
    ]

    def stub_llm(system, user, context):
        return genai_audit.LLMResult(
            output="Your card expired. Reissue takes 5 business days.", tokens_in=50, tokens_out=12
        )

    def lying_llm(system, user, context):
        return genai_audit.LLMResult(output="Reissue takes 2 days and costs 30 USD.")

    with psycopg.connect(audit_db["writer"], autocommit=True) as c:
        genai_audit.register_model_version(c, model, registered_by="mlops")
        genai_audit.register_prompt_version(
            c, prompt, registered_by="ai-eng", approved_by="model-risk"
        )
        ok = genai_audit.AuditedLLM(
            c, model, prompt, stub_llm, [genai_audit.numbers_grounded_guard], use_mlflow=False
        ).call(
            user_input="Why was my card 4111 1111 1111 1111 declined?",
            caller="agent-assist",
            purpose="card_support",
            retrieved=docs,
            country="MX",
            subject_token="cust-tok-2",
        )
        bad = genai_audit.AuditedLLM(
            c, model, prompt, lying_llm, [genai_audit.numbers_grounded_guard], use_mlflow=False
        ).call(
            user_input="How long is a reissue?",
            caller="agent-assist",
            purpose="card_support",
            retrieved=docs,
        )
        genai_audit.record_override(
            c,
            ok["request_id"],
            "supervisor-7",
            "edited",
            "Your card expired. Reissue takes 5 business days.",
            "tone",
            "Tu tarjeta venció.",
        )
        stored = c.execute(
            "SELECT input_redacted FROM genai.generation WHERE request_id = %s", (ok["request_id"],)
        ).fetchone()[0]
        n_retrieval = c.execute("SELECT count(*) FROM genai.retrieval").fetchone()[0]
        n_override = c.execute("SELECT count(*) FROM genai.human_override").fetchone()[0]
        problems = audit_ledger.verify_all(c)
    assert "<CREDIT_CARD>" in stored and "4111" not in stored
    assert not ok["blocked"] and bad["blocked"] and bad["output"] is None
    assert n_retrieval == 2 and n_override == 1
    assert all(not p for t, p in problems.items() if t.startswith("genai."))

"""pii_guard: every identifier type is caught, check digits suppress look-alikes, redaction keeps no value."""

import pytest

from latam_platform import pii_guard

VALID = {
    "EMAIL": "escribir a maria.perez@example.com hoy",
    "CREDIT_CARD": "tarjeta 4111 1111 1111 1111 bloqueada",
    "MX_CURP": "CURP GODE561231HDFRRN09 en expediente",
    "MX_RFC": "RFC GODE561231AB1 del cliente",
    "MX_CLABE": "transferir a la CLABE 002010077777777771",
    "BR_CPF": "CPF 529.982.247-25 informado",
    "BR_CNPJ": "empresa CNPJ 11.222.333/0001-81",
    "AR_CUIT": "CUIT 20-12345678-6 en la factura",
    "NATIONAL_ID_LABELED": "cédula 1.020.304.050 del titular",
    "PHONE": "llamar al +52 55 1234 5678",
    "IP_ADDRESS": "login desde 201.150.33.7 ayer",
}


@pytest.mark.parametrize("entity,text", VALID.items())
def test_detects_each_identifier(entity, text):
    res = pii_guard.scan(text, use_ner=False)
    assert entity in res.entities, res.entities


@pytest.mark.parametrize(
    "text",
    [
        "tarjeta 4111 1111 1111 1112 rechazada",  # fails Luhn
        "CPF 529.982.247-26",  # wrong check digit
        "CLABE 002010077777777772",  # wrong check digit
        "monto 1250000 COP aprobado el 2026-05-17",  # amounts and dates are not PII
    ],
)
def test_check_digits_reject_lookalikes(text):
    assert not pii_guard.scan(text, use_ner=False).has_pii


def test_redact_removes_values_and_keeps_only_hashes():
    text = "Cliente con CPF 529.982.247-25 y correo ana@example.com pide reembolso"
    red, res = pii_guard.redact(text, use_ner=False)
    assert "529.982.247-25" not in red and "ana@example.com" not in red
    assert "<BR_CPF>" in red and "<EMAIL>" in red
    assert all(len(f.text_sha256) == 64 for f in res.findings)

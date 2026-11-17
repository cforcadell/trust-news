import ssl
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))
from common.utils.kafka_contracts import kafka_admin_security_kwargs, kafka_security_kwargs


def test_aiokafka_tls_contract(monkeypatch, tmp_path):
    ca = tmp_path / "ca.crt"
    ca.write_text("test CA")
    monkeypatch.setenv("KAFKA_CA_FILE", str(ca))
    monkeypatch.setattr(ssl, "create_default_context", lambda cafile: ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
    settings = kafka_security_kwargs("SSL")
    assert settings["security_protocol"] == "SSL"
    assert settings["ssl_context"].check_hostname
    assert settings["ssl_context"].verify_mode == ssl.CERT_REQUIRED


@pytest.mark.parametrize("protocol", ["PLAINTEXT", "SASL_PLAINTEXT", "bad"])
def test_plaintext_or_unknown_protocol_fails_closed(protocol):
    with pytest.raises(ValueError, match="encrypted security protocol"):
        kafka_security_kwargs(protocol)


def test_missing_ca_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("KAFKA_CA_FILE", str(tmp_path / "missing.crt"))
    with pytest.raises(ValueError, match="CA file is missing"):
        kafka_security_kwargs("SSL")
    with pytest.raises(ValueError, match="CA file is missing"):
        kafka_admin_security_kwargs()


def test_kafka_python_admin_uses_same_ca(monkeypatch, tmp_path):
    ca = tmp_path / "ca.crt"
    ca.write_text("test CA")
    monkeypatch.setenv("KAFKA_CA_FILE", str(ca))
    assert kafka_admin_security_kwargs() == {
        "security_protocol": "SSL",
        "ssl_cafile": str(ca),
        "ssl_check_hostname": True,
    }

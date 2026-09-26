import pytest
from fastapi import HTTPException

from gateway import main as gateway


def test_presenting_client_prefers_azp():
    assert gateway.presenting_client_id({"azp": "TrustNewsWeb", "client_id": "Other"}) == "TrustNewsWeb"


def test_owner_key_does_not_change_with_web_presenter():
    assert gateway.get_computed_client_id({"azp": "TrustNewsWeb", "sub": "user-1"}) == "user_user-1"


def test_allowed_presenting_client_is_accepted(monkeypatch):
    monkeypatch.setattr(gateway, "KEYCLOAK_ALLOWED_CLIENT_IDS", {"TrustNewsWeb"})

    gateway.validate_presenting_client({"azp": "TrustNewsWeb", "sub": "user-1"})


@pytest.mark.parametrize(
    "claims",
    [
        {"azp": "OtherClient", "sub": "user-1"},
        {"client_id": "OtherClient", "sub": "user-1"},
        {"sub": "user-1"},
    ],
)
def test_unallowed_or_missing_presenting_client_is_rejected(monkeypatch, claims):
    monkeypatch.setattr(gateway, "KEYCLOAK_ALLOWED_CLIENT_IDS", {"TrustNewsWeb"})

    with pytest.raises(HTTPException) as error:
        gateway.validate_presenting_client(claims)

    assert error.value.status_code == 401
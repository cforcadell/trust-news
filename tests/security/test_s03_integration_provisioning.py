from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.security import provision_s03_integration as provision


def args(operation="create"):
    return Namespace(operation=operation, integration_id="partner-one",
                     org_id="6cb8f9aa-6465-40a8-a897-f7bc3e817722",
                     action=["orders:create"], news_generation_limit=10,
                     blockchain_validation_limit=0,
                     expires_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())


def test_catalog_and_new_client_identity():
    root = Path(__file__).resolve().parents[2]
    actions = provision.catalog(root)
    assert "orders:create" in actions
    assert "assermetry-news-handler" in actions["orders:create"]
    assert provision.client_id_for("partner-one") == "tnapi-partner-one"
    for invalid in ("TrustNewsApi", "TrustNewsWeb", "Partner One", "ab"):
        with pytest.raises(ValueError):
            provision.client_id_for(invalid)


def test_plan_blocks_unmanaged_client_and_accepts_matching_pending_resume():
    command = args()
    assert provision.checked_state(command, "https://issuer", None, None, None) == "READY"
    client = {"attributes": {provision.MARKER: "partner-one"}, "enabled": False}
    assert provision.checked_state(command, "https://issuer", {"attributes": {}}, None, None) == "BLOCKED_EXISTING"
    assert provision.checked_state(command, "https://issuer", {**client, "enabled": True}, None, None) == "BLOCKED_EXISTING"
    assert provision.checked_state(command, "https://issuer", client, None, None) == "RESUME"
    binding = {"issuer": "https://issuer", "azp": "tnapi-partner-one",
               "org_id": command.org_id, "status": "pending", "actions": command.action,
               "expires_at": datetime.fromisoformat(command.expires_at)}
    quota = {"quota_id": "integration_partner-one", "org_id": command.org_id,
             "status": "Active", "limits": {"news_generation": 10, "blockchain_validation": 0},
             "consumed": {"news_generation": 0, "blockchain_validation": 0}}
    assert provision.checked_state(command, "https://issuer", client, binding, quota) == "RESUME"
    assert provision.checked_state(command, "https://issuer", client, {**binding, "org_id": "other"}, quota) == "BLOCKED_MISMATCH"


def test_private_credentials_are_owner_only_and_not_silently_overwritten(tmp_path):
    path = provision.credential_path(tmp_path, "partner-one")
    provision.save_credentials(path, "tnapi-partner-one", "test-secret", replace=False)
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    with pytest.raises(RuntimeError, match="cannot be replaced"):
        provision.save_credentials(path, "tnapi-partner-one", "changed", replace=False)
    provision.save_credentials(path, "tnapi-partner-one", "changed", replace=True)
    assert "changed" in path.read_text()

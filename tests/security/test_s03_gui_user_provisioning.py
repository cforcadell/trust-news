import json
import stat
import sys
import uuid

import pytest

from scripts.security import provision_s03_gui_user as gui


ISSUER = "https://identity.example/auth/realms/TrustNews"


def managed_user(*, enabled=False):
    return {"id": "subject-a", "username": "synthetic_user", "enabled": enabled,
            "attributes": {gui.PROVISIONER_ATTRIBUTE: [gui.PROVISIONER_VALUE]}}


def test_plan_is_stable_for_new_user_and_never_switches_client(capsys):
    args = dict(context="k3s", issuer=ISSUER, username="synthetic_user",
                email=None, user=None, memberships=[], web_ready=True)
    first = gui.build_plan(**args)
    second = gui.build_plan(**args)
    assert first["can_apply"] is True
    assert first["client"] == "TrustNewsWeb"
    assert first["plan_sha256"] == second["plan_sha256"]
    gui.print_plan(first)
    output = capsys.readouterr().out
    assert "client=TrustNewsWeb" in output
    assert "s03_gui_provision=DRY_RUN" in output
    assert "subject-a" not in output


def test_existing_unmanaged_or_active_user_and_conflicting_membership_block():
    base = dict(context="k3s", issuer=ISSUER, username="synthetic_user",
                email=None, memberships=[], web_ready=True)
    unmanaged = {**managed_user(), "attributes": {}}
    assert gui.build_plan(**base, user=unmanaged)["state"] == "BLOCKED_EXISTING_USER"
    assert gui.build_plan(**base, user=managed_user(enabled=True))["can_apply"] is False
    subject = managed_user()["id"]
    expected_org = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{ISSUER}|{subject}"))
    same_owner = {"issuer": ISSUER, "subject": subject, "org_id": expected_org,
                  "active": True, "legacy_client_ids": [f"user_{subject}"]}
    assert gui.build_plan(**{**base, "memberships": [same_owner]}, user=managed_user())["state"] == "RESUME_DISABLED"
    conflict = {**same_owner, "active": False}
    assert gui.build_plan(**{**base, "memberships": [conflict]}, user=managed_user())["state"] == "BLOCKED_MEMBERSHIP"
    assert gui.build_plan(**{**base, "web_ready": False}, user=None)["state"] == "BLOCKED_WEB_CLIENT"


def test_private_credentials_are_0600_and_refuse_unrelated_existing_file(tmp_path):
    path = gui.private_credentials_path(tmp_path, "synthetic_user", resume=False)
    gui.write_credentials(path, "synthetic_user", "temporary-test-password", "user_subject-a")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert json.loads(path.read_text())["quota_client_id"] == "user_subject-a"
    with pytest.raises(RuntimeError, match="cannot be replaced"):
        gui.private_credentials_path(tmp_path, "synthetic_user", resume=False)
    assert gui.private_credentials_path(tmp_path, "synthetic_user", resume=True) == path


def test_private_credentials_refuse_symlinked_directory(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "secrets").symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError, match="cannot be a symlink"):
        gui.private_credentials_path(tmp_path, "synthetic_user", resume=False)


def test_web_client_must_have_gateway_and_service_audiences(monkeypatch):
    def request(_client, _method, path, **_kwargs):
        if path.endswith("/clients"):
            return [{"id": "web-uuid", "clientId": "TrustNewsWeb"}]
        if path.endswith("/default-client-scopes"):
            return [{"name": "trustnews-gateway-audience"}]
        return {"enabled": True, "standardFlowEnabled": True}

    monkeypatch.setattr(gui, "keycloak_request", request)
    required = {"trustnews-gateway-audience", "s03-aud-assermetry-news-handler"}
    assert gui.web_client_ready(object(), "/admin/realms/TrustNews", required) is False


def test_service_account_username_is_reserved(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["provision_s03_gui_user", "--context", "k3s",
                                  "--username", "service-account-test"])
    with pytest.raises(SystemExit, match="reserved"):
        gui.main()


def test_provision_enables_user_only_after_membership(monkeypatch, tmp_path):
    events = []
    user = managed_user()
    subject = user["id"]
    credential_path = gui.private_credentials_path(tmp_path, "synthetic_user", resume=False)

    def request(_client, method, path, **kwargs):
        events.append((method, path))
        if method == "GET" and path.endswith("/role-mappings/realm/composite"):
            return [{"name": "default-roles-trustnews"}]
        if method == "GET" and path.endswith(f"/users/{subject}"):
            return {**user, "enabled": any(event == ("PUT", f"/admin/realms/TrustNews/users/{subject}")
                                           for event in events)}
        return None

    class Collection:
        def create_index(self, *_args, **_kwargs):
            events.append(("INDEX", "membership"))

        def update_one(self, filt, update, *, upsert):
            assert filt["subject"] == subject and filt["active"] is True
            assert update["$addToSet"]["legacy_client_ids"] == f"user_{subject}"
            assert upsert is True
            events.append(("UPSERT", "membership"))

        def find_one(self, filt, projection):
            assert filt["subject"] == subject and filt["legacy_client_ids"] == f"user_{subject}"
            assert projection == {"_id": 1}
            return {"_id": "membership-id"}

    monkeypatch.setattr(gui, "keycloak_request", request)
    monkeypatch.setattr(gui, "keycloak_user", lambda *_: user)
    monkeypatch.setattr(gui, "membership_rows", lambda *_: [])
    gui.provision(object(), "/admin/realms/TrustNews", "synthetic_user", None,
                  None, ISSUER, Collection(), credential_path)
    assert ("UPSERT", "membership") in events
    assert events.index(("UPSERT", "membership")) < events.index(
        ("PUT", f"/admin/realms/TrustNews/users/{subject}"))
    assert all(not (method == "POST" and "/clients" in path) for method, path in events)
    assert credential_path.exists()


def test_privileged_realm_role_blocks_before_membership_or_password(monkeypatch, tmp_path):
    calls = []

    def request(_client, method, path, **_kwargs):
        calls.append((method, path))
        return [{"name": "trust-admin"}]

    monkeypatch.setattr(gui, "keycloak_request", request)
    path = gui.private_credentials_path(tmp_path, "synthetic_user", resume=False)
    with pytest.raises(RuntimeError, match="privileged"):
        gui.provision(object(), "/admin/realms/TrustNews", "synthetic_user", None,
                      managed_user(), ISSUER, object(), path)
    assert len(calls) == 1 and calls[0][0] == "GET"
    assert not path.exists()

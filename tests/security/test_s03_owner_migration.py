import pytest

from scripts.security.migrate_s03_owners import build_plan, print_plan, validate_apply_request


CONFIG = {"legacy_prefixes": ["user", "TrustNewsWeb", "TrustNewsApi"]}
ISSUER = "https://identity.example/realms/TrustNews"


def test_plan_maps_only_exact_keys_for_enabled_human_users(capsys):
    report = build_plan(
        issuer=ISSUER,
        config=CONFIG,
        order_counts={"user_subject-a": 2, "historical-owner": 1},
        quota_counts={"user_subject-a": 1},
        users=[
            {"id": "subject-a", "username": "alpha", "enabled": True},
            {"id": "subject-b", "username": "beta", "enabled": True},
        ],
        memberships=[],
    )

    assert report["mapped_users"] == 1
    assert report["mapped_aliases"] == 1
    assert report["unmapped_legacy_keys"] == 1
    assert report["can_apply"] is True
    assert report["plans"][0]["username"] == "alpha"
    assert report["plans"][0]["aliases"] == [
        {"key": "user_subject-a", "prefix": "user", "orders": 2, "quotas": 1}
    ]

    print_plan(report, "test-context")
    output = capsys.readouterr().out
    assert 'owner username="alpha" aliases=1' in output
    assert "subject-a" not in output
    assert "historical-owner" not in output


def test_existing_other_owner_or_inactive_membership_blocks_whole_plan():
    order = {"key": "user_subject-a", "orders": 1, "quotas": 0}
    user = {"id": "subject-a", "username": "alpha", "enabled": True}
    conflicting_owner = {
        "issuer": ISSUER, "subject": "someone-else", "org_id": "another-org",
        "active": True, "legacy_client_ids": [order["key"]],
    }
    report = build_plan(
        issuer=ISSUER, config=CONFIG,
        order_counts={order["key"]: order["orders"]}, quota_counts={},
        users=[user], memberships=[conflicting_owner],
    )
    assert report["ambiguous_or_conflicting_keys"] == 1
    assert report["mapped_aliases"] == 0
    assert report["can_apply"] is False

    inactive_membership = {
        "issuer": ISSUER,
        "subject": "subject-a",
        "org_id": report["plans"][0]["org_id"],
        "active": False,
        "legacy_client_ids": [order["key"]],
    }
    inactive_report = build_plan(
        issuer=ISSUER, config=CONFIG,
        order_counts={order["key"]: order["orders"]}, quota_counts={},
        users=[user], memberships=[inactive_membership],
    )
    assert inactive_report["ambiguous_or_conflicting_keys"] == 1
    assert inactive_report["can_apply"] is False

    inactive_without_alias = {**inactive_membership, "legacy_client_ids": []}
    no_alias_report = build_plan(
        issuer=ISSUER, config=CONFIG,
        order_counts={order["key"]: order["orders"]}, quota_counts={},
        users=[user], memberships=[inactive_without_alias],
    )
    assert no_alias_report["ambiguous_or_conflicting_keys"] == 1
    assert no_alias_report["can_apply"] is False


def test_plan_hash_is_deterministic_and_changes_with_mapping():
    args = {
        "issuer": ISSUER,
        "config": CONFIG,
        "order_counts": {"user_subject-a": 1},
        "quota_counts": {},
        "users": [{"id": "subject-a", "username": "alpha", "enabled": True}],
        "memberships": [],
    }
    first = build_plan(**args)
    second = build_plan(**args)
    changed = build_plan(**{**args, "order_counts": {"user_subject-a": 2}})

    assert first["plan_sha256"] == second["plan_sha256"]
    assert first["plan_sha256"] != changed["plan_sha256"]


def test_existing_active_membership_is_a_safe_idempotent_mapping():
    inputs = {
        "issuer": ISSUER,
        "config": CONFIG,
        "order_counts": {"user_subject-a": 1},
        "quota_counts": {"user_subject-a": 1},
        "users": [{"id": "subject-a", "username": "alpha", "enabled": True}],
    }
    initial = build_plan(**inputs, memberships=[])
    row = initial["plans"][0]
    existing = {
        "issuer": row["issuer"], "subject": row["subject"], "org_id": row["org_id"],
        "active": True, "legacy_client_ids": ["user_subject-a"],
    }
    repeated = build_plan(**inputs, memberships=[existing])

    assert repeated["can_apply"] is True
    assert repeated["mapped_aliases"] == 1


def test_apply_requires_matching_context_and_reviewed_hash():
    validate_apply_request(apply=False, context="k3s", confirm_context=None, confirm_plan=None)
    validate_apply_request(apply=True, context="k3s", confirm_context="k3s", confirm_plan="a" * 64)

    with pytest.raises(SystemExit, match="matching --context"):
        validate_apply_request(apply=True, context="k3s", confirm_context="kind", confirm_plan="a" * 64)
    with pytest.raises(SystemExit, match="matching --context"):
        validate_apply_request(apply=True, context="k3s", confirm_context="k3s", confirm_plan=None)
    with pytest.raises(SystemExit, match="only valid together"):
        validate_apply_request(apply=False, context="k3s", confirm_context="k3s", confirm_plan="a" * 64)

#!/usr/bin/env python3
"""Unified keyboard driven manager for S03 GUI users and OAuth integrations."""
import argparse
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def operation_python():
    """Choose an interpreter that can run the existing S03 engines."""
    candidates = [os.environ.get("TRUSTNEWS_S03_PYTHON"),
                  str(Path.home() / "trust-news-ops-venv" / "bin" / "python"),
                  str(ROOT / ".venv" / "bin" / "python"), sys.executable]
    tried = set()
    for candidate in candidates:
        if not candidate or candidate in tried:
            continue
        tried.add(candidate)
        try:
            check = subprocess.run([candidate, "-c", "import httpx, pymongo"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            continue
        if check.returncode == 0:
            return candidate
    return None


def menu(title, options):
    while True:
        print(f"\n{title}")
        for i, option in enumerate(options):
            print(f"{i + 1}. {option}")
        choice = input("Select a number (q = back): ").strip().lower()
        if choice == "q":
            return -1
        if choice.isdecimal() and 1 <= int(choice) <= len(options):
            return int(choice) - 1
        print("Invalid selection. Enter one of the listed numbers.")


def field(prompt):
    value = input(prompt + " (empty cancels): ").strip()
    return value or None


def field_default(prompt, default):
    value = input(f"{prompt} [{default}] (Enter accepts; q cancels): ").strip()
    if value.lower() == "q":
        return None
    return value or default


def expiry_two_years_from_now():
    now = datetime.now(timezone.utc)
    try:
        expiry = now.replace(year=now.year + 2)
    except ValueError:
        # Handle February 29 when the target year is not a leap year.
        expiry = now.replace(year=now.year + 2, month=2, day=28)
    return expiry.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def context_field():
    """Default to kubectl's active context, while permitting an explicit override."""
    try:
        result = subprocess.run(["kubectl", "config", "current-context"],
                                capture_output=True, text=True, timeout=10, check=False)
        default = result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        default = ""
    prompt = (f"Kubernetes context [{default}] (Enter accepts; q cancels): "
              if default else "Kubernetes context (q cancels): ")
    value = input(prompt).strip()
    if value.lower() == "q":
        return None
    return value or default or None


def suggested_id(context, family, python):
    result = subprocess.run([
        python, "-m", "scripts.security.inspect_s03", "--context", context,
        "--family", family, "--suggest-id",
    ], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode:
        print(result.stdout)
        input("Could not suggest an ID. Press Enter to return...")
        return None
    return next((line.split("=", 1)[1] for line in result.stdout.splitlines()
                 if line.startswith("suggested_id=")), None)


def reviewed_plan_digest(output):
    values = [token.split("=", 1)[1]
              for line in output.splitlines()
              for token in line.split()
              if token.startswith("plan_sha256=")]
    if len(values) != 1 or len(values[0]) != 64:
        return None
    if any(char not in "0123456789abcdef" for char in values[0]):
        return None
    return values[0]


def integration_actions():
    try:
        import json
        rows = json.loads((ROOT / "api/common/security/integration-routes.json").read_text(
            encoding="utf-8"))
        available = sorted({row["action"] for row in rows
                            if isinstance(row, dict) and isinstance(row.get("action"), str)})
    except (OSError, ValueError, KeyError, TypeError):
        print("Could not load the allowed API action catalog.")
        return None
    if not available:
        print("The allowed API action catalog is empty.")
        return None
    print("Allowed API actions:")
    for action in available:
        print(f"- {action}")
    print("- all (select every action listed above)")
    selected = []
    while True:
        value = input("Action (repeat for more; empty finishes; all selects all; q cancels): ").strip()
        if value.lower() == "q":
            return None
        if value.casefold() == "all":
            print("Selected all current catalog actions:")
            for action in available:
                print(f"- {action}")
            return available
        if not value:
            if selected:
                return selected
            print("Select at least one allowed action.")
            continue
        if value not in available:
            print("Action is not in the allowed catalog.")
            continue
        if value in selected:
            print("Action already selected.")
            continue
        selected.append(value)


def inventory(family):
    context = context_field()
    if not context:
        return
    search_label = "Organization UUID filter (empty = all)" if family == "org" else "Username/integration ID filter (empty = all)"
    search = field(search_label) or ""
    python = operation_python()
    if python is None:
        print("S03 inventory needs a Python environment with httpx and pymongo.")
        input("Press Enter to return...")
        return
    offset = 0
    while True:
        result = subprocess.run([
            python, "-m", "scripts.security.inspect_s03", "--context", context,
            "--family", family, "--search", search, "--offset", str(offset), "--limit", "25",
        ], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        print(result.stdout)
        if result.returncode:
            input("Inventory read failed. Enter to return...")
            return
        next_offset = next((int(line.split("=", 1)[1].split()[0])
                            for line in result.stdout.splitlines() if line.startswith("rows=")), None)
        count = next_offset
        if count is None or count < 25 or input("n = next page; Enter = return: ").strip().lower() != "n":
            return
        offset += count


def guided(family, operation):
    _guided_fields_and_apply(family, operation)


def _guided_fields_and_apply(family, operation):
    python = operation_python()
    if python is None:
        print("S03 operations need a Python environment with httpx and pymongo.")
        input("Press Enter to return...")
        return
    context = context_field()
    if not context:
        return
    args = ["--context", context]
    if family == "org":
        args += ["--org-id", str(uuid.uuid4())]
        for flag, label in (("--news-generation-limit", "Organization news generation limit"),
                            ("--blockchain-validation-limit", "Organization blockchain validation limit")):
            value = field_default(label, "9999")
            if value is None or not value.isdecimal():
                return
            args += [flag, value]
        module = "scripts.security.provision_s03_organization"
    elif family == "gui":
        suggestion = suggested_id(context, "web", python)
        if not suggestion:
            return
        username = field_default("OpenID username", suggestion)
        if not username:
            return
        org_id = str(uuid.uuid4())
        args += ["--username", username, "--org-id", org_id]
        email = field("Optional email")
        if email:
            args += ["--email", email]
        for flag, label in (("--news-generation-limit", "News generation limit"),
                            ("--blockchain-validation-limit", "Blockchain validation limit")):
            value = field_default(label, "9999")
            if value is None or not value.isdecimal():
                return
            args += [flag, value]
        module = "scripts.security.provision_s03_gui_user"
    else:
        if operation == "create":
            suggestion = suggested_id(context, "api", python)
            if not suggestion:
                return
            integration = field_default("OAuth integration ID", suggestion)
        else:
            integration = field("Integration ID")
        if not integration:
            return
        args += ["--integration-id", integration, "--operation", operation]
        module = "scripts.security.provision_s03_integration"
        if operation == "create":
            org_id = field("Organization UUID (existing active organization)")
            if not org_id:
                return
            args += ["--org-id", org_id]
            expiry = field_default("Expiry ISO-8601", expiry_two_years_from_now())
            if not expiry:
                return
            args += ["--expires-at", expiry]
            actions = integration_actions()
            if not actions:
                return
            for action in actions:
                args += ["--action", action]
        if operation in {"create", "limits"}:
            limits = [("--news-generation-limit", "Integration news generation limit"),
                      ("--blockchain-validation-limit", "Integration blockchain validation limit"),
                      ("--org-news-generation-limit", "Organization news generation limit"),
                      ("--org-blockchain-validation-limit", "Organization blockchain validation limit")]
            for flag, label in limits:
                value = (field_default(label, "9999") if operation == "create"
                         else field(label))
                if value is None or not value.isdecimal():
                    return
                args += [flag, value]
    preview = subprocess.run([python, "-m", module, *args], cwd=ROOT,
                             text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(preview.stdout)
    digest = reviewed_plan_digest(preview.stdout)
    if preview.returncode or not digest:
        input("Plan blocked. Press Enter to return...")
        return
    if input("Review the plan. Type APLICAR to continue: ").strip() != "APLICAR":
        return
    subprocess.run([python, "-m", module, *args, "--apply",
                    "--confirm-context", context, "--confirm-plan", digest], cwd=ROOT)
    input("Operation finished. Press Enter to return...")


def app():
    while True:
        family = menu("S03 - Unified management",
                      ["Web users - TrustNewsWeb", "API integrations - OAuth", "Exit"])
        if family < 0 or family == 2:
            return
        if family == 0:
            selected = menu("Web users", ["Create / resume", "List / inspect", "Back"])
            if selected == 0:
                guided("gui", "create")
            elif selected == 1:
                inventory("web")
        else:
            ops = ["Create integration", "List integrations", "Create organization", "List organizations",
                   "Change integration limits", "Rotate secret", "Suspend integration",
                   "Reactivate integration", "Retire integration", "Back"]
            selected = menu("API integrations - OAuth", ops)
            if selected == 1:
                inventory("api")
            elif selected == 2:
                guided("org", "create")
            elif selected == 3:
                inventory("org")
            elif selected in {0, 4, 5, 6, 7, 8}:
                operation = {0: "create", 4: "limits", 5: "rotate",
                             6: "suspend", 7: "reactivate", 8: "retire"}[selected]
                guided("oauth", operation)


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("An interactive terminal is required.", file=sys.stderr)
        return 2
    app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Collect a read-only, value-free Kubernetes inventory for any context."""

import argparse
import datetime as dt
import json
import subprocess
import sys


RESOURCE_TYPES = (
    "namespaces",
    "nodes",
    "deployments",
    "statefulsets",
    "daemonsets",
    "pods",
    "services",
    "ingresses",
    "networkpolicies",
)


def kubectl(context, resource):
    command = [
        "kubectl", "--context", context, "--request-timeout=10s",
        "get", resource, "--all-namespaces", "-o", "json",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"kubectl get {resource} failed (exit {result.returncode})")
    try:
        items = json.loads(result.stdout)["items"]
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(f"kubectl get {resource} returned invalid JSON") from exc
    if not isinstance(items, list):
        raise RuntimeError(f"kubectl get {resource} returned no item list")
    return items


def basic(item):
    metadata = item.get("metadata") or {}
    return {"namespace": metadata.get("namespace"), "name": metadata.get("name")}


def containers(spec):
    return sorted(
        [{"name": entry.get("name"), "image": entry.get("image")}
         for entry in spec.get("containers", [])],
        key=lambda entry: (entry["name"] or ""),
    )


def sanitize(resource, item):
    record = basic(item)
    spec = item.get("spec") or {}
    status = item.get("status") or {}
    if resource == "nodes":
        record["kubelet_version"] = (status.get("nodeInfo") or {}).get("kubeletVersion")
    elif resource in ("deployments", "statefulsets", "daemonsets"):
        record["kind"] = item.get("kind")
        record["desired"] = (spec.get("replicas") if resource != "daemonsets"
                             else status.get("desiredNumberScheduled"))
        record["ready"] = (status.get("readyReplicas") if resource != "daemonsets"
                           else status.get("numberReady")) or 0
        record["containers"] = containers(((spec.get("template") or {}).get("spec") or {}))
    elif resource == "pods":
        record["phase"] = status.get("phase")
        record["containers"] = containers(spec)
        record["image_ids"] = sorted(
            [{"name": entry.get("name"), "image_id": entry.get("imageID")}
             for entry in status.get("containerStatuses", [])],
            key=lambda entry: (entry["name"] or ""),
        )
    elif resource == "services":
        record["type"] = spec.get("type")
        record["ports"] = sorted(
            [{"port": entry.get("port"), "protocol": entry.get("protocol")}
             for entry in spec.get("ports", [])],
            key=lambda entry: (entry["port"] or 0, entry["protocol"] or ""),
        )
    elif resource == "ingresses":
        record["hosts"] = sorted({entry.get("host") for entry in spec.get("rules", [])
                                  if entry.get("host")})
    elif resource == "networkpolicies":
        record["policy_types"] = sorted(spec.get("policyTypes") or [])
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True, help="Explicit kubectl context")
    parser.add_argument("--environment", required=True, help="Human-readable environment label")
    args = parser.parse_args()
    report = {
        "schema_version": 1,
        "environment": args.environment,
        "context": args.context,
        "collected_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "resources": {},
        "errors": [],
    }
    for resource in RESOURCE_TYPES:
        try:
            report["resources"][resource] = sorted(
                [sanitize(resource, item) for item in kubectl(args.context, resource)],
                key=lambda item: (item["namespace"] or "", item["name"] or ""),
            )
        except RuntimeError as exc:
            report["errors"].append(str(exc))
    report["complete"] = not report["errors"]
    json.dump(report, sys.stdout, indent=2, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report["complete"] else 3


if __name__ == "__main__":
    sys.exit(main())

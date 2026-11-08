#!/usr/bin/env python3
"""Create a reusable local CA and per-Service TLS Secrets for kind.

Private keys remain outside the repository. Existing keys are reused; the
script never silently replaces a trust anchor or server identity.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess


def run(*args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def apply_secret(*kubectl_args):
    yaml = subprocess.check_output(["kubectl", "create", *kubectl_args, "--dry-run=client", "-o", "yaml"])
    subprocess.run(["kubectl", "apply", "-f", "-"], input=yaml, check=True, stdout=subprocess.DEVNULL)


def create_ca(folder):
    cert, key = folder / "ca.crt", folder / "ca.key"
    if cert.exists() != key.exists():
        raise RuntimeError("Incomplete existing CA")
    if not cert.exists():
        run("openssl", "req", "-x509", "-newkey", "rsa:3072", "-nodes", "-days", "365",
            "-subj", "/CN=Assermetry S03 kind CA", "-keyout", str(key), "-out", str(cert))
        os.chmod(key, 0o600)
    return cert, key


def create_service_cert(folder, ca_cert, ca_key, namespace, service):
    name = f"{namespace}-{service}"
    key, cert, csr, ext = (folder / f"{name}.{suffix}" for suffix in ("key", "crt", "csr", "ext"))
    if cert.exists() != key.exists():
        raise RuntimeError(f"Incomplete certificate for {name}")
    if not cert.exists():
        dns = f"{service}.{namespace}.svc.cluster.local"
        run("openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes", "-subj", f"/CN={dns}",
            "-keyout", str(key), "-out", str(csr))
        os.chmod(key, 0o600)
        ext.write_text("basicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\n"
                       "extendedKeyUsage=serverAuth\n"
                       f"subjectAltName=DNS:{dns},DNS:{service}.{namespace}.svc\n", encoding="utf-8")
        run("openssl", "x509", "-req", "-in", str(csr), "-CA", str(ca_cert), "-CAkey", str(ca_key),
            "-CAcreateserial", "-days", "90", "-out", str(cert), "-extfile", str(ext))
        csr.unlink()
        ext.unlink()
    return cert, key


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="docs/security/s03-local-services.json")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--apply-kind", action="store_true")
    args = parser.parse_args()
    if args.apply_kind:
        context = subprocess.check_output(["kubectl", "config", "current-context"], text=True).strip()
        if not context.startswith("kind-"):
            raise SystemExit(f"Refusing to apply local S03 material outside a kind context: {context}")
    folder = Path(args.output_dir).resolve()
    if folder.is_relative_to(Path.cwd().resolve()):
        raise SystemExit("PKI output must be outside the repository")
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    with open(args.config, encoding="utf-8") as handle:
        services = json.load(handle)
    ca_cert, ca_key = create_ca(folder)
    for namespace, service in {(row["namespace"], row["service"]) for row in services}:
        create_service_cert(folder, ca_cert, ca_key, namespace, service)
    if args.apply_kind:
        for namespace in {row["namespace"] for row in services}:
            apply_secret("secret", "generic", "s03-internal-ca", "-n", namespace, f"--from-file=ca.crt={ca_cert}")
        for row in services:
            namespace, service = row["namespace"], row["service"]
            name = f"{namespace}-{service}"
            apply_secret("secret", "tls", f"s03-tls-{service}", "-n", namespace,
                         f"--cert={folder / (name + '.crt')}", f"--key={folder / (name + '.key')}")
            print(f"s03_local_secret={namespace}/{service}")
    print(f"s03_local_pki=PASS services={len(services)} applied={args.apply_kind}")


if __name__ == "__main__":
    main()

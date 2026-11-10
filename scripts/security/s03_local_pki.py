#!/usr/bin/env python3
"""Create reusable local S03 certificate files for kind Kustomize overlays.

Private keys remain outside the repository. Existing keys are reused; the
script never silently replaces a trust anchor or server identity.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]


def run(*args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def create_ca(folder):
    cert, key = folder / "ca.crt", folder / "ca.key"
    if cert.exists() != key.exists():
        raise RuntimeError("Incomplete existing CA")
    if not cert.exists():
        run("openssl", "req", "-x509", "-newkey", "rsa:3072", "-nodes", "-days", "365",
            "-subj", "/CN=Assermetry S03 kind CA", "-keyout", str(key), "-out", str(cert))
        os.chmod(key, 0o600)
    return cert, key


def create_service_cert(folder, ca_cert, ca_key, namespace, service, extra_dns=()):
    name = f"{namespace}-{service}"
    key, cert, csr, ext = (folder / f"{name}.{suffix}" for suffix in ("key", "crt", "csr", "ext"))
    if cert.exists() != key.exists():
        raise RuntimeError(f"Incomplete certificate for {name}")
    if not cert.exists():
        dns = f"{service}.{namespace}.svc.cluster.local"
        run("openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes", "-subj", f"/CN={dns}",
            "-keyout", str(key), "-out", str(csr))
        os.chmod(key, 0o600)
        names = (dns, f"{service}.{namespace}.svc", *extra_dns)
        ext.write_text("basicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\n"
                       "extendedKeyUsage=serverAuth\n"
                       f"subjectAltName={','.join('DNS:' + item for item in names)}\n", encoding="utf-8")
        run("openssl", "x509", "-req", "-in", str(csr), "-CA", str(ca_cert), "-CAkey", str(ca_key),
            "-CAcreateserial", "-days", "90", "-out", str(cert), "-extfile", str(ext))
        csr.unlink()
        ext.unlink()
    return cert, key


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="docs/security/s03-local-services.json")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
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
    for namespace in ("infra", "apis"):
        link = ROOT / "k8s/s03/tls/overlays/local" / namespace / "pki"
        if link.is_symlink():
            if link.resolve() != folder:
                raise RuntimeError(f"Existing PKI link points elsewhere: {link}")
        elif link.exists():
            raise RuntimeError(f"PKI overlay path is not a symlink: {link}")
        else:
            link.symlink_to(folder, target_is_directory=True)
    print(f"s03_local_pki=PASS services={len(services)} overlay=prepared")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Provision the local Kafka TLS overlay from the existing S03 kind CA."""

import argparse
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import subprocess

from s03_local_pki import create_ca, create_service_cert


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pki-dir", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    pki = Path(args.pki_dir).resolve()
    if pki.is_relative_to(root):
        raise SystemExit("PKI material must be outside the repository")
    pki.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(pki, 0o700)
    ca, ca_key = create_ca(pki)
    cert, key = create_service_cert(
        pki, ca, ca_key, "infra", "kafka",
        extra_dns=("kafka", "kafka.infra", "kafka-0.kafka.infra.svc.cluster.local"),
    )
    subprocess.run(["openssl", "verify", "-CAfile", str(ca), str(cert)],
                   check=True, stdout=subprocess.DEVNULL)
    for hostname in ("kafka.infra.svc.cluster.local", "kafka-0.kafka.infra.svc.cluster.local"):
        subprocess.run(["openssl", "x509", "-in", str(cert), "-noout", "-checkhost", hostname],
                       check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["openssl", "x509", "-in", str(cert), "-noout", "-checkend", "86400"],
                   check=True, stdout=subprocess.DEVNULL)
    infra = root / "k8s/infra/kafka/overlays/local"
    apis = root / "k8s/apis/kafka-tls/overlays/local"
    infra.mkdir(parents=True, exist_ok=True)
    apis.mkdir(parents=True, exist_ok=True)
    env = infra / "kafka-tls.env"
    store = pki / "infra-kafka.p12"
    overlay_store = infra / "broker.p12"
    if env.exists() != store.exists():
        raise SystemExit("Incomplete Kafka local TLS overlay; restore both env and keystore")
    if not env.exists():
        password = secrets.token_urlsafe(36)
        subprocess.run([
            "openssl", "pkcs12", "-export", "-name", "kafka", "-in", str(cert),
            "-inkey", str(key), "-certfile", str(ca), "-out", str(store),
            "-passout", "env:S07A_STORE_PASSWORD",
        ], check=True, stdout=subprocess.DEVNULL,
            env={**os.environ, "S07A_STORE_PASSWORD": password})
        env.write_text(f"KEYSTORE_PASSWORD={password}\n", encoding="utf-8")
        os.chmod(store, 0o600)
        os.chmod(env, 0o600)
    else:
        password = dict(line.strip().split("=", 1) for line in env.read_text().splitlines())["KEYSTORE_PASSWORD"]
        exported = subprocess.check_output([
            "openssl", "pkcs12", "-in", str(store), "-clcerts", "-nokeys",
            "-passin", "env:S07A_STORE_PASSWORD",
        ], env={**os.environ, "S07A_STORE_PASSWORD": password}, stderr=subprocess.DEVNULL)
        current = subprocess.check_output(["openssl", "x509", "-in", str(cert), "-outform", "DER"])
        stored = subprocess.run(["openssl", "x509", "-outform", "DER"], input=exported,
                                check=True, capture_output=True).stdout
        if hashlib.sha256(current).digest() != hashlib.sha256(stored).digest():
            raise SystemExit("Existing broker.p12 does not match the PKI certificate")
    if overlay_store.is_symlink():
        if overlay_store.resolve() != store:
            raise SystemExit("Kafka overlay points to a different keystore")
    elif overlay_store.exists():
        raise SystemExit("Kafka overlay keystore must be a symlink to the external PKI directory")
    else:
        overlay_store.symlink_to(store)
    shutil.copyfile(ca, infra / "ca.crt")
    shutil.copyfile(ca, apis / "ca.crt")
    print("s07a_local_kafka_tls=READY")


if __name__ == "__main__":
    main()

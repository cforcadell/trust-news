#!/usr/bin/env bash
set -euo pipefail

cert_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
host="${1:-localhost}"

if [[ ! "$host" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]]; then
  printf 'Invalid DNS hostname: %s\n' "$host" >&2
  exit 2
fi

umask 077
key_file="$cert_dir/privkey.pem"
cert_file="$cert_dir/fullchain.pem"

if [[ -f "$key_file" ]]; then
  openssl req -x509 -sha256 -days 365 \
    -key "$key_file" -out "$cert_file" \
    -subj "/CN=$host" -addext "subjectAltName=DNS:$host"
else
  openssl req -x509 -sha256 -days 365 \
    -newkey rsa:2048 -nodes -keyout "$key_file" -out "$cert_file" \
    -subj "/CN=$host" -addext "subjectAltName=DNS:$host"
fi

chmod 0644 "$cert_file"

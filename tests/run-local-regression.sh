#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
regression_dir="$(mktemp -d "${TMPDIR:-/tmp}/assermetry-regression.XXXXXX")"
cleanup() {
  rm -rf -- "$regression_dir"
}
trap cleanup EXIT

python3 -m venv "$regression_dir/venv"
"$regression_dir/venv/bin/python" -m pip install --quiet --disable-pip-version-check \
  -r "$repository_root/tests/api/requirements.txt"
"$regression_dir/venv/bin/python" -m pip check

cd "$repository_root"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="api:tests" "$regression_dir/venv/bin/python" -m pytest tests/api -q \
  --ignore=tests/api/test_extraer_integration.py \
  --ignore=tests/api/test_ipfs_integration.py \
  --ignore=tests/api/test_news-chain_integration.py \
  --ignore=tests/api/test_validator_api.py \
  --ignore=tests/api/test_news-handler.py \
  --ignore=tests/api/test_quotas.py

node --check web_classic/app/js/app.js
node --check web_classic/app/js/i18n.js
node --test tests/frontend/unit/*.test.js

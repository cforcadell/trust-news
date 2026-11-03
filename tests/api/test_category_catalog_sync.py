import json
from pathlib import Path

from common.category_catalog import CATEGORY_CATALOG


def test_blockchain_category_seed_matches_backend_catalog():
    root = Path(__file__).resolve().parents[2]
    seed = json.loads((root / "smart-contracts/config/categories.json").read_text(encoding="utf-8"))
    assert {item["id"]: item["name"] for item in seed} == CATEGORY_CATALOG

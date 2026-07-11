from __future__ import annotations

from typing import Dict


# This catalog mirrors the category ids registered in TrustNews. Adding a new
# category requires registering it on-chain and adding its display label here.
CATEGORY_CATALOG: Dict[int, str] = {
    1: "ECONOMÍA",
    2: "DEPORTES",
    3: "POLÍTICA",
    4: "TECNOLOGÍA",
    5: "SALUD",
    6: "ENTRETENIMIENTO",
    7: "CIENCIA",
    8: "CULTURA",
    9: "MEDIO AMBIENTE",
    10: "SOCIAL",
}

CATEGORY_IDS = frozenset(CATEGORY_CATALOG)
CATEGORY_CATALOG_PROMPT = "\n".join(
    f"{category_id} {label}" for category_id, label in CATEGORY_CATALOG.items()
)


def validate_category_id(category_id: int) -> int:
    if category_id not in CATEGORY_IDS:
        accepted = ", ".join(str(item) for item in sorted(CATEGORY_IDS))
        raise ValueError(f"Invalid categoryId {category_id!r}. Accepted ids: {accepted}")
    return category_id


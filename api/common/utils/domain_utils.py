import re
from typing import Iterable, List, Optional


def normalize_domain(domain: str) -> str:
    value = (domain or "").strip().lower()
    value = re.sub(r"^https?://", "", value)
    return value.split("/")[0].removeprefix("www.")


def normalize_domains(domains: Optional[Iterable[str]]) -> List[str]:
    seen = set()
    normalized: List[str] = []
    for domain in domains or []:
        item = normalize_domain(str(domain))
        if item and item not in seen:
            seen.add(item)
            normalized.append(item)
    return normalized

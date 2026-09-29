from urllib.parse import urlsplit, urlunsplit


def normalize_domain(value: str) -> str:
    raw = str(value or "").strip().lower()
    if "://" in raw:
        raw = urlsplit(raw).hostname or ""
    else:
        raw = raw.split("/", 1)[0].split(":", 1)[0]
    return raw.removeprefix("www.").strip(".")


def normalize_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw if "://" in raw else f"https://{raw}")
    host = normalize_domain(parsed.hostname or "")
    if not host:
        return ""
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower() or "https", host, path, parsed.query, ""))

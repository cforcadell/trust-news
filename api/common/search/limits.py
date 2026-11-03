import os

from .errors import SearchConfigurationError


DEFAULT_PROVIDER_MAX_RESULTS = 50


def effective_max_results(requested: int) -> int:
    raw_limit = os.getenv("SEARCH_PROVIDER_MAX_RESULTS", str(DEFAULT_PROVIDER_MAX_RESULTS))
    try:
        provider_limit = int(raw_limit)
    except ValueError as exc:
        raise SearchConfigurationError("SEARCH_PROVIDER_MAX_RESULTS must be an integer") from exc
    if not 1 <= provider_limit <= 50:
        raise SearchConfigurationError("SEARCH_PROVIDER_MAX_RESULTS must be between 1 and 50")
    return min(requested, provider_limit)

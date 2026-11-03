class SearchError(RuntimeError):
    """Base error for shared search infrastructure."""


class SearchConfigurationError(SearchError):
    """The selected provider is unknown or lacks required configuration."""


class SearchProviderError(SearchError):
    """The upstream provider failed after the configured retry policy."""

    def __init__(self, provider: str, message: str, *, status_code: int | None = None):
        self.provider = provider
        self.status_code = status_code
        super().__init__(message)

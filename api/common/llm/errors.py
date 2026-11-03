class LLMError(RuntimeError):
    """Base error raised by shared LLM infrastructure."""


class LLMConfigurationError(LLMError):
    pass


class LLMProviderError(LLMError):
    def __init__(self, provider: str, message: str, *, status_code: int | None = None):
        self.provider = provider
        self.status_code = status_code
        super().__init__(message)


class LLMResponseError(LLMError):
    def __init__(self, message: str, *, response_content: str | None = None):
        # The response is kept in memory only so callers can derive sanitized
        # diagnostics. It must never be included in str(exc) or persisted raw.
        self.response_content = response_content
        super().__init__(message)

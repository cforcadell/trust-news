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
    pass

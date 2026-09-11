from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LLMRequest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    prompt: str
    model: str
    temperature: float = 0.1
    json_mode: bool = False
    response_schema: dict[str, Any] | None = None
    response_model: type[BaseModel] | None = Field(default=None, exclude=True)


class LLMUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class LLMResponse(BaseModel):
    content: str
    provider: str
    model: str
    usage: LLMUsage | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)

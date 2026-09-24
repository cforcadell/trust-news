from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LLMRequest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    prompt: str
    model: str
    temperature: float = 0.1
    json_mode: bool = False
    response_schema: dict[str, Any] | None = None
    response_model: type[BaseModel] | None = Field(default=None, exclude=True)
    strict_response_validation: bool = Field(default=True, exclude=True)

    @model_validator(mode="after")
    def configure_structured_output(self):
        """Use one Pydantic contract for provider and local validation.

        Callers normally only need to provide ``response_model``.  The schema is
        derived here so every provider receives the same contract.  Consumers
        that deliberately recover valid rows from a partially invalid batch may
        disable strict batch validation while retaining the provider schema.
        """
        if self.response_model is not None:
            generated_schema = self.response_model.model_json_schema()
            if self.response_schema is None:
                self.response_schema = generated_schema
            elif self.response_schema != generated_schema:
                raise ValueError("response_schema must match response_model")
        if self.response_schema is not None:
            self.json_mode = True
        return self


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

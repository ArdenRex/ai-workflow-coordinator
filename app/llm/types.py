"""Provider-neutral request/response types."""
import enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MessageRole(str, enum.Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class Message(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    role: MessageRole
    content: str

    @field_validator("content")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message content must not be blank")
        return v


class LLMRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    messages: List[Message] = Field(min_length=1)
    max_output_tokens: Optional[int] = Field(default=None, ge=1)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)   # deterministic by default
    json_mode: bool = False                                   # hint: provider should return JSON


class Usage(BaseModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class LLMResponse(BaseModel):
    text: str
    provider: str
    model: str
    finish_reason: str = "stop"           # stop | length | other
    usage: Usage = Field(default_factory=Usage)

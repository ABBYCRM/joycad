"""Provider-agnostic LLM types and the abstract client interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LLMRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class LLMMessage:
    role: LLMRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict] | None = None  # for assistant tool calls


@dataclass
class ToolSpec:
    """Function-call / tool-use declaration."""
    name: str
    description: str
    parameters: dict[str, Any]        # JSON-schema-style
    required: list[str] = field(default_factory=list)


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[dict] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    raw: Any = None
    provider: str = ""


class LLMClient(ABC):
    """Unified LLM client. Implement one per provider."""

    name: str = "abstract"

    @abstractmethod
    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: list[ToolSpec] | None = None,
        tool_choice: str | dict | None = "auto",
        json_mode: bool = False,
    ) -> LLMResponse: ...

    def __repr__(self) -> str:
        return f"<LLMClient provider={self.name}>"

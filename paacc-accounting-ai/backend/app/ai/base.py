from dataclasses import dataclass
from typing import Protocol


@dataclass
class Message:
    role: str  # system | user | assistant
    content: str


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str


class LLMProvider(Protocol):
    name: str

    def complete(self, messages: list[Message], **opts) -> LLMResponse: ...

from app.ai.base import LLMProvider, LLMResponse, Message


class EchoProvider:
    """Offline deterministic provider for dev/tests. Makes no network calls."""
    name = "echo"

    def complete(self, messages: list[Message], **opts) -> LLMResponse:
        last = next((m.content for m in reversed(messages) if m.role == "user"), "")
        return LLMResponse(text=f"echo: {last}", provider=self.name, model="echo-1")


class _NotConfigured:
    def __init__(self, name: str):
        self.name = name

    def complete(self, messages: list[Message], **opts) -> LLMResponse:
        raise NotImplementedError(f"provider '{self.name}' adapter is not implemented yet")


def get_provider(name: str) -> LLMProvider:
    if name == "echo":
        return EchoProvider()
    if name in {"anthropic", "openai", "local"}:
        return _NotConfigured(name)
    raise ValueError(f"unknown provider '{name}'")

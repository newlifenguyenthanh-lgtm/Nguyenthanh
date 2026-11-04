from dataclasses import dataclass

from app.ai.base import LLMProvider, Message


@dataclass(frozen=True)
class AgentSpec:
    key: str
    title: str
    tax_domain: bool  # tax agents stay disabled until rules are verified


AGENTS: dict[str, AgentSpec] = {a.key: a for a in [
    AgentSpec("general_accounting", "General accounting", False),
    AgentSpec("vat", "Value-added tax", True),
    AgentSpec("cit", "Corporate income tax", True),
    AgentSpec("pit", "Personal income tax", True),
    AgentSpec("construction", "Construction accounting", False),
    AgentSpec("contracts", "Contracts", False),
    AgentSpec("payments", "Payments", False),
    AgentSpec("finance", "Finance", False),
    AgentSpec("audit", "Audit", False),
]}


def run_agent(key: str, prompt: str, provider: LLMProvider) -> dict:
    spec = AGENTS[key]
    if spec.tax_domain:
        return {"agent": key, "status": "not_implemented",
                "detail": "Tax rules are not yet verified against official sources."}
    resp = provider.complete([
        Message("system", f"You are the PAACC {spec.title} assistant. Do not state tax rules you cannot cite."),
        Message("user", prompt),
    ])
    return {"agent": key, "status": "ok", "provider": resp.provider, "model": resp.model, "output": resp.text}

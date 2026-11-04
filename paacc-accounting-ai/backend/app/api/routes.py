from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agents.registry import AGENTS, run_agent
from app.ai.providers import get_provider
from app.config import get_settings
from app.domain.journal import JournalEntry

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/agents")
def list_agents() -> list[dict]:
    return [{"key": a.key, "title": a.title, "enabled": not a.tax_domain} for a in AGENTS.values()]


class AgentRequest(BaseModel):
    prompt: str
    provider: str | None = None


@router.post("/agents/{key}/run")
def run(key: str, req: AgentRequest) -> dict:
    if key not in AGENTS:
        raise HTTPException(404, "unknown agent")
    try:
        provider = get_provider(req.provider or get_settings().default_ai_provider)
        return run_agent(key, req.prompt, provider)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except NotImplementedError as e:
        raise HTTPException(501, str(e))


@router.post("/journal/validate")
def validate_journal(entry: JournalEntry) -> dict:
    return {"valid": True, "total": str(sum(l.debit for l in entry.lines))}

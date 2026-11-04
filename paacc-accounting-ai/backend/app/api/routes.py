from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.agents.registry import AGENTS, run_agent
from app.ai.providers import get_provider
from app.config import get_settings
from app.db import get_db
from app.deps import require
from app.domain.journal import JournalEntry
from app.models import User
from app.office.service import set_task_status, start_task
from sqlalchemy.orm import Session

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/agents")
def list_agents() -> list[dict]:
    return [{"key": a.key, "title": a.title, "title_vi": a.title_vi, "department": a.department,
             "enabled": not a.tax_domain} for a in AGENTS.values()]


class AgentRequest(BaseModel):
    prompt: str
    provider: str | None = None


@router.post("/agents/{key}/run")
def run(key: str, req: AgentRequest, user: User = Depends(require("ai_task:write")),
        db: Session = Depends(get_db)) -> dict:
    """Runs an agent and records a real ai_tasks row (running -> completed/error) for the virtual office."""
    if key not in AGENTS:
        raise HTTPException(404, "unknown agent")
    try:
        provider = get_provider(req.provider or get_settings().default_ai_provider)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if AGENTS[key].tax_domain:  # disabled: nothing runs, so no task is recorded
        return run_agent(key, req.prompt, provider)
    task = start_task(db, user, key, req.prompt[:120] or key)
    db.commit()
    try:
        result = run_agent(key, req.prompt, provider)
    except NotImplementedError as e:
        set_task_status(task, "error", error=str(e)); db.commit()
        raise HTTPException(501, str(e))
    if result["status"] == "ok":
        set_task_status(task, "completed", output=result["output"])
    else:
        set_task_status(task, "error", error=result.get("detail", result["status"]))
    db.commit()
    return {**result, "task_id": str(task.id)}


@router.post("/journal/validate")
def validate_journal(entry: JournalEntry) -> dict:
    return {"valid": True, "total": str(sum(l.debit for l in entry.lines))}

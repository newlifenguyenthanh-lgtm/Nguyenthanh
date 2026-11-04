"""Pure status derivation from real task records. No randomness, no animation state."""
import datetime as dt
from dataclasses import dataclass

STATUSES = ("idle", "working", "waiting_approval", "completed", "error")
PRIORITY = {"error": 4, "waiting_approval": 3, "working": 2, "completed": 1, "idle": 0}
TASK_STATUSES = ("queued", "running", "waiting_approval", "completed", "error", "cancelled")
TRANSITIONS = {
    "queued": {"running", "cancelled"},
    "running": {"completed", "error", "waiting_approval", "cancelled"},
    "waiting_approval": set(),  # leaves only via approve/reject endpoints
    "error": {"queued"},  # retry
    "completed": set(),
    "cancelled": set(),
}
RECENT = dt.timedelta(hours=24)


@dataclass(frozen=True)
class TaskView:
    status: str
    finished_at: dt.datetime | None
    created_at: dt.datetime


def utc(t: dt.datetime | None) -> dt.datetime | None:
    if t is None:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)  # SQLite returns naive UTC


def agent_status(tasks: list[TaskView], now: dt.datetime) -> str:
    finished = sorted((t for t in tasks if t.status in ("completed", "error")),
                      key=lambda t: utc(t.finished_at or t.created_at))
    if finished and finished[-1].status == "error":
        return "error"
    if any(t.status == "waiting_approval" for t in tasks):
        return "waiting_approval"
    if any(t.status in ("queued", "running") for t in tasks):
        return "working"
    if finished and now - utc(finished[-1].finished_at or finished[-1].created_at) <= RECENT:
        return "completed"
    return "idle"


def combine(statuses: list[str]) -> str:
    return max(statuses, key=PRIORITY.__getitem__, default="idle")


def can_transition(src: str, dst: str) -> bool:
    return dst in TRANSITIONS.get(src, set())

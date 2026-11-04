import datetime as dt

from app.office.catalog import DEFAULT_DEPARTMENTS
from app.office.status import TaskView, agent_status, can_transition, combine
from tests.conftest import B, login

NOW = dt.datetime(2026, 11, 4, 12, tzinfo=dt.timezone.utc)


def tv(status, hours_ago=1, finished=True):
    t = NOW - dt.timedelta(hours=hours_ago)
    return TaskView(status, t if finished and status in ("completed", "error") else None, t)


# ---------- pure status derivation ----------
def test_agent_status_rules():
    assert agent_status([], NOW) == "idle"
    assert agent_status([tv("running")], NOW) == "working"
    assert agent_status([tv("queued")], NOW) == "working"
    assert agent_status([tv("running"), tv("waiting_approval")], NOW) == "waiting_approval"
    assert agent_status([tv("completed", 2)], NOW) == "completed"
    assert agent_status([tv("completed", 30)], NOW) == "idle"  # older than 24 h
    assert agent_status([tv("error", 2)], NOW) == "error"
    assert agent_status([tv("error", 3), tv("completed", 1)], NOW) == "completed"  # later success clears error
    assert agent_status([tv("cancelled")], NOW) == "idle"


def test_combine_and_transitions():
    assert combine([]) == "idle"
    assert combine(["idle", "working", "completed"]) == "working"
    assert combine(["working", "waiting_approval"]) == "waiting_approval"
    assert combine(["waiting_approval", "error"]) == "error"
    assert can_transition("queued", "running") and can_transition("error", "queued")
    assert not can_transition("completed", "running") and not can_transition("waiting_approval", "completed")


# ---------- API ----------
def test_overview_seeds_ten_departments_with_layout_and_agents(env):
    v = login(env, "viewer@a.test", "pw-x")
    deps = env.get(f"{B}/office/overview", headers=v).json()["departments"]
    assert [d["code"] for d in deps] == [d[0] for d in DEFAULT_DEPARTMENTS] and len(deps) == 10
    assert all({"x", "z", "w", "d"} <= set(d["layout"]) for d in deps)
    assert all(d["status"] == "idle" for d in deps)
    agents = [a["key"] for d in deps for a in d["agents"]]
    assert len(agents) == len(set(agents)) == 18  # each agent in exactly one department
    cad = next(d for d in deps if d["code"] == "cad_design")
    assert cad["module"] == {"route": None, "status": "planned", "phase": 5}
    # idempotent seeding
    assert len(env.get(f"{B}/office/overview", headers=v).json()["departments"]) == 10


def test_agent_run_reflected_in_office(env):
    a = login(env, "admin@a.test", "pw-admin-1")
    env.post(f"{B}/agents/audit/run", json={"prompt": "kiểm tra"}, headers=a)
    d = env.get(f"{B}/office/departments/internal_audit", headers=a).json()
    assert d["status"] == "completed" and d["agents"][0]["status"] == "completed"
    assert d["recent_tasks"][0]["status"] == "completed" and d["task_counts"]["completed"] == 1
    env.post(f"{B}/agents/audit/run", json={"prompt": "x", "provider": "openai"}, headers=a)  # adapter missing -> error
    assert env.get(f"{B}/office/departments/internal_audit", headers=a).json()["status"] == "error"


def test_task_lifecycle_with_approval(env):
    a = login(env, "admin@a.test", "pw-admin-1")
    d = login(env, "director@a.test", "pw-x")
    t = env.post(f"{B}/ai-tasks", json={"agent_key": "quantity_surveyor", "title": "Bóc tách BV KC-01",
                                        "requires_approval": True}, headers=a).json()
    assert t["status"] == "queued" and t["department_code"] == "engineering_qs"
    dept = lambda: env.get(f"{B}/office/departments/engineering_qs", headers=a).json()
    assert dept()["status"] == "working"
    assert env.post(f"{B}/ai-tasks/{t['id']}/status", json={"status": "running"}, headers=a).status_code == 200
    assert dept()["agents"][1]["current_task"]["id"] == t["id"]
    # cannot skip approval
    assert env.post(f"{B}/ai-tasks/{t['id']}/status", json={"status": "completed"}, headers=a).status_code == 409
    env.post(f"{B}/ai-tasks/{t['id']}/status", json={"status": "waiting_approval"}, headers=a)
    assert dept()["status"] == "waiting_approval"
    board = env.get(f"{B}/office/departments/board", headers=a).json()
    assert next(m for m in board["metrics"] if m["key"] == "pending_approvals")["value"] == "1"
    v = login(env, "viewer@a.test", "pw-x")
    assert env.post(f"{B}/ai-tasks/{t['id']}/approve", headers=v).status_code == 403
    assert env.post(f"{B}/ai-tasks/{t['id']}/approve", headers=d).json()["status"] == "completed"
    assert env.post(f"{B}/ai-tasks/{t['id']}/approve", headers=d).status_code == 409
    assert dept()["status"] == "completed"
    assert env.post(f"{B}/ai-tasks/{t['id']}/status", json={"status": "bogus"}, headers=a).status_code == 409


def test_business_approvals_and_metrics_are_real(env):
    a = login(env, "admin@a.test", "pw-admin-1")
    pid = env.post(f"{B}/projects", json={"code": "P1", "name": "x", "status": "active"}, headers=a).json()["id"]
    part = env.post(f"{B}/partners", json={"name": "CĐT", "kind": "customer"}, headers=a).json()["id"]
    cid = env.post(f"{B}/contracts", json={"project_id": pid, "partner_id": part, "number": "HD1",
                                           "direction": "outbound", "original_value": "1500000000"}, headers=a).json()["id"]
    env.post(f"{B}/contracts/{cid}/appendices", json={"number": "PL1", "delta_value": "1"}, headers=a)
    cp = env.get(f"{B}/office/departments/contract_payment", headers=a).json()
    m = {x["key"]: x["value"] for x in cp["metrics"]}
    assert cp["status"] == "waiting_approval" and cp["pending_business_approvals"] == 1
    assert m == {"contracts": "1", "outbound_original_value": "1500000000.00", "pending_appendices": "1"}
    env.post(f"{B}/documents", data={"title": "BV", "kind": "drawing"}, files={"file": ("a.pdf", b"x")}, headers=a)
    eng = env.get(f"{B}/office/departments/engineering_qs", headers=a).json()
    assert {x["key"]: x["value"] for x in eng["metrics"]}["drawing_docs"] == "1"
    assert eng["recent_documents"][0]["title"] == "BV"
    assert env.get(f"{B}/office/departments/accounting_finance", headers=a).json()["metrics"] == []  # module not built


def test_members_permissions_and_isolation(env):
    a = login(env, "admin@a.test", "pw-admin-1")
    b = login(env, "admin@b.test", "pw-admin-2")
    v = login(env, "viewer@a.test", "pw-x")
    me = env.get(f"{B}/auth/me", headers=v).json()
    assert env.post(f"{B}/office/departments/bidding/members", json={"user_id": me["id"]}, headers=v).status_code == 403
    assert env.post(f"{B}/office/departments/bidding/members", json={"user_id": me["id"]}, headers=b).status_code == 404
    assert env.post(f"{B}/office/departments/bidding/members", json={"user_id": me["id"], "job_title": "Chuyên viên"},
                    headers=a).status_code == 201
    assert env.post(f"{B}/office/departments/bidding/members", json={"user_id": me["id"]}, headers=a).status_code == 409
    emp = env.get(f"{B}/office/departments/bidding", headers=a).json()["employees"]
    assert emp[0]["job_title"] == "Chuyên viên"
    env.post(f"{B}/ai-tasks", json={"agent_key": "audit", "title": "x"}, headers=a)
    assert env.get(f"{B}/ai-tasks", headers=b).json() == []
    assert env.get(f"{B}/office/departments/internal_audit", headers=b).json()["status"] == "idle"
    assert env.get(f"{B}/office/departments/nope", headers=a).status_code == 404
    assert env.post(f"{B}/ai-tasks", json={"agent_key": "nope", "title": "x"}, headers=a).status_code == 422

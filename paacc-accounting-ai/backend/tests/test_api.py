from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import login

c = TestClient(app)
B = "/api/v1"


def test_health():
    assert c.get(f"{B}/health").json() == {"status": "ok"}


def test_agents_listed_tax_disabled():
    agents = {a["key"]: a for a in c.get(f"{B}/agents").json()}
    # 14 design agents + accounting/tax sub-agents; every agent belongs to a department
    assert len(agents) == 18 and all(a["department"] for a in agents.values())
    assert agents["vat"]["enabled"] is False and agents["audit"]["enabled"] is True


def test_agent_run_requires_login(env):
    assert env.post(f"{B}/agents/audit/run", json={"prompt": "x"}).status_code == 401


def test_tax_agent_not_implemented(env):
    a = login(env, "admin@a.test", "pw-admin-1")
    r = env.post(f"{B}/agents/vat/run", json={"prompt": "x"}, headers=a).json()
    assert r["status"] == "not_implemented" and "task_id" not in r


def test_general_agent_echo(env):
    a = login(env, "admin@a.test", "pw-admin-1")
    r = env.post(f"{B}/agents/general_accounting/run", json={"prompt": "hello"}, headers=a).json()
    assert r["status"] == "ok" and r["output"] == "echo: hello" and r["task_id"]


def test_unknown_agent_and_provider(env):
    a = login(env, "admin@a.test", "pw-admin-1")
    assert env.post(f"{B}/agents/nope/run", json={"prompt": "x"}, headers=a).status_code == 404
    assert env.post(f"{B}/agents/audit/run", json={"prompt": "x", "provider": "zzz"}, headers=a).status_code == 400
    assert env.post(f"{B}/agents/audit/run", json={"prompt": "x", "provider": "openai"}, headers=a).status_code == 501


def test_journal_balanced():
    body = {"lines": [{"account_code": "A", "debit": "100"}, {"account_code": "B", "credit": "100"}]}
    r = c.post(f"{B}/journal/validate", json=body)
    assert r.status_code == 200 and r.json()["valid"] is True


def test_journal_unbalanced_rejected():
    body = {"lines": [{"account_code": "A", "debit": "100"}, {"account_code": "B", "credit": "90"}]}
    assert c.post(f"{B}/journal/validate", json=body).status_code == 422


def test_journal_line_both_sides_rejected():
    body = {"lines": [{"account_code": "A", "debit": "1", "credit": "1"}, {"account_code": "B", "credit": "1"}]}
    assert c.post(f"{B}/journal/validate", json=body).status_code == 422

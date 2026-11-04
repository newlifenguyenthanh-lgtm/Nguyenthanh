from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)
B = "/api/v1"


def test_health():
    assert c.get(f"{B}/health").json() == {"status": "ok"}


def test_agents_listed_tax_disabled():
    agents = {a["key"]: a for a in c.get(f"{B}/agents").json()}
    assert len(agents) == 9
    assert agents["vat"]["enabled"] is False and agents["audit"]["enabled"] is True


def test_tax_agent_not_implemented():
    r = c.post(f"{B}/agents/vat/run", json={"prompt": "x"}).json()
    assert r["status"] == "not_implemented"


def test_general_agent_echo():
    r = c.post(f"{B}/agents/general_accounting/run", json={"prompt": "hello"}).json()
    assert r["status"] == "ok" and r["output"] == "echo: hello"


def test_unknown_agent_and_provider():
    assert c.post(f"{B}/agents/nope/run", json={"prompt": "x"}).status_code == 404
    assert c.post(f"{B}/agents/audit/run", json={"prompt": "x", "provider": "zzz"}).status_code == 400
    assert c.post(f"{B}/agents/audit/run", json={"prompt": "x", "provider": "openai"}).status_code == 501


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

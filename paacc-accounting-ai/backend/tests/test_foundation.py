from tests.conftest import B, login


def test_login_and_rbac(env):
    assert env.post(f"{B}/auth/login", json={"email": "admin@a.test", "password": "bad"}).status_code == 401
    assert env.get(f"{B}/projects").status_code == 401
    v = login(env, "viewer@a.test", "pw-x")
    assert env.get(f"{B}/projects", headers=v).status_code == 200
    assert env.post(f"{B}/projects", json={"code": "P1", "name": "x"}, headers=v).status_code == 403


def test_project_crud_filter_and_tenant_isolation(env):
    a = login(env, "admin@a.test", "pw-admin-1")
    b = login(env, "admin@b.test", "pw-admin-2")
    r = env.post(f"{B}/projects", json={"code": "P1", "name": "Cầu Bình"}, headers=a)
    assert r.status_code == 201
    pid = r.json()["id"]
    assert env.post(f"{B}/projects", json={"code": "P1", "name": "dup"}, headers=a).status_code == 409
    assert len(env.get(f"{B}/projects?q=P1", headers=a).json()) == 1
    assert env.get(f"{B}/projects", headers=b).json() == []
    assert env.patch(f"{B}/projects/{pid}", json={"status": "active"}, headers=b).status_code == 404
    assert env.patch(f"{B}/projects/{pid}", json={"status": "active"}, headers=a).json()["status"] == "active"


def _setup_contract(env, a, value="1000000000"):
    pid = env.post(f"{B}/projects", json={"code": "P1", "name": "x"}, headers=a).json()["id"]
    part = env.post(f"{B}/partners", json={"name": "CĐT", "kind": "customer"}, headers=a).json()["id"]
    c = env.post(f"{B}/contracts", json={"project_id": pid, "partner_id": part, "number": "HD01",
                                         "direction": "outbound", "original_value": value}, headers=a)
    assert c.status_code == 201, c.text
    return c.json()["id"]


def test_appendix_requires_approval_to_change_value(env):
    a = login(env, "admin@a.test", "pw-admin-1")
    d = login(env, "director@a.test", "pw-x")
    cid = _setup_contract(env, a)
    up = env.post(f"{B}/contracts/{cid}/appendices", json={"number": "PL1", "delta_value": "200000000"}, headers=a).json()
    down = env.post(f"{B}/contracts/{cid}/appendices", json={"number": "PL2", "delta_value": "-50000000"}, headers=a).json()
    s = env.get(f"{B}/contracts/{cid}/summary", headers=a).json()
    assert s["adjusted_value"] == "1000000000.00" and s["pending_appendices"] == 2
    viewer = login(env, "viewer@a.test", "pw-x")
    assert env.post(f"{B}/appendices/{up['id']}/approve", headers=viewer).status_code == 403
    assert env.post(f"{B}/appendices/{up['id']}/approve", headers=d).json()["status"] == "approved"
    assert env.post(f"{B}/appendices/{down['id']}/approve", headers=d).status_code == 200
    assert env.post(f"{B}/appendices/{down['id']}/approve", headers=d).status_code == 409
    s = env.get(f"{B}/contracts/{cid}/summary", headers=a).json()
    assert s["adjusted_value"] == "1150000000.00" and s["pending_appendices"] == 0


def test_rejected_appendix_excluded_and_audit_written(env):
    a = login(env, "admin@a.test", "pw-admin-1")
    cid = _setup_contract(env, a)
    ap = env.post(f"{B}/contracts/{cid}/appendices", json={"number": "PL1", "delta_value": "5"}, headers=a).json()
    env.post(f"{B}/appendices/{ap['id']}/reject", headers=a)
    assert env.get(f"{B}/contracts/{cid}/summary", headers=a).json()["adjusted_value"] == "1000000000.00"
    actions = [x["action"] for x in env.get(f"{B}/audit-logs", headers=a).json()]
    assert "reject" in actions and "create" in actions
    assert env.get(f"{B}/audit-logs", headers=login(env, "viewer@a.test", "pw-x")).status_code == 403


def test_contract_rejects_foreign_project(env):
    a = login(env, "admin@a.test", "pw-admin-1")
    b = login(env, "admin@b.test", "pw-admin-2")
    pid = env.post(f"{B}/projects", json={"code": "PB", "name": "b"}, headers=b).json()["id"]
    part = env.post(f"{B}/partners", json={"name": "x", "kind": "supplier"}, headers=a).json()["id"]
    r = env.post(f"{B}/contracts", json={"project_id": pid, "partner_id": part, "number": "N",
                                         "direction": "inbound", "original_value": "1"}, headers=a)
    assert r.status_code == 404

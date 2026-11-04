import hashlib

from tests.conftest import B, login


def up(env, h, content=b"%PDF-1.4 demo", name="ban ve.pdf", **extra):
    return env.post(f"{B}/documents", data={"title": "Bản vẽ A1", "kind": "drawing", **extra},
                    files={"file": (name, content, "application/pdf")}, headers=h)


def test_upload_hash_version_download(env):
    a = login(env, "admin@a.test", "pw-admin-1")
    r = up(env, a)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["version"]["sha256"] == hashlib.sha256(b"%PDF-1.4 demo").hexdigest() and d["current_version"] == 1
    r2 = env.post(f"{B}/documents/{d['id']}/versions", data={"note": "rev B"},
                  files={"file": ("ban ve.pdf", b"%PDF-1.4 revB", "application/pdf")}, headers=a)
    assert r2.json()["current_version"] == 2
    vs = env.get(f"{B}/documents/{d['id']}/versions", headers=a).json()
    assert [v["version_no"] for v in vs] == [1, 2]
    # original version stays byte-identical
    assert env.get(f"{B}/documents/{d['id']}/versions/1/download", headers=a).content == b"%PDF-1.4 demo"
    assert env.get(f"{B}/documents/{d['id']}/versions/2/download", headers=a).content == b"%PDF-1.4 revB"
    assert env.get(f"{B}/documents/{d['id']}/versions/9/download", headers=a).status_code == 404


def test_duplicate_detection_and_filename_sanitized(env):
    a = login(env, "admin@a.test", "pw-admin-1")
    first = up(env, a).json()
    second = up(env, a, name="../../etc/passwd").json()
    assert second["duplicate_of_document_id"] == first["id"]
    assert second["version"]["filename"] == "passwd"


def test_permissions_and_tenant_isolation(env):
    a = login(env, "admin@a.test", "pw-admin-1")
    b = login(env, "admin@b.test", "pw-admin-2")
    v = login(env, "viewer@a.test", "pw-x")
    did = up(env, a).json()["id"]
    assert up(env, v).status_code == 403
    assert env.get(f"{B}/documents", headers=v).status_code == 200
    assert env.get(f"{B}/documents", headers=b).json() == []
    assert env.get(f"{B}/documents/{did}/versions", headers=b).status_code == 404
    assert env.get(f"{B}/documents/{did}/versions/1/download", headers=b).status_code == 404


def test_validation(env):
    a = login(env, "admin@a.test", "pw-admin-1")
    assert up(env, a, content=b"").status_code == 422
    assert up(env, a, kind="zzz").status_code == 422
    assert up(env, a, project_id="00000000-0000-0000-0000-000000000000").status_code == 404
    pid = env.post(f"{B}/projects", json={"code": "P1", "name": "x"}, headers=a).json()["id"]
    up(env, a, project_id=pid)
    assert len(env.get(f"{B}/documents?project_id={pid}&kind=drawing", headers=a).json()) == 1

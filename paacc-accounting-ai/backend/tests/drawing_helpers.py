from app.pdf import service
from app.pdf.ocr import OcrLine
from tests.conftest import B


class FakeOcr:
    name = "fake-ocr"

    def __init__(self, lines=None):
        self.lines = lines if lines is not None else [
            OcrLine("BẢN VẼ SỐ: KC-02", 88.0, (2300, 1910, 2700, 1950)),
            OcrLine("TỶ LỆ: 1:50", 76.0, (2300, 2030, 2600, 2070)),
            OcrLine("THÉP HỘP 50x50x2 L=6000 SL=10", 47.0, (2000, 360, 2700, 400)),
        ]

    def recognize(self, png):
        return self.lines


def use_ocr(monkeypatch, engine):
    monkeypatch.setattr(service, "OCR_FACTORY", (lambda: engine) if engine else None)
    if engine is None:
        monkeypatch.setenv("PAACC_OCR_ENABLED", "false")


def upload(env, headers, data: bytes, title="Bản vẽ KC", project_id=None, name="kc.pdf"):
    form = {"title": title, "kind": "drawing", **({"project_id": project_id} if project_id else {})}
    r = env.post(f"{B}/documents", data=form, files={"file": (name, data, "application/pdf")}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def process(env, headers, doc_id, version_no=None):
    return env.post(f"{B}/drawings", json={"document_id": doc_id, **({"version_no": version_no} if version_no else {})},
                    headers=headers)

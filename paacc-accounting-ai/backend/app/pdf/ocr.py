"""OCR abstraction. The default engine is Tesseract (local, no data leaves the server)."""
import io
import shutil
from dataclasses import dataclass
from typing import Protocol


@dataclass
class OcrLine:
    text: str
    confidence: float  # 0-100 (Tesseract scale)
    bbox_px: tuple[float, float, float, float]


class OcrEngine(Protocol):
    name: str

    def recognize(self, png: bytes) -> list[OcrLine]: ...


class TesseractOcr:
    def __init__(self, langs: tuple[str, ...] = ("vie", "eng"), psm: int = 11):
        import pytesseract
        self._pt = pytesseract
        available = set(pytesseract.get_languages(config=""))
        chosen = [lang for lang in langs if lang in available] or ["eng"]
        self.lang = "+".join(chosen)
        self.psm = psm
        self.name = f"tesseract-{pytesseract.get_tesseract_version()}:{self.lang}:psm{psm}"

    @staticmethod
    def available() -> bool:
        return shutil.which("tesseract") is not None

    def recognize(self, png: bytes) -> list[OcrLine]:
        from PIL import Image
        img = Image.open(io.BytesIO(png))
        d = self._pt.image_to_data(img, lang=self.lang, config=f"--psm {self.psm}", output_type=self._pt.Output.DICT)
        groups: dict[tuple, list[int]] = {}
        for i, word in enumerate(d["text"]):
            if not word.strip() or float(d["conf"][i]) < 0:
                continue
            groups.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append(i)
        out = []
        for idx in groups.values():
            x0 = min(d["left"][i] for i in idx); y0 = min(d["top"][i] for i in idx)
            x1 = max(d["left"][i] + d["width"][i] for i in idx); y1 = max(d["top"][i] + d["height"][i] for i in idx)
            out.append(OcrLine(" ".join(d["text"][i] for i in idx),
                               sum(float(d["conf"][i]) for i in idx) / len(idx), (x0, y0, x1, y1)))
        return out


def default_ocr() -> OcrEngine | None:
    return TesseractOcr() if TesseractOcr.available() else None

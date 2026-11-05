"""Detection of legacy Vietnamese encodings in extracted text (Phase 5A.1). DETECTION ONLY.

CAD drawings and old spreadsheets often use 8-bit Vietnamese fonts (.VnTime = TCVN3/ABC, VNI-Times = VNI).
When such text is extracted it arrives as Latin-1-looking characters ("VÞ trÝ cöa ra - vµo"). Converting it
requires a verified code table; until one is validated on real samples nothing is converted - the original text
is always kept, and the result only says what the text probably is, with evidence and a confidence.
"""
import re
import unicodedata
from dataclasses import dataclass, field

# Latin-1 letters that ARE legal in Unicode Vietnamese (precomposed vowels with grave/acute/circumflex/tilde)
_VN_LATIN1 = set("àáâãèéêìíòóôõùúýÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÝ")
_VN_SPECIFIC = re.compile("[Ạ-ỹđĐăĂơƠưƯ]")
# characters that appear in TCVN3(ABC)-encoded text and never in Unicode Vietnamese nor typical VNI text
_TCVN3_STRONG = set("µ¸¶·¹¨©®ª«¬»¼½¾ÆÇËÌÎÏÞßåæçî§¦¡¢£¤¥")
# VNI writes a tone/shape mark as a separate 8-bit character AFTER the base vowel: aù aø aû aõ aï, and ñ = đ
# case-consistent: a lower-case vowel takes a lower-case mark, an upper-case vowel an upper-case mark
_VNI_PATTERN = re.compile(r"[aeiouy][ùøûõï]|[AEIOUY][ÙØÛÕÏ]|[ñÑ]|[aeo]ä|[AEO]Ä")
_UTF8_MOJIBAKE = re.compile(r"Ã[\u0080-¿]|Ä[\u0080-¿]|á[º»][\u0080-¿]|Æ[°¡]")


@dataclass
class EncodingGuess:
    encoding: str  # unicode | ascii | tcvn3 | vni | utf8_mojibake | garbled_unknown
    confidence: float
    evidence: list[str] = field(default_factory=list)

    @property
    def suspicious(self) -> bool:
        return self.encoding not in ("unicode", "ascii")

    def as_dict(self) -> dict:
        return {"encoding": self.encoding, "confidence": self.confidence, "evidence": self.evidence}


def detect(text: str) -> EncodingGuess:
    s = unicodedata.normalize("NFC", text or "")
    if not s.strip():
        return EncodingGuess("ascii", 1.0)
    moj = _UTF8_MOJIBAKE.findall(s)
    if moj:
        return EncodingGuess("utf8_mojibake", min(1.0, 0.6 + 0.1 * len(moj)), sorted(set(moj))[:8])
    odd = [c for c in s if "¡" <= c <= "ÿ" and c not in _VN_LATIN1 and c not in "×÷°±²³·"]
    if not odd:
        if _VN_SPECIFIC.search(s):
            return EncodingGuess("unicode", 1.0)
        return EncodingGuess("ascii" if s.isascii() else "unicode", 1.0)
    tcvn = [c for c in s if c in _TCVN3_STRONG]
    vni = _VNI_PATTERN.findall(s)
    letters = sum(1 for c in s if c.isalpha()) or 1
    if _VN_SPECIFIC.search(s) and len(odd) <= 1:
        return EncodingGuess("unicode", 0.7, sorted(set(odd)))  # real Unicode Vietnamese with a stray symbol
    if len(tcvn) > len(vni):
        conf = min(0.99, 0.5 + 0.5 * min(1.0, len(tcvn) / max(3, letters * 0.15)))
        return EncodingGuess("tcvn3", round(conf, 2), sorted(set(tcvn))[:10])
    if len(vni) > len(tcvn):
        conf = min(0.99, 0.5 + 0.5 * min(1.0, len(vni) / max(3, letters * 0.15)))
        return EncodingGuess("vni", round(conf, 2), sorted(set(vni))[:10])
    return EncodingGuess("garbled_unknown", 0.5, sorted(set(odd))[:10])

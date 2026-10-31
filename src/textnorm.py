"""Text normalization helpers (Vietnamese aware)."""
from __future__ import annotations

import re
import unicodedata

_PHONE_RE = re.compile(r"[\(\-–]?\s*\(?(?:\+?84|0)\d[\d\s\.\-]{7,13}\d\)?")
_WS_RE = re.compile(r"\s+")


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D")


def answer_norm(s: str) -> str:
    """Normalization used by the official string matcher.

    NFC, lowercase, every char that is not a letter/digit/space becomes a space,
    collapse whitespace. Vietnamese diacritics are kept.
    """
    s = nfc(str(s)).lower()
    s = "".join(c if (c.isalnum() or c.isspace()) else " " for c in s)
    return _WS_RE.sub(" ", s).strip()


def key_norm(s: str) -> str:
    """Loose key: answer_norm + accents stripped. Used to merge spelling variants."""
    return strip_accents(answer_norm(s))


def remove_phone(s: str) -> str:
    return _WS_RE.sub(" ", _PHONE_RE.sub(" ", str(s))).strip(" -–()")


def col_norm(s: str) -> str:
    """Normalize a column header for dictionary lookup."""
    s = strip_accents(nfc(str(s)))
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)          # MaHoaDon -> Ma Hoa Don
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", s)     # SLQuyDoi -> SL Quy Doi
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return _WS_RE.sub(" ", s).strip()


def fix_mojibake(name: str) -> str:
    """File names extracted with the wrong code page (utf-8 bytes read as cp1258/cp1252)."""
    for enc in ("cp1258", "cp1252", "latin-1"):
        try:
            fixed = name.encode(enc).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if fixed != name:
            return nfc(fixed)
    return nfc(name)

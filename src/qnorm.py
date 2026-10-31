"""Question normalization: telex-typo repair and a no-accent view for matching."""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

from .textnorm import nfc, strip_accents

_VOWEL_MARKS = {"aa": "â", "aw": "ă", "ee": "ê", "oo": "ô", "ow": "ơ", "uw": "ư", "dd": "đ"}
_TONES = {"s": "́", "f": "̀", "r": "̉", "x": "̃", "j": "̣"}
_VOWELS = "aăâeêioôơuưy"


def _place_tone(syl: str, tone: str) -> str:
    """Put a combining tone mark on the right vowel of a syllable (modern style)."""
    s = syl
    idx = [i for i, c in enumerate(s) if c in _VOWELS]
    if not idx:
        return s
    # priority vowels with hats/horns
    for i in idx:
        if s[i] in "ăâêôơư":
            pos = i
            if s[i] == "ư" and i + 1 < len(s) and s[i + 1] == "ơ":
                pos = i + 1
            break
    else:
        vs = [i for i in idx]
        # 'qu' / 'gi' onset: u / i belongs to the consonant
        if s.startswith("qu") and 1 in vs:
            vs = [i for i in vs if i != 1]
        if s.startswith("gi") and 1 in vs and len(vs) > 1:
            vs = [i for i in vs if i != 1]
        if not vs:
            vs = idx
        ends_cons = s[-1] not in _VOWELS
        if len(vs) >= 2 and not ends_cons and vs[-1] == len(s) - 1:
            pos = vs[-2] if len(vs) == 2 else vs[1]
        elif len(vs) >= 2:
            pos = vs[1] if ends_cons else vs[-2]
        else:
            pos = vs[0]
    return unicodedata.normalize("NFC", s[: pos + 1] + _TONES[tone] + s[pos + 1:])


def telex_decode(tok: str) -> Optional[str]:
    """Decode one telex-typed lowercase token, e.g. 'dduwowcj' -> 'được'. None if not telex-looking."""
    t = tok
    if not re.fullmatch(r"[a-z]+", t):
        return None
    tone = None
    changed = False
    # tone letter may be at the end (most common) or right after the vowel cluster
    m = re.fullmatch(r"(.*?[aeiouyw].*?)([sfrxj])([a-z]*)", t)
    if t[-1] in _TONES and len(t) > 1:
        tone, t = t[-1], t[:-1]
    elif m and m.group(3) and m.group(3) in ("c", "ch", "m", "n", "ng", "nh", "p", "t"):
        tone, t = m.group(2), m.group(1) + m.group(3)
    s = t
    for a, b in (("uow", "ươ"), ("dd", "đ"), ("aa", "â"), ("aw", "ă"), ("ee", "ê"), ("oo", "ô"), ("ow", "ơ"), ("uw", "ư")):
        if a in s:
            s = s.replace(a, b)
            changed = True
    if "w" in s:
        s = s.replace("w", "ư")
        changed = True
    if tone:
        s = _place_tone(s, tone)
        changed = True
    return s if changed else None


class QuestionNormalizer:
    def __init__(self, vocab: Iterable[str] = ()):
        self.vocab: set[str] = set()
        self.add_vocab(vocab)

    def add_vocab(self, texts: Iterable[str]):
        for t in texts:
            if not t:
                continue
            for w in re.findall(r"[^\W\d_]+", nfc(str(t)).lower()):
                if any(ord(c) > 127 for c in w):
                    self.vocab.add(w)

    def fix_telex(self, q: str) -> str:
        out = []
        for tok in re.split(r"(\W+)", q):
            low = tok.lower()
            dec = telex_decode(low) if tok and tok.isascii() and tok.isalpha() and len(tok) >= 3 else None
            if dec and dec in self.vocab:
                out.append(dec if tok.islower() else dec.capitalize())
            else:
                out.append(tok)
        return "".join(out)

    def normalize(self, q: str) -> str:
        q = nfc(q).strip()
        q = self.fix_telex(q)
        return re.sub(r"\s+", " ", q)


def plain(q: str) -> str:
    """Lowercase, accent-free version for keyword rules."""
    return re.sub(r"\s+", " ", strip_accents(nfc(q)).lower()).strip()

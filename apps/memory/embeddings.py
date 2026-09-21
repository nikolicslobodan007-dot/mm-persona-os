"""Embedding sloj — zamenljiv. Canon §10.5, §21; Memory v0.1 §6.

Canon kaže da se model bira **posle F4 merenja**, na srpskom. Zato F4 ne
vezuje sistem ni za jednog provajdera: ovde postoji ruter i jedan lokalni
model bez mreže, a `memory_eval` meri svaki model na istom zlatnom skupu.
Kad se izabere pravi model, dodaje se provajder u `PROVIDERS` i menja
`EMBEDDING_MODEL` — kod koji pretražuje ne zna razliku.

`local-hash-v1` nije „pravi" semantički model. To je feature hashing nad
rečima i trigramima slova, sa svođenjem dijakritika (č→c, đ→dj). Prepoznaje
isti koren kroz padeže („logistika", „logistici", „logističke") i radi bez
ijednog spoljnog poziva — dovoljno za pilot i za testove, i daje donju
granicu sa kojom se pravi modeli porede.

Vektor je indeks za pronalaženje kandidata, nikad izvor istine (§4.1).
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections.abc import Callable

from django.conf import settings

LOCAL_MODEL = "local-hash-v1"
_FOLD = str.maketrans({"đ": "dj", "Đ": "dj"})
_WORD = re.compile(r"[a-z0-9]+")


def normalize(text: str) -> str:
    """Mala slova, bez dijakritika, jedan razmak. Osnova i za hash sadržaja."""
    text = text.translate(_FOLD)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(_WORD.findall(text.lower()))


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode()).hexdigest()


def _features(text: str) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for w in normalize(text).split():
        out.append((f"w:{w}", 1.0))
        padded = f"#{w}#"
        for i in range(len(padded) - 2):
            out.append((f"t:{padded[i:i + 3]}", 0.5))
    return out


def local_hash(text: str, dim: int) -> list[float]:
    v = [0.0] * dim
    for feat, weight in _features(text):
        h = hashlib.blake2b(feat.encode(), digest_size=8).digest()
        idx = int.from_bytes(h[:4], "big") % dim
        sign = 1.0 if h[4] & 1 else -1.0
        v[idx] += sign * weight
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


PROVIDERS: dict[str, Callable[[str, int], list[float]]] = {
    LOCAL_MODEL: local_hash,
}


def model_key() -> str:
    return getattr(settings, "EMBEDDING_MODEL", "") or LOCAL_MODEL


def embed(text: str, *, model: str | None = None) -> list[float]:
    key = model or model_key()
    if key not in PROVIDERS:
        raise LookupError(f"embedding model {key!r} nije registrovan (Canon §10.5)")
    return PROVIDERS[key](text, settings.EMBEDDING_DIM)


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))

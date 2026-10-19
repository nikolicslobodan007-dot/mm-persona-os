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


def stems(text: str) -> set[str]:
    """Koreni reči za grubo leksičko poklapanje: prvih pet slova, reči
    kraće od tri slova se preskaču.

    ADR-0101 — isti postupak koristi i pretraga memorije
    (`apps/memory/retrieval.py`) i izbor veština (`apps/memory/context.py`),
    pa stoji ovde jednom umesto dva puta.
    """
    return {w[:5] for w in normalize(text).split() if len(w) >= 3}


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


# ADR-0120 — semantički višejezični model za veštine, lokalno preko fastembed
# (ONNX). Model je pečen u imidž pa radi offline; uvozi se lenjo i drži kao
# singleton jer je učitavanje skupo a poziv čest. Memorijski `embed` (gore)
# ostaje netaknut: veštine imaju svoj model i svoju dimenziju.
_FASTEMBED_NAME = {
    "minilm-l12-v2": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
}
_fastembed_cache: dict[str, object] = {}


def _fastembed(key: str):
    if key not in _fastembed_cache:
        from fastembed import TextEmbedding

        kesh = getattr(settings, "FASTEMBED_CACHE", "") or None
        _fastembed_cache[key] = TextEmbedding(
            _FASTEMBED_NAME[key], cache_dir=kesh)
    return _fastembed_cache[key]


def vestina_model_key() -> str:
    return getattr(settings, "VESTINA_EMBEDDING_MODEL", "minilm-l12-v2")


def embed_vestina(text: str, *, model: str | None = None) -> list[float]:
    """Vektor veštine semantičkim modelom (ADR-0120).

    Model je simetričan (paraphrase-multilingual): upit i veština se kodiraju
    isto, bez prefiksa. Tekst ide sirov (model sam vodi računa o velikim
    slovima i dijakritici) — NE kroz `normalize`, koji je za hash-model.
    """
    key = model or vestina_model_key()
    vec = next(iter(_fastembed(key).embed([text])))
    return [float(x) for x in vec]

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
# Bez rezervnog spiska: ako instalacija zavisnosti ne uspe, build mora da padne
# glasno, a ne da tiho napravi image bez polovine paketa.
RUN pip install -e ".[dev]"

# ADR-0082 — Aider u svom kavezu. NE u okruzenje aplikacije: on nosi 107
# zavisnosti, a sa nasima mu se poklapaju dve (`pyyaml`, `jsonschema`). U
# sopstvenom venv-u sme da ima koji god `pydantic` hoce, a Django ostaje
# netaknut; uklanjanje je brisanje jednog direktorijuma. Verzija je zakucana:
# alat koji pise nas kod ne sme da se menja sam izmedju dva pecenja slike.
RUN python -m venv /opt/aider \
 && /opt/aider/bin/pip install --no-cache-dir aider-chat==0.86.2

COPY . .

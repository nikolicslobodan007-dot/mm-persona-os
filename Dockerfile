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

COPY . .

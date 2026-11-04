FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    FASTEMBED_CACHE=/opt/fastembed-cache

WORKDIR /app

# ADR-0087 — `git` je ovde zato sto zakrpu pravi on. Izvestaj pokretaca
# (ADR-0086) nosi tokene i cenu, ali ne i izmenjene fajlove; razliku izmedju
# radnog primerka i polazista racuna `git diff`. Svoj differ ne pisemo.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev git \
 ffmpeg tesseract-ocr \
 && rm -rf /var/lib/apt/lists/*

# ADR-0126 — srpski OCR modeli (latinica + ćirilica). apt `tesseract-ocr-srp`
# ne nosi uvek `srp_latn`, a memeovi su latinica; zato ih povlačimo direktno u
# tessdata. Build ima otvoren internet; padne li preuzimanje, build pada glasno.
RUN python -c "import urllib.request, glob, os; d=os.path.dirname(glob.glob('/usr/share/tesseract-ocr/*/tessdata/eng.traineddata')[0]); [urllib.request.urlretrieve('https://raw.githubusercontent.com/tesseract-ocr/tessdata/main/'+l+'.traineddata', os.path.join(d, l+'.traineddata')) for l in ('srp','srp_latn')]"

# ADR-0128 — Deno za yt-dlp n-challenge (YouTube). Bez JS runtime-a yt-dlp ne
# reši n-zagonetku pa YouTube vrati samo storyboard sličice, bez audija.
# Solver skripte yt-dlp povuče sam u radu (mreža je dozvoljena).
RUN python -c "import urllib.request,zipfile,io,os; z=urllib.request.urlopen('https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip').read(); zipfile.ZipFile(io.BytesIO(z)).extractall('/usr/local/bin'); os.chmod('/usr/local/bin/deno', 0o755)"

COPY pyproject.toml constraints.txt ./
# Bez rezervnog spiska: ako instalacija zavisnosti ne uspe, build mora da padne
# glasno, a ne da tiho napravi image bez polovine paketa.
# ADR-0083 — `-c constraints.txt`: instalira se tacno ono sto je izmereno
# zeleno. Bez toga svako pecenje slike razresava zavisnosti iznova i sme da
# povuce sta god je novo; tako je produkcija presla sa Django 5.2 na 6.1.2,
# a da to niko nije odlucio.
RUN pip install -e ".[dev]" -c constraints.txt

# ADR-0120 — pečemo višejezični model veština u sliku, u isti keš koji
# `FASTEMBED_CACHE` pokazuje, da pogon radi BEZ mreže (ADR-0009) i da
# prvi uvoz ne čeka preuzimanje. Build se radi na serveru (otvoren
# internet); ako preuzimanje padne, build mora da padne glasno, ne da
# tiho napravi sliku bez modela.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', cache_dir='/opt/fastembed-cache')"

# ADR-0082 — Aider u svom kavezu. NE u okruzenje aplikacije: on nosi 107
# zavisnosti, a sa nasima mu se poklapaju dve (`pyyaml`, `jsonschema`). U
# sopstvenom venv-u sme da ima koji god `pydantic` hoce, a Django ostaje
# netaknut; uklanjanje je brisanje jednog direktorijuma. Verzija je zakucana:
# alat koji pise nas kod ne sme da se menja sam izmedju dva pecenja slike.
RUN python -m venv /opt/aider \
 && /opt/aider/bin/pip install --no-cache-dir aider-chat==0.86.2

COPY . .

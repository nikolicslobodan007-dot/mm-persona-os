"""Lokalni Whisper (faster-whisper) — ASR bez spoljnog provajdera.

Groq je ograničen (ToS ban); lokalni Whisper radi bez naloga, bez troška i
nezavisno od tuđih ograničenja. Teške zavisnosti (ctranslate2/av/onnxruntime)
žive u izolovanom venv-u (/opt/whisper, kao aider — ADR-0082), pa app zove
podproces: glavni paketi i `constraints.txt` ostaju netaknuti. Model se peče u
sliku (/opt/whisper-models), jezik se auto-detektuje (rilsovi su i srpski i
engleski).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile

_VENV_PY = os.environ.get("WHISPER_PY", "/opt/whisper/bin/python")
_MODEL = os.environ.get("WHISPER_MODEL", "small")

_SKRIPTA = (
    "import json, sys\n"
    "from faster_whisper import WhisperModel\n"
    "m = WhisperModel(sys.argv[2], device='cpu', compute_type='int8', "
    "download_root='/opt/whisper-models')\n"
    "seg, _ = m.transcribe(sys.argv[1], language=(sys.argv[3] or None), vad_filter=True)\n"
    "print(json.dumps(' '.join(s.text.strip() for s in seg).strip()))\n"
)


def transkribuj(podaci: bytes, *, model: str = "", jezik: str | None = None) -> str:
    """Audio bajtovi → transkript. Podiže izuzetak ako podproces padne."""
    with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as fh:
        fh.write(podaci)
        put = fh.name
    try:
        r = subprocess.run(
            [_VENV_PY, "-c", _SKRIPTA, put, model or _MODEL, jezik or ""],
            capture_output=True, text=True, timeout=600, check=True)
    finally:
        os.unlink(put)
    return json.loads(r.stdout.strip() or '""')

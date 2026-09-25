"""Uvoz mašinske recenzije. ADR-0036.

Ulaz je **SARIF 2.1.0** (OASIS standard), ne sopstveni format nekog alata. Danas
ga daje `alibaba/open-code-review` (`ocr review --format sarif`), sutra sme bilo
šta što ume SARIF — uvoznik ostaje isti.

Tri stvari koje ovaj modul namerno radi drugačije nego što bi se očekivalo:

  - **mašina ne postavlja `BLOCKER`.** Preslikavanje je jedan stepen niže od onoga
    što alat tvrdi, jer model greši, a `BLOCKER` zaustavlja zadatak. Izvorna težina
    se čuva u tekstu nalaza — ništa se ne gubi.
  - **nalaz van dozvoljenih putanja zadatka se ne kači na zadatak**, nego se
    prebroji i prijavi. Zadatak ne odgovara za kod koji ne sme da dira.
  - **ono što nije SARIF se odbija.** Tiho uvezenih nula nalaza nema.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.db import transaction

from api import audit
from apps.personas.models import Persona
from apps.policy import service as policy
from common import enums as E

from .models import CodeTask, ReviewFinding
from .zadaci import TaskError, under_any

__all__ = ["import_sarif", "load_sarif", "SARIF_TO_SEVERITY"]

#: ADR-0036 §2 — namerno jedan stepen niže nego što alat tvrdi.
SARIF_TO_SEVERITY: dict[str, str] = {
    "error": E.FindingSeverity.MAJOR.value,
    "warning": E.FindingSeverity.MINOR.value,
    "note": E.FindingSeverity.NIT.value,
    "none": E.FindingSeverity.NIT.value,
    "": E.FindingSeverity.NIT.value,
}

_FINGERPRINT_KEYS = ("ocrFinding/v1",)


def load_sarif(path: str | Path) -> dict[str, Any]:
    """Učitava i proverava da je fajl zaista SARIF — inače greška, ne prazan uvoz."""
    p = Path(path)
    if not p.exists():
        raise TaskError("NO_REPORT", f"Nema fajla {p}.")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise TaskError("BAD_REPORT", f"{p} nije ispravan JSON: {e}") from e
    return _validate(data, str(p))


def _validate(data: Any, gde: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise TaskError("BAD_REPORT", f"{gde}: očekivan JSON objekat.")
    verzija = str(data.get("version", ""))
    if not verzija.startswith("2.1"):
        raise TaskError(
            "BAD_REPORT",
            f"{gde}: nije SARIF 2.1.x (version={verzija!r}). Uvoznik prima samo SARIF "
            f"— `ocr review --format sarif` (ADR-0036 §1).",
        )
    runs = data.get("runs")
    if not isinstance(runs, list):
        raise TaskError("BAD_REPORT", f"{gde}: `runs` nije lista.")
    for r in runs:
        if not isinstance(r, dict) or not isinstance(r.get("results", []), list):
            raise TaskError("BAD_REPORT", f"{gde}: `runs[].results` nije lista.")
    return data


def _tool_name(report: dict[str, Any]) -> str:
    for run in report.get("runs") or []:
        ime = (((run.get("tool") or {}).get("driver") or {}).get("name") or "").strip()
        if ime:
            return ime[:40]
    return "sarif"


def _location(res: dict[str, Any]) -> tuple[str, int | None]:
    for loc in res.get("locations") or []:
        fiz = (loc or {}).get("physicalLocation") or {}
        putanja = ((fiz.get("artifactLocation") or {}).get("uri") or "").strip()
        if not putanja:
            continue
        red = (fiz.get("region") or {}).get("startLine")
        return policy.normalize_path(putanja), int(red) if isinstance(red, int) else None
    return "", None


def _fingerprint(res: dict[str, Any]) -> str:
    otisci = res.get("partialFingerprints") or {}
    if not isinstance(otisci, dict):
        return ""
    for k in _FINGERPRINT_KEYS:
        if otisci.get(k):
            return str(otisci[k])[:120]
    for v in otisci.values():  # bilo koji otisak je bolji nego nijedan
        if v:
            return str(v)[:120]
    return ""


@transaction.atomic
def import_sarif(zadatak: CodeTask, report: dict[str, Any], *, source: str = "",
                 reviewer: Persona | None = None) -> dict[str, Any]:
    """Uvozi SARIF izveštaj u nalaze zadatka. Vraća prebrojano stanje.

    Ključevi u odgovoru:
      `uvezeno` — novi nalazi na ovom zadatku;
      `vec_postoji` — isti otisak je već uvezen (ponovljena recenzija);
      `van_zadatka` / `zasticena_zona` — putanje koje ovaj zadatak ne pokriva;
      `bez_putanje` / `bez_teksta` — nalaz bez lokacije ili bez tvrdnje;
      `bezbednost` — `security` nalazi najviše težine, za ljudsko oko.
    """
    report = _validate(report, "izveštaj")
    izvor = (source or _tool_name(report))[:40]
    if reviewer and zadatak.assignee_id and reviewer.pk == zadatak.assignee_id:
        raise TaskError("SELF_REVIEW", "Autor ne uvozi recenziju sopstvenog rada "
                                       "(ADR-0034 §5.2).")

    stanje: dict[str, Any] = {
        "uvezeno": 0, "vec_postoji": 0, "van_zadatka": [], "zasticena_zona": [],
        "bez_putanje": 0, "bez_teksta": 0, "bezbednost": 0, "izvor": izvor,
    }
    postojeci = set(
        zadatak.findings.exclude(fingerprint="").values_list("fingerprint", flat=True)
    )

    for run in report.get("runs") or []:
        for res in run.get("results") or []:
            if not isinstance(res, dict):
                continue
            nivo = str(res.get("level") or "").lower()
            kategorija = str(res.get("ruleId") or "")[:40]
            tekst = str((res.get("message") or {}).get("text") or "").strip()
            putanja, red = _location(res)

            if nivo == "error" and kategorija == "security":
                stanje["bezbednost"] += 1

            if not putanja:
                stanje["bez_putanje"] += 1
                continue
            zona = policy.path_is_protected(putanja)
            if zona:
                stanje["zasticena_zona"].append(putanja)
                continue
            if not under_any(putanja, zadatak.allowed_paths):
                stanje["van_zadatka"].append(putanja)
                continue
            if not tekst:
                stanje["bez_teksta"] += 1
                continue

            otisak = _fingerprint(res)
            if otisak and otisak in postojeci:
                stanje["vec_postoji"] += 1
                continue

            ReviewFinding.objects.create(
                task=zadatak, reviewer=reviewer, file=putanja, line=red,
                claim=f"[{kategorija or 'other'}/{nivo or 'note'}] {tekst}"[:8000],
                severity=SARIF_TO_SEVERITY.get(nivo, E.FindingSeverity.NIT.value),
                status=E.FindingStatus.OPEN, source=izvor,
                fingerprint=otisak, category=kategorija,
            )
            if otisak:
                postojeci.add(otisak)
            stanje["uvezeno"] += 1

    audit.record(
        "task.review.imported",
        severity=E.AuditSeverity.WARNING if stanje["bezbednost"] else E.AuditSeverity.INFO,
        persona=zadatak.assignee,
        details={
            "task": zadatak.public_id, "source": izvor,
            "imported": stanje["uvezeno"], "duplicates": stanje["vec_postoji"],
            "outside_task": sorted(set(stanje["van_zadatka"])),
            "protected_zone": sorted(set(stanje["zasticena_zona"])),
            "without_path": stanje["bez_putanje"], "without_text": stanje["bez_teksta"],
            "security": stanje["bezbednost"],
        },
    )
    return stanje

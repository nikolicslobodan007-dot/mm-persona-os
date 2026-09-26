"""Zakrpa kao kapija. ADR-0038.

Agent ne piše fajlove — agent predaje `unified diff`. Sistem ga čita, proverava i
tek onda primenjuje. Provera koju je moguće zaboraviti nije kapija, pa ovde nema
puta kojim izmena stiže do fajl-sistema mimo `may_touch`.

Četiri zamke koje naivno čitanje zakrpe propušta, i koje su zato zatvorene ovde:

  - **preimenovanje** nosi dve putanje; ko proverava samo novu, propušta izmenu u
    `apps/policy` izvedenu tako što se fajl prvo preimenuje;
  - **`..` i apsolutna putanja** — `git apply` ume da piše van radnog direktorijuma;
  - **mod `120000`** pravi simbolički link, posle kog obična putanja pokazuje gde
    hoće i sve provere putanja postaju bezvredne;
  - **putanja u navodnicima** (`"a/fajl\\ts imenom"`) se prvo dekodira pa proverava —
    ime fajla ne sme da bude način da se provera preskoči.

Binarna zakrpa se odbija: blob koji niko ne može da pročita se ne recenzira.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from django.db import transaction

from api import audit
from apps.personas.models import Persona
from apps.policy import service as policy
from common import enums as E

from .models import CodeTask, TaskPatch
from .zadaci import TaskError, may_touch

__all__ = ["Izmena", "Nalaz", "paths_in", "check", "submit", "zabelezi_neuspeh",
           "MAX_DIFF_BYTES"]

#: Gornja granica veličine zakrpe. Zakrpa preko ove mere nije izmena nego prepis,
#: i traži da se zadatak podeli.
MAX_DIFF_BYTES = 1_000_000

_SYMLINK_MODE = "120000"
_NULL = "/dev/null"

#: Putanja u `diff --git` redu je ili u navodnicima (i tada sme da sadrži razmak),
#: ili bez njih. Naivno `(.+?) (.+)` seče na prvom razmaku — pa i unutar navodnika.
_PUT = r'(?:"(?:\\.|[^"\\])*"|\S+)'
_DIFF_GIT = re.compile(rf"^diff --git (?P<a>{_PUT}) (?P<b>{_PUT})$")
_MODE = re.compile(r"^(?:new file mode|deleted file mode|old mode|new mode) (?P<mode>\d{6})\s*$")
_RENAME = re.compile(r"^rename (?:from|to) (?P<put>.+)$")
_MINUS = re.compile(r"^--- (?P<put>.+)$")
_PLUS = re.compile(r"^\+\+\+ (?P<put>.+)$")

#: C-escape sekvence iz `git` citiranja putanja.
_ESC = {"a": 7, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9, "v": 11,
        "\\": 92, '"': 34}


class PatchError(TaskError):
    """Zakrpa se ne može ni pročitati — ne dolazi ni do provere putanja."""


@dataclass(frozen=True)
class Izmena:
    """Jedna putanja koju zakrpa dira."""

    path: str
    kind: str = "izmena"          # izmena · nova · brisanje · preimenovanje


@dataclass
class Nalaz:
    """Ishod provere: šta zakrpa dira i zašto sme ili ne sme."""

    izmene: list[Izmena] = field(default_factory=list)
    odbijeno: list[tuple[str, str]] = field(default_factory=list)   # (putanja, razlog)
    greske: list[str] = field(default_factory=list)                 # zakrpa kao celina

    @property
    def ok(self) -> bool:
        return not self.odbijeno and not self.greske and bool(self.izmene)

    @property
    def putanje(self) -> list[str]:
        return sorted({i.path for i in self.izmene})


# ---------------------------------------------------------------- čitanje zakrpe


def _unquote(raw: str) -> str:
    """Dekodira putanju u navodnicima onako kako je `git` piše.

    Neuspelo dekodiranje je greška, ne razlog da se nastavi sa sirovim tekstom:
    putanja koju ne umemo da pročitamo ne sme da se proverava napamet.
    """
    if not (raw.startswith('"') and raw.endswith('"') and len(raw) >= 2):
        return raw
    telo, out, i = raw[1:-1], bytearray(), 0
    while i < len(telo):
        z = telo[i]
        if z != "\\":
            out.extend(z.encode("utf-8"))
            i += 1
            continue
        i += 1
        if i >= len(telo):
            raise PatchError("BAD_PATH", f"Nedovršen znak u putanji {raw!r}.")
        n = telo[i]
        if n in _ESC:
            out.append(_ESC[n])
            i += 1
        elif n.isdigit() and len(telo) >= i + 3:
            try:
                out.append(int(telo[i:i + 3], 8))
            except ValueError as e:
                raise PatchError("BAD_PATH", f"Loš oktalni znak u {raw!r}.") from e
            i += 3
        else:
            raise PatchError("BAD_PATH", f"Nepoznat znak `\\{n}` u putanji {raw!r}.")
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError as e:
        raise PatchError("BAD_PATH", f"Putanja {raw!r} nije ispravan UTF-8.") from e


def _strip_prefix(put: str) -> str:
    """Skida `a/` ili `b/` koje `git diff` podrazumevano dodaje."""
    return put[2:] if put[:2] in ("a/", "b/") else put


def _clean(raw: str) -> str | None:
    """Putanja spremna za proveru, ili `None` za `/dev/null`."""
    put = _unquote(raw.strip().split("\t")[0])
    if put == _NULL:
        return None
    put = _strip_prefix(put)
    norm = policy.normalize_path(put)
    if not norm:
        raise PatchError("BAD_PATH", "Prazna putanja u zakrpi.")
    if put.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", put):
        raise PatchError("ABSOLUTE_PATH", f"Apsolutna putanja u zakrpi: {put!r}.")
    if ".." in norm.split("/"):
        raise PatchError("PATH_ESCAPE",
                         f"Putanja {put!r} izlazi iz radnog direktorijuma.")
    return norm


def paths_in(diff: str) -> list[Izmena]:
    """Sve putanje koje zakrpa dira, sa vrstom izmene.

    Kod preimenovanja se vraćaju **obe** putanja — i stara i nova.
    """
    if not diff.strip():
        raise PatchError("EMPTY_PATCH", "Prazna zakrpa.")
    if len(diff.encode("utf-8")) > MAX_DIFF_BYTES:
        raise PatchError("PATCH_TOO_BIG",
                         f"Zakrpa je preko {MAX_DIFF_BYTES} bajtova — to nije izmena "
                         "nego prepis; podeli zadatak.")

    nadjene: dict[str, str] = {}
    vidi_novi = vidi_brisanje = vidi_preimenovanje = False

    def zapamti(put: str | None, vrsta: str) -> None:
        if put is None:
            return
        # jača vrsta pobeđuje: preimenovanje > nova/brisanje > izmena
        red = {"izmena": 0, "nova": 1, "brisanje": 1, "preimenovanje": 2}
        if put not in nadjene or red[vrsta] > red[nadjene[put]]:
            nadjene[put] = vrsta

    for red in diff.splitlines():
        if red.startswith("GIT binary patch") or red.startswith("Binary files "):
            raise PatchError("BINARY_PATCH",
                             "Binarna zakrpa se ne prima — što se ne može pročitati, "
                             "ne može se ni recenzirati.")
        if (m := _MODE.match(red)):
            if m.group("mode") == _SYMLINK_MODE:
                raise PatchError(
                    "SYMLINK",
                    "Zakrpa pravi ili menja simbolički link (mod 120000). Posle njega "
                    "obična putanja pokazuje gde hoće, pa provere putanja ne važe.")
            if red.startswith("new file mode"):
                vidi_novi = True
            elif red.startswith("deleted file mode"):
                vidi_brisanje = True
            continue
        if (m := _RENAME.match(red)):
            vidi_preimenovanje = True
            zapamti(_clean(m.group("put")), "preimenovanje")
            continue
        if (m := _DIFF_GIT.match(red)):
            vidi_novi = vidi_brisanje = vidi_preimenovanje = False
            for kljuc in ("a", "b"):
                zapamti(_clean(m.group(kljuc)), "izmena")
            continue
        if (m := _MINUS.match(red)):
            vrsta = "brisanje" if vidi_brisanje else (
                "preimenovanje" if vidi_preimenovanje else "izmena")
            zapamti(_clean(m.group("put")), vrsta)
            continue
        if (m := _PLUS.match(red)):
            vrsta = "nova" if vidi_novi else (
                "preimenovanje" if vidi_preimenovanje else "izmena")
            zapamti(_clean(m.group("put")), vrsta)
            continue

    if not nadjene:
        raise PatchError("NO_PATHS",
                         "Zakrpa ne dira nijednu putanju — nije unified diff.")
    return [Izmena(p, nadjene[p]) for p in sorted(nadjene)]


# ---------------------------------------------------------------------- provera


def check(zadatak: CodeTask, diff: str, *, persona: Persona | None = None) -> Nalaz:
    """Da li zakrpa sme da se primeni na ovaj zadatak.

    Svaka putanja — i stara i nova kod preimenovanja — prolazi `may_touch`.
    """
    nalaz = Nalaz()
    try:
        nalaz.izmene = paths_in(diff)
    except PatchError as e:
        nalaz.greske.append(f"{e.code}: {e}")
        return nalaz

    for izmena in nalaz.izmene:
        razlog = may_touch(zadatak, izmena.path, persona=persona)
        if razlog:
            nalaz.odbijeno.append((izmena.path, razlog))
    return nalaz


@transaction.atomic
def submit(zadatak: CodeTask, diff: str, *, persona: Persona | None = None,
           base_sha: str = "", cena_centi: int = 0) -> TaskPatch:
    """Upisuje zakrpu i njen ishod. Odbijena zakrpa se **takođe** pamti.

    Odbijena zakrpa je podatak: po njoj se vidi da li agent stalno pokušava izvan
    svog dela koda, a to je merenje koje ADR-0034 §6 traži.
    """
    nalaz = check(zadatak, diff, persona=persona)
    red = TaskPatch.objects.create(
        task=zadatak, author=persona, base_sha=base_sha, diff=diff,
        paths=nalaz.putanje, cost_eur_cents=max(0, int(cena_centi)),
        status=E.PatchStatus.ACCEPTED if nalaz.ok else E.PatchStatus.REJECTED,
        reason="; ".join(nalaz.greske + [f"{p}: {r}" for p, r in nalaz.odbijeno])[:2000],
    )
    audit.record(
        "task.patch.submitted",
        severity=E.AuditSeverity.INFO if nalaz.ok else E.AuditSeverity.WARNING,
        persona=persona or zadatak.assignee,
        details={"task": zadatak.public_id, "status": red.status,
                 "paths": nalaz.putanje, "reason": red.reason,
                 "base": base_sha, "cena_centi": red.cost_eur_cents},
    )
    return red


@transaction.atomic
def zabelezi_neuspeh(zadatak: CodeTask, *, persona: Persona | None, tekst: str,
                     razlog: str, cena_centi: int = 0) -> TaskPatch:
    """Pokušaj koji nije ni stigao do zakrpe — model nije vratio upotrebljiv diff.

    Upisuje se kao odbijena zakrpa iz dva razloga, i oba su o poštenju brojeva
    (ADR-0044): poziv je **plaćen**, pa trošak mora negde da stoji; i pokušaj se
    **desio**, pa mora da se broji u plafon pokušaja. Prećutan neuspeh bi značio
    besplatan i beskonačan krug.
    """
    red = TaskPatch.objects.create(
        task=zadatak, author=persona, diff=tekst[:20_000], paths=[],
        status=E.PatchStatus.REJECTED, reason=razlog[:2000],
        cost_eur_cents=max(0, int(cena_centi)),
    )
    audit.record("task.patch.submitted", severity=E.AuditSeverity.WARNING,
                 persona=persona or zadatak.assignee,
                 details={"task": zadatak.public_id, "status": red.status,
                          "paths": [], "reason": red.reason,
                          "cena_centi": red.cost_eur_cents})
    return red

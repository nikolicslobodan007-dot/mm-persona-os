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

__all__ = ["Izmena", "Ispravka", "Nalaz", "paths_in", "prebroj_hunkove", "check",
           "submit", "zabelezi_neuspeh", "odbij_posle_provere", "pripisi_krivicu",
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

#: Zaglavlje hunka: `@@ -stara,koliko +nova,koliko @@ [naslov]`. Broj posle zareza
#: sme da izostane i tada je 1. Rep iza drugog `@@` je oznaka odeljka koju `git`
#: dodaje radi čitljivosti — prenosi se netaknut.
_HUNK = re.compile(
    r"^@@ -(?P<sp>\d+)(?:,(?P<sk>\d+))? \+(?P<np>\d+)(?:,(?P<nk>\d+))? @@(?P<rep>.*)$")

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


@dataclass(frozen=True)
class Ispravka:
    """Jedno `@@` zaglavlje čije smo brojeve prebrojali umesto pisca. ADR-0052."""

    red: int                       # redni broj reda sa `@@`, od 1
    pre: tuple[int, int]           # šta je pisalo: (staro, novo)
    posle: tuple[int, int]         # šta je izbrojano

    def __str__(self) -> str:
        return (f"red {self.red}: -{self.pre[0]} +{self.pre[1]} → "
                f"-{self.posle[0]} +{self.posle[1]}")


@dataclass
class Nalaz:
    """Ishod provere: šta zakrpa dira i zašto sme ili ne sme."""

    izmene: list[Izmena] = field(default_factory=list)
    odbijeno: list[tuple[str, str]] = field(default_factory=list)   # (putanja, razlog)
    #: Zaglavlja hunkova koja smo prebrojali (ADR-0052). Ne obara zakrpu, ali se
    #: **uvek** vidi: ide u `reason` i pred recenzenta.
    ispravke: list[Ispravka] = field(default_factory=list)
    #: Zakrpa sa ispravljenim zaglavljima — ona koja se čuva i primenjuje.
    diff: str = ""
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


def _nov_fajl(redovi: list[str], j: int) -> bool:
    """Par `--- `/`+++ ` u dva reda — početak novog fajla, ne telo hunka.

    Sam `--- ` nije dovoljan: red koji briše sadržaj `-- x` izgleda isto tako.
    Par se u kodu ne pojavljuje slučajno.
    """
    return (redovi[j].startswith("--- ") and j + 1 < len(redovi)
            and redovi[j + 1].startswith("+++ "))


def prebroj_hunkove(diff: str) -> tuple[str, list[Ispravka]]:
    """Ispravlja brojeve u `@@` zaglavljima po telu hunka. ADR-0052.

    Vraća `(zakrpa, ispravke)`. Telo hunka je samodovoljno — završava se na
    sledećem `@@`, na sledećem fajlu ili na kraju — pa za dato telo postoji
    **tačno jedan** ispravan par brojeva. Ovde se ništa ne nagađa; prebrojava se.

    Šta se **ne** dira: početni brojevi reda (`-6`, `+22`) i oznaka odeljka iza
    drugog `@@`. Oni nose nameru i nisu izvedivi iz tela; da ih računamo, to bi
    bilo pogađanje šta je pisac hteo, a to ADR-0049 s pravom odbija.

    Šta ostaje greška: red u telu koji ne počinje razmakom, `+`, `-` ni `\\`. Takav
    red se ne može ni prebrojati, pa se ne može ni ispraviti.

    Zakrpa bez ijednog `@@` prolazi netaknuta: preimenovanje i izmena moda hunk ni
    ne nose (ADR-0049).

    Ispravka **nije tiha** — vraća se pozivaocu, upisuje se u `reason` zakrpe i
    stoji pred recenzentom. To je jedina odbrana od slučaja u kom je pisac hteo
    duži hunk pa ga je odsekao: zaglavlje je tada jedini trag te namere, a mi
    bismo bez zapisa ćutke prihvatili osakaćenu verziju.
    """
    redovi = diff.splitlines(keepends=True)
    goli = diff.splitlines()
    ispravke: list[Ispravka] = []
    i = 0
    while i < len(goli):
        m = _HUNK.match(goli[i])
        if m is None:
            i += 1
            continue
        trazeno_s = int(m.group("sk") or 1)
        trazeno_n = int(m.group("nk") or 1)
        j, s, n = i + 1, 0, 0
        while j < len(goli):
            red = goli[j]
            if _HUNK.match(red) or red.startswith("diff --git ") or _nov_fajl(goli, j):
                break
            z = red[:1]
            if z in (" ", ""):
                s, n = s + 1, n + 1
            elif z == "-":
                s += 1
            elif z == "+":
                n += 1
            elif z == "\\":
                pass                      # „\ No newline at end of file"
            else:
                raise PatchError(
                    "BAD_HUNK",
                    f"Red {j + 1} u hunku ne počinje razmakom, `+`, `-` ni `\\`: "
                    f"{red[:60]!r}. Ovakav red se ne može ni prebrojati.",
                )
            j += 1
        if (s, n) != (trazeno_s, trazeno_n):
            kraj = "\n" if redovi[i].endswith("\n") else ""
            redovi[i] = (f"@@ -{m.group('sp')},{s} +{m.group('np')},{n} @@"
                         f"{m.group('rep')}{kraj}")
            ispravke.append(Ispravka(red=i + 1, pre=(trazeno_s, trazeno_n),
                                     posle=(s, n)))
        i = j
    return ("".join(redovi) if ispravke else diff), ispravke


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
    # Aritmetika hunkova ide POSLE čitanja putanja, ne pre: preimenovanje i izmena
    # moda su valjane zakrpe bez ijednog `@@`, a binarna zakrpa ima svoju poruku.
    prebroj_hunkove(diff)          # diže BAD_HUNK na telo koje se ne da čitati
    return [Izmena(p, nadjene[p]) for p in sorted(nadjene)]


# ---------------------------------------------------------------------- provera


def check(zadatak: CodeTask, diff: str, *, persona: Persona | None = None) -> Nalaz:
    """Da li zakrpa sme da se primeni na ovaj zadatak.

    Svaka putanja — i stara i nova kod preimenovanja — prolazi `may_touch`.
    """
    nalaz = Nalaz(diff=diff)
    try:
        nalaz.izmene = paths_in(diff)
        # ADR-0052 — zaglavlja se prebrojavaju, i ispravljena zakrpa je ona koja
        # se dalje čuva i primenjuje. Ispravka se ne gubi: ide u `reason`.
        nalaz.diff, nalaz.ispravke = prebroj_hunkove(diff)
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
           base_sha: str = "", cena_centi: int = 0,
           od_modela: bool = False) -> TaskPatch:
    """Upisuje zakrpu i njen ishod. Odbijena zakrpa se **takođe** pamti.

    Odbijena zakrpa je podatak: po njoj se vidi da li agent stalno pokušava izvan
    svog dela koda, a to je merenje koje ADR-0034 §6 traži.
    """
    nalaz = check(zadatak, diff, persona=persona)
    # ADR-0052 — čuva se zakrpa sa prebrojanim zaglavljima, jer je to ona koja će
    # se primeniti. Ono što je pisac napisao ostaje vidljivo kroz `reason`.
    upis = nalaz.diff or diff
    razlozi = [f"{p}: {r}" for p, r in nalaz.odbijeno]
    if nalaz.ispravke:
        razlozi.append(
            "zaglavlja hunkova prebrojana (ADR-0052): "
            + "; ".join(str(i) for i in nalaz.ispravke)
            + " — proveri da hunk nije odsečen")
    red = TaskPatch.objects.create(
        task=zadatak, author=persona, base_sha=base_sha, diff=upis,
        paths=nalaz.putanje, cost_eur_cents=max(0, int(cena_centi)),
        from_model=bool(od_modela),
        status=E.PatchStatus.ACCEPTED if nalaz.ok else E.PatchStatus.REJECTED,
        reason="; ".join(nalaz.greske + razlozi)[:2000],
    )
    audit.record(
        "task.patch.submitted",
        severity=E.AuditSeverity.INFO if nalaz.ok else E.AuditSeverity.WARNING,
        persona=persona or zadatak.assignee,
        details={"task": zadatak.public_id, "status": red.status,
                 "paths": nalaz.putanje, "reason": red.reason,
                 "ispravke": [str(i) for i in nalaz.ispravke],
                 "base": base_sha, "cena_centi": red.cost_eur_cents},
    )
    return red


@transaction.atomic
def odbij_posle_provere(zadatak: CodeTask, zakrpa: TaskPatch, razlog: str) -> TaskPatch:
    """Zakrpa je prošla proveru putanja, ali se **nije primenila** kod izvršioca.

    Poslušnik ovo prijavljuje umesto da izmisli palu kapiju. Do ADR-0049 je
    svaka greška van kapija upisivana kao `pytest: False` — jedini način da
    posao izađe iz reda (ADR-0040), ali i upis testa koji nikada nije pokrenut.
    Lažna mera je gora od posla koji stoji.

    Status ide na `REJECTED`: zakrpa jeste odbijena, samo kasnije nego obično.
    Time izlazi i iz reda, jer red gleda `ACCEPTED`.
    """
    if zakrpa.task_id != zadatak.pk:
        raise TaskError("WRONG_TASK", "Zakrpa ne pripada ovom zadatku.")
    if zakrpa.gates.exists():
        raise TaskError(
            "ALREADY_MEASURED",
            "Zakrpa već ima ishod kapije; ono što je mereno se ne proglašava "
            "neprimenjivim.",
        )
    zakrpa.status = E.PatchStatus.REJECTED
    zakrpa.reason = (f"nije se primenila: {razlog}".strip())[:2000]
    zakrpa.save(update_fields=["status", "reason", "updated_at"])
    audit.record("task.patch.unapplied", severity=E.AuditSeverity.WARNING,
                 persona=zakrpa.author or zadatak.assignee,
                 details={"task": zadatak.public_id, "patch": str(zakrpa.pk),
                          "reason": zakrpa.reason})
    return zakrpa


@transaction.atomic
def pripisi_krivicu(zakrpa: TaskPatch, krivica: str, *, actor: str,
                    razlog: str) -> TaskPatch:
    """Kaže čija je greška što je zakrpa odbijena. ADR-0053.

    `ucinak` je do sada brojao odbijanja i ćutao o uzroku, pa su naši kvarovi
    stajali kao agentov promašaj: parser bez `diff --git` (ADR-0048), ponovna
    predaja koju smo izazvali (ADR-0050), zakrpa koju je pretekla ljudska ruka.
    Popravili smo uzroke i ostavili merilo — a po merilu se odlučuje.

    Granice, iste kao kod ponovnog otvaranja nalaza (ADR-0050):

      - **samo čovek.** Ovo je presuda o tuđem radu, ne merenje. Mašina koja bi
        sama sebe oslobodila krivice ne bi merila ništa;
      - **razlog je obavezan** i ide u zapis — bez njega bi `ucinak` imao broj
        koji niko ne može da potkrepi, a to je tačno ono što ADR-0033 zabranjuje;
      - **samo odbijena zakrpa.** Na prihvaćenoj krivica nema smisla.

    Status se ne dira: zakrpa je odbijena i ostaje odbijena. Menja se ko za to
    odgovara.
    """
    if krivica not in E.PatchFault.values():
        raise TaskError("UNKNOWN_FAULT", f"Nepoznata krivica {krivica!r}; poznate: "
                                         f"{sorted(E.PatchFault.values())}")
    if not actor.startswith("user:"):
        raise TaskError(
            "NOT_HUMAN",
            f"Krivicu za odbijenu zakrpu pripisuje čovek, a {actor!r} to nije.")
    if not razlog.strip():
        raise TaskError("NO_REASON",
                        "Bez razloga bi ovo bio broj koji niko ne može da potkrepi.")
    if zakrpa.status != E.PatchStatus.REJECTED.value:
        raise TaskError(
            "NOT_REJECTED",
            f"Zakrpa je {zakrpa.status}; krivica se pripisuje samo odbijenoj.")

    pre = zakrpa.fault
    zakrpa.fault = krivica
    zakrpa.fault_reason = razlog.strip()[:2000]
    zakrpa.save(update_fields=["fault", "fault_reason", "updated_at"])
    audit.record("task.patch.fault_assigned",
                 severity=E.AuditSeverity.WARNING,
                 persona=zakrpa.author,
                 details={"task": zakrpa.task.public_id, "patch": str(zakrpa.pk),
                          "iz": pre, "u": krivica, "razlog": zakrpa.fault_reason,
                          "actor": actor})
    return zakrpa


@transaction.atomic
def zabelezi_neuspeh(zadatak: CodeTask, *, persona: Persona | None, tekst: str,
                     razlog: str, cena_centi: int = 0,
                     od_modela: bool = False) -> TaskPatch:
    """Pokušaj koji nije ni stigao do zakrpe — model nije vratio upotrebljiv diff.

    Upisuje se kao odbijena zakrpa iz dva razloga, i oba su o poštenju brojeva
    (ADR-0044): poziv je **plaćen**, pa trošak mora negde da stoji; i pokušaj se
    **desio**, pa mora da se broji u plafon pokušaja. Prećutan neuspeh bi značio
    besplatan i beskonačan krug.
    """
    red = TaskPatch.objects.create(
        task=zadatak, author=persona, diff=tekst[:20_000], paths=[],
        status=E.PatchStatus.REJECTED, reason=razlog[:2000],
        cost_eur_cents=max(0, int(cena_centi)), from_model=bool(od_modela),
    )
    audit.record("task.patch.submitted", severity=E.AuditSeverity.WARNING,
                 persona=persona or zadatak.assignee,
                 details={"task": zadatak.public_id, "status": red.status,
                          "paths": [], "reason": red.reason,
                          "cena_centi": red.cost_eur_cents})
    return red

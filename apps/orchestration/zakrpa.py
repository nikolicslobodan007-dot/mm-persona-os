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
from pathlib import Path

from django.db import transaction

from api import audit
from apps.personas.models import Persona
from apps.policy import service as policy
from common import enums as E

from .models import CodeTask, TaskPatch
from .zadaci import TaskError, may_touch

__all__ = ["Izmena", "Ispravka", "Nalaz", "paths_in", "prebroj_hunkove", "check",
           "submit", "zabelezi_neuspeh", "odbij_posle_provere", "pripisi_krivicu",
           "proveri_rep", "dopuni_rep", "MAX_DIFF_BYTES", "NAJMANJE_REPA",
           "NAJVISE_DOPUNE"]

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
    #: Koliko je praznih redova u telu hunka novog fajla dobilo nazad svoj `+`
    #: (ADR-0052, dopuna 29.09.). Nula kod svakog drugog hunka.
    prazni: int = 0

    def __str__(self) -> str:
        osnovno = (f"red {self.red}: -{self.pre[0]} +{self.pre[1]} → "
                   f"-{self.posle[0]} +{self.posle[1]}")
        return osnovno if not self.prazni else (
            f"{osnovno} (vraćen `+` na {self.prazni} praznih redova novog fajla)")


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
    #: Repovi hunkova koje smo dopunili iz fajla (ADR-0066). Kao i `ispravke`:
    #: ne obara zakrpu, ali se **uvek** vidi — naša ruka u tuđem radu se ne krije.
    dopune: list[str] = field(default_factory=list)

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
        # ADR-0052 (dopuna 29.09.) — hunk novog fajla (`--- /dev/null`, stari
        # početak `0`) po definiciji formata NEMA kontekst: jedini ispravan oblik
        # je `@@ -0,0 +1,N @@`. Prazan red u njegovom telu zato nije kontekst nego
        # **dodat prazan red kome je uređivač skinuo `+`**. Bez ovoga se `-0,0`
        # „ispravi" u `-0,1`, `git apply` odbije zakrpu sa „new file depends on
        # old contents", a agent dobije neuspeh za NAŠ kvar (ADR-0053).
        nov_fajl = m.group("sp") == "0"
        j, s, n, prazni = i + 1, 0, 0, 0
        while j < len(goli):
            red = goli[j]
            if _HUNK.match(red) or red.startswith("diff --git ") or _nov_fajl(goli, j):
                break
            z = red[:1]
            if z == "" and nov_fajl:
                # Broj nije dovoljan: `git apply` prazan red u telu čita kao
                # kontekst i sam odbija hunk novog fajla. Zato se redu vraća
                # njegov `+`. Ovde se ne pogađa — u telu novog fajla svaki red
                # je dodat, pa prazan red može biti samo dodat prazan red.
                redovi[j] = "+" + redovi[j]
                n += 1
                prazni += 1
            elif z in (" ", ""):
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
        if nov_fajl and s:
            # Ovde se ne ispravlja nego se staje: `@@ -0,{s}` je nemoguć oblik,
            # pa telo sadrži red koji smo pogrešno pročitali. Tiho upisan
            # nemoguć broj je gori od odbijene zakrpe.
            raise PatchError(
                "BAD_HUNK",
                f"Hunk u redu {i + 1} počinje od starog reda 0 (nov fajl), a telo "
                f"daje {s} starih redova. Nov fajl nema kontekst — telo nije "
                f"ispravno pročitano.",
            )
        if (s, n) != (trazeno_s, trazeno_n) or prazni:
            kraj = "\n" if redovi[i].endswith("\n") else ""
            redovi[i] = (f"@@ -{m.group('sp')},{s} +{m.group('np')},{n} @@"
                         f"{m.group('rep')}{kraj}")
            ispravke.append(Ispravka(red=i + 1, pre=(trazeno_s, trazeno_n),
                                     posle=(s, n), prazni=prazni))
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
        # ADR-0066 — izostavljeni rep hunka se dopunjuje PRE prebrojavanja, da
        # prebrojavanje vidi dopunjeno telo. Dopuna se ne krije: ide u `reason`.
        dopunjen, nalaz.dopune = dopuni_rep(diff)
        # ADR-0052 — zaglavlja se prebrojavaju, i ispravljena zakrpa je ona koja
        # se dalje čuva i primenjuje. Ispravka se ne gubi: ide u `reason`.
        nalaz.diff, nalaz.ispravke = prebroj_hunkove(dopunjen)
    except PatchError as e:
        nalaz.greske.append(f"{e.code}: {e}")
        return nalaz

    # ADR-0065 — hunk bez repa `git apply` odbija, pa se to kaže ovde a ne tek
    # kod poslušnika. Provera se vrti nad ISPRAVLJENOM zakrpom, jer se ona i
    # primenjuje (ADR-0052).
    nalaz.greske.extend(proveri_rep(nalaz.diff))

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
    if nalaz.dopune:
        razlozi.append("repovi hunkova dopunjeni iz fajla (ADR-0066): "
                       + "; ".join(nalaz.dopune))
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
                 "dopune": nalaz.dopune,
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


# ------------------------------------------------------- rep hunka (ADR-0065)

#: Koliko redova konteksta `git apply` traži na kraju hunka koji nije na kraju
#: fajla. Izmereno 01.10.2026. nad pravim `git`-om: 0 → „patch does not apply",
#: 1 → primenjuje se. Nije stvar stila nego uslov primene.
NAJMANJE_REPA = 1


def _koren_slike() -> Path:
    """Stablo nad kojim brif čita fajlove — isto ono koje pisac vidi."""
    from django.conf import settings

    return Path(settings.BASE_DIR).resolve()


def proveri_rep(diff: str, koren: Path | None = None) -> list[str]:
    """Hunk koji se završava izmenjenim redom `git apply` odbija. ADR-0065.

    01.10.2026. su tri Lazarova pokušaja na `TSK-01M3V1NV6S82R25AMH8E6JWYNK`
    primljena kao `ACCEPTED`, a poslušnik ih je odbio sa „patch does not apply".
    Zakrpa je bila ispravna po svemu što smo proveravali — putanje, aritmetika
    hunkova, kontekst koji postoji u fajlu bajt po bajt — ali je poslednji red
    hunka bio dodat red, bez ijednog reda konteksta iza.

    Izuzetak je hunk koji dopire do **kraja fajla**: tamo repa nema odakle, i
    `git` ga ne traži. Zato se gleda stvarni fajl, a ne samo zaglavlje.

    Vraća spisak poruka; prazan spisak znači da je sve u redu. Fajl koji se ne
    može pročitati se **preskače** — ovo je provera, ne drugi sloj dozvola, a
    ćutke odbijena ispravna zakrpa je gora od propuštene (ADR-0053).
    """
    koren = koren or _koren_slike()
    greske: list[str] = []
    redovi = diff.splitlines()
    put: str | None = None
    i = 0
    while i < len(redovi):
        red = redovi[i]
        if (m := _PLUS.match(red)):
            try:
                put = _clean(m.group("put"))
            except PatchError:
                put = None
            i += 1
            continue
        if not (m := _HUNK.match(red)):
            i += 1
            continue
        pocetak = int(m.group("sp"))
        starih = int(m.group("sk") or 1)
        # Telo hunka: do sledećeg zaglavlja, sledećeg fajla ili kraja.
        j, poslednji = i + 1, ""
        while j < len(redovi):
            t = redovi[j]
            if _HUNK.match(t) or t.startswith("diff --git ") or _MINUS.match(t):
                break
            if t[:1] in ("+", "-", " ") or t == "":
                poslednji = t
            j += 1
        if poslednji[:1] in ("+", "-") and put:
            fajl = (koren / put)
            try:
                ukupno = len(fajl.read_text(encoding="utf-8").splitlines())
            except OSError:
                i = j
                continue
            kraj_hunka = pocetak + starih - 1
            if kraj_hunka < ukupno:
                greske.append(
                    f"{put}: hunk u redu {i + 1} se završava izmenjenim redom. "
                    f"`git apply` takav hunk odbija — dodaj bar {NAJMANJE_REPA} red "
                    f"konteksta iza poslednje izmene (red {kraj_hunka + 1} fajla), "
                    "i uračunaj ga u brojeve u `@@` zaglavlju.")
        i = j
    return greske


#: Koliko redova repa smemo da dopunimo iz fajla (ADR-0066). Manjak veći od ovoga
#: nije zaboravljen rep nego nešto drugo, i tada se zakrpa odbija kao i pre.
NAJVISE_DOPUNE = 5


def dopuni_rep(diff: str, koren: Path | None = None) -> tuple[str, list[str]]:
    """Dopunjuje izostavljeni rep hunka doslovnim redovima iz fajla. ADR-0066.

    Izmereno 01.10.2026. na pet uzastopnih pokušaja: model u zaglavlju napiše
    `@@ -186,10`, a u telu ostavi osam starih redova i završi izmenom. Zna da
    tamo idu još dva reda — i sam ih je izbrojao — ali ih ne otkuca. `git apply`
    takav hunk odbija (ADR-0065).

    **Ovo nije pogađanje.** Koliko redova fali kaže model svojim zaglavljem; koji
    su to redovi kaže fajl, na poziciji koju je model deklarisao. A ako pozicija
    nije tačna, `git` i dalje neće naći kontekst i zakrpa pada kao i do sada — kao
    što pada i kad dopune nema. Dopuna, dakle, ne može tiho da promaši: ili se sve
    poklopi, ili pukne isto kao pre.

    Radi se **pre** `prebroj_hunkove`, da prebrojavanje vidi dopunjeno telo.
    Vraća (zakrpa, spisak opisa) — opisi idu u `reason`, nikad se ne prećute.
    """
    koren = koren or _koren_slike()
    redovi = diff.splitlines()
    izlaz: list[str] = []
    opisi: list[str] = []
    put: str | None = None
    i = 0
    while i < len(redovi):
        red = redovi[i]
        izlaz.append(red)
        if (m := _PLUS.match(red)):
            try:
                put = _clean(m.group("put"))
            except PatchError:
                put = None
            i += 1
            continue
        if not (m := _HUNK.match(red)):
            i += 1
            continue
        pocetak, trazeno = int(m.group("sp")), int(m.group("sk") or 1)
        j, telo, starih = i + 1, [], 0
        while j < len(redovi):
            t = redovi[j]
            if _HUNK.match(t) or t.startswith("diff --git ") or _MINUS.match(t):
                break
            telo.append(t)
            if t[:1] in (" ", "-") or t == "":
                starih += 1
            j += 1
        manjak = trazeno - starih
        poslednji = telo[-1] if telo else ""
        if (put and poslednji[:1] in ("+", "-") and 0 < manjak <= NAJVISE_DOPUNE):
            try:
                svi = (koren / put).read_text(encoding="utf-8").splitlines()
            except OSError:
                svi = []
            # Redovi koji fale su oni odmah iza onoga što je hunk pokrio.
            od, do = pocetak - 1 + starih, pocetak - 1 + trazeno
            if svi and do <= len(svi):
                telo += [" " + x for x in svi[od:do]]
                opisi.append(
                    f"{put}: hunku u redu {i + 1} dopisano {manjak} red(ova) "
                    f"konteksta iz fajla (redovi {od + 1}–{do}), jer je zaglavlje "
                    f"tražilo {trazeno} starih redova a telo dalo {starih} "
                    "(ADR-0066)")
        izlaz += telo
        i = j
    return ("\n".join(izlaz) + ("\n" if diff.endswith("\n") else "")), opisi

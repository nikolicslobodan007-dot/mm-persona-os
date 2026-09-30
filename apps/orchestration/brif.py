"""Brif za pisca zakrpe. ADR-0041 (prva polovina).

Da bi agent napisao diff koji se **primenjuje**, nije dovoljno da mu se kaže šta
da uradi — mora da vidi fajlove kakvi su sada. Do sada toga nije bilo nigde:
`/tasks/{id}/work` daje zakrpu koja postoji, ne građu za zakrpu koja tek treba
da nastane.

Tri stvari koje brif namerno radi:

  - **staje u granice.** Nema „pošalji mu ceo repozitorijum": broj fajlova,
    veličina po fajlu i ukupna veličina imaju plafon, a šta je odsečeno se
    **kaže**, ne prećuti (ADR-0036 §1 — tiho ispuštenih stvari nema).
  - **nosi otisak svakog fajla.** Slika aplikacije nema `.git`, pa brif ne može
    da tvrdi commit. Umesto obećanja koje ne može da ispuni, daje `sha256` po
    fajlu; ako se radni primerak razlikuje, `git apply` pukne glasno.
  - **nosi i povratnu informaciju** — otvorene nalaze recenzenta i poslednje pale
    kapije. Bez toga bi sledeći pokušaj ponovio istu grešku.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from django.conf import settings
from django.db.models import Q

from apps.policy import service as policy
from common import enums as E

from .models import CodeTask

__all__ = ["build", "MAX_FILES", "MAX_FILE_BYTES", "MAX_TOTAL_BYTES"]

#: Plafoni. Zadatak koji ih probija nije uzak dovoljno — deli se, ne podiže se plafon.
MAX_FILES = 40
MAX_FILE_BYTES = 60_000
MAX_TOTAL_BYTES = 200_000

#: Šta se i ne pokušava pročitati kao tekst.
BINARNE = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz",
    ".tar", ".woff", ".woff2", ".ttf", ".mo", ".pyc", ".so", ".bin", ".sqlite3",
})
PRESKOCI_DIR = frozenset({".git", "__pycache__", "node_modules", ".ruff_cache",
                          ".pytest_cache", "staticfiles", "media"})

#: ADR-0061 — fajlovi koje pisac uvek dobija **da ih pročita**, bez obzira na
#: dozvoljene putanje, i koje ne sme da menja.
#:
#: `common/enums.py` je rečnik celog sistema (Canon §20): svaka zakrpa koja
#: imenuje status, ishod ili šifru greške mora da vidi koji članovi postoje.
#: 30.09. je P-00027 vratio prozu umesto zakrpe jer nije mogao da potvrdi da
#: `E.StepStatus.SKIPPED` postoji, a ADR-0033 mu zabranjuje da pretpostavi.
#: Zaštićena zona zabranjuje **izmenu**, ne čitanje — `code.read` je L0 za sve.
REFERENCA: tuple[str, ...] = ("common/enums.py",)

#: Iz referentnih `.py` fajlova ide **izvod**, ne ceo tekst: pisac traži rečnik,
#: ne prozu. Mereno 30.09. na `common/enums.py`: ceo fajl 41.552 B (20,8 % od
#: `MAX_TOTAL_BYTES`), izvod 15.874 B (7,9 %) — i sadrži sve članove.
_KLASA = re.compile(r"^class \w+")
_CLAN = re.compile(r"^    [A-Z][A-Z0-9_]* = ")


def _koren() -> Path:
    return Path(settings.BASE_DIR).resolve()


def _kandidati(zadatak: CodeTask) -> list[Path]:
    """Fajlovi pod dozvoljenim putanjama, uredno sortirani i bez smeća."""
    koren, nadjeni = _koren(), []
    for prefiks in zadatak.allowed_paths:
        p = (koren / policy.normalize_path(prefiks)).resolve()
        # Prefiks van korena se ne čita ni slučajno.
        if not (p == koren or koren in p.parents):
            continue
        if p.is_file():
            nadjeni.append(p)
            continue
        if not p.is_dir():
            continue
        for f in sorted(p.rglob("*")):
            if not f.is_file():
                continue
            if PRESKOCI_DIR & set(f.relative_to(koren).parts):
                continue
            nadjeni.append(f)
    return sorted(set(nadjeni))


def _procitaj(f: Path) -> tuple[str, str] | None:
    """Sadržaj i `sha256`, ili `None` ako fajl nije tekst."""
    if f.suffix.lower() in BINARNE:
        return None
    try:
        sirovo = f.read_bytes()
    except OSError:
        return None
    try:
        tekst = sirovo.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return tekst, hashlib.sha256(sirovo).hexdigest()


def _izvod_enuma(tekst: str) -> str:
    """Iz `.py` fajla vadi samo zaglavlja klasa i članove u velikim slovima.

    Pisac treba da zna **koji članovi postoje**, ne zašto. Dokumentacija i telo
    metoda su tri četvrtine fajla i nijedan od njih ne odgovara na pitanje zbog
    kog je ADR-0061 napisan.
    """
    izlaz, u_klasi = [], False
    for red in tekst.splitlines():
        if _KLASA.match(red):
            izlaz.append(red)
            u_klasi = True
        elif u_klasi and _CLAN.match(red):
            izlaz.append(red)
        elif red and not red.startswith((" ", ")")):
            u_klasi = False
    return "\n".join(izlaz) + "\n" if izlaz else tekst


def _referenca(koren: Path) -> list[dict]:
    """Fajlovi koje pisac sme da čita a ne sme da menja. ADR-0061."""
    redovi = []
    for rel in REFERENCA:
        f = (koren / rel).resolve()
        if not (f.is_file() and (f == koren or koren in f.parents)):
            continue
        procitano = _procitaj(f)
        if procitano is None:
            continue
        tekst, otisak = procitano
        redovi.append({
            "path": rel,
            "sha256": otisak,
            "content": _izvod_enuma(tekst) if f.suffix == ".py" else tekst,
            "read_only": True,
        })
    return redovi


def _nalazi(zadatak: CodeTask) -> list[dict]:
    return [
        {"file": n.file, "line": n.line, "severity": n.severity,
         "claim": n.claim[:1000], "source": n.source}
        for n in zadatak.findings.filter(status=E.FindingStatus.OPEN.value)
        .order_by("severity", "file")[:50]
    ]


def _pale_kapije(zadatak: CodeTask) -> list[dict]:
    """Poslednji ishod po kapiji, samo ako je pao — to je ono što treba popraviti."""
    poslednji: dict[str, object] = {}
    for red in zadatak.gates.order_by("created_at"):
        poslednji[red.gate] = red
    return [
        {"gate": g, "detail": (r.detail or "")[-3000:]}
        for g, r in sorted(poslednji.items()) if not r.passed
    ]


#: Koliko ranije zakrpe staje u brif. Ista mera kao plafon diff-a kod pisca.
MAX_PATCH_BYTES = 20_000

#: Rečenica koja stoji uz svaki brif. Fajlovi dolaze sa diska ove slike, a slika
#: je sagrađena iz `main` — grane sa nespojenim radom u njoj NEMA (ADR-0047).
IZVOR_FAJLOVA = (
    "Fajlovi ispod su trenutno stanje u glavnoj grani, onako kako ih vidi ova "
    "slika aplikacije. Rad koji stoji na granama zadataka, uključujući tvoje "
    "ranije zakrpe, NIJE u njima. Novu zakrpu pišeš nad ovim fajlovima."
)


def _ishod(red) -> str:
    """Šta se sa zakrpom **stvarno** desilo, rečenicom koju pisac može da pročita.

    `status` sam po sebi obmanjuje. `ACCEPTED` znači samo „prošla je proveru
    putanja" — a 27.09. je pisac dobio brif u kome je njegova pokvarena zakrpa
    stajala kao `ACCEPTED`, pa je razumno zaključio da je sve u redu i vratio je
    istu. To je koštalo jedan poziv i poslednji pokušaj (ADR-0050).
    """
    if red.status == E.PatchStatus.REJECTED.value:
        return "ODBIJENA je i nije ušla u kod. Razlog: " + (
            red.reason or "nije zabeležen").strip()
    if red.applied_sha:
        return f"primenjena i zapamćena na grani zadatka (commit {red.applied_sha[:12]})."
    if red.status == E.PatchStatus.APPLIED.value:
        return "primenjena, ali commit nije zabeležen."
    return ("prošla je proveru putanja, ali NIJE primenjena — u kodu je nema. "
            "Pogledaj pale kapije ispod i napiši je iznova.")


def _prethodna(zadatak: CodeTask) -> dict | None:
    """Poslednja zakrpa **čija je sudbina poznata**, i ta sudbina uz nju.

    Bez nje je brif protivrečan: nalazi govore o kodu koji u fajlovima ne postoji,
    jer grana nije u slici. Aplikacija nema `.git` (ADR-0041 §2) i ne može da
    pročita granu, ali zakrpu ima u bazi — pa se šalje ona.

    Odbijena zakrpa ulazi **bez uslova**: njen razlog je jedino po čemu pisac može
    da ispravi rad, a do ADR-0050 do njega nije stizao nijedan — ni „nije vratio
    diff", ni „ista zakrpa", ni `BAD_HUNK`. Prihvaćena a neizmerena ne ulazi: nju
    poslušnik tek uzima, pa se o njoj još ništa ne zna.
    """
    red = (zadatak.patches
           .filter(Q(status=E.PatchStatus.REJECTED.value)
                   | (Q(status__in=(E.PatchStatus.ACCEPTED.value,
                                    E.PatchStatus.APPLIED.value))
                      & (Q(gates__isnull=False) | ~Q(applied_sha=""))))
           .order_by("-created_at").first())
    if red is None:
        return None
    diff = red.diff or ""
    odsecen = len(diff.encode("utf-8")) > MAX_PATCH_BYTES
    if odsecen:
        diff = diff.encode("utf-8")[:MAX_PATCH_BYTES].decode("utf-8", "ignore")
    return {
        "patch_id": str(red.pk),
        # `ishod` stoji PRE `status`-a namerno: to je ono što pisac treba da
        # pročita, a `status` je interna reč koja se lako pogrešno razume.
        "ishod": _ishod(red),
        "status": red.status,
        "reason": (red.reason or "")[:2000],
        "applied_sha": red.applied_sha,
        "paths": list(red.paths),
        "diff": diff,
        "truncated": odsecen,
    }


def build(zadatak: CodeTask) -> dict:
    """Sve što piscu zakrpe treba, i ništa više.

    `odsečeno` nije kozmetika: pisac mora da zna da nije video sve, inače piše
    zakrpu nad pretpostavkom (ADR-0033). Iz istog razloga brif kaže **iz kog
    stabla** su fajlovi i nosi **ranije predatu zakrpu** kad je ima: nalaz koji
    opisuje kod kog u priloženim fajlovima nema je protivrečan brif (ADR-0047).
    """
    koren = _koren()
    fajlovi: list[dict] = []
    odsečeno: list[dict] = []
    ukupno = 0

    # Ranija zakrpa ulazi u isti plafon kao i fajlovi. Kad zbog nje fajl ispadne,
    # to se kaže u `truncated` — plafon se ne podiže tiho (ADR-0041 §1).
    prethodna = _prethodna(zadatak)
    zauzeto = len(prethodna["diff"].encode("utf-8")) if prethodna else 0
    # ADR-0061 — referenca ulazi u isti plafon kao i sve ostalo. Ne dodaje se
    # „pored" budžeta: tada bi rasla dok neko ne primeti. Ono što ne stane ne
    # nestaje tiho nego ide u `truncated`, kao i svaki drugi fajl.
    referenca: list[dict] = []
    for r in _referenca(koren):
        velicina = len(r["content"].encode("utf-8"))
        if zauzeto + velicina > MAX_TOTAL_BYTES:
            odsečeno.append({"path": r["path"],
                             "reason": "rečnik nije stao u ukupan plafon"})
            continue
        zauzeto += velicina
        referenca.append(r)
    plafon = MAX_TOTAL_BYTES - zauzeto

    for f in _kandidati(zadatak):
        rel = f.relative_to(koren).as_posix()
        if zona := policy.path_is_protected(rel):
            odsečeno.append({"path": rel, "reason": f"zaštićena zona ({zona})"})
            continue
        if len(fajlovi) >= MAX_FILES:
            odsečeno.append({"path": rel, "reason": "preko plafona broja fajlova"})
            continue
        procitano = _procitaj(f)
        if procitano is None:
            odsečeno.append({"path": rel, "reason": "nije tekst"})
            continue
        tekst, otisak = procitano
        velicina = len(tekst.encode("utf-8"))
        if velicina > MAX_FILE_BYTES:
            odsečeno.append({"path": rel, "reason": f"fajl veći od {MAX_FILE_BYTES} B"})
            continue
        if ukupno + velicina > plafon:
            odsečeno.append({
                "path": rel,
                "reason": "preko ukupnog plafona"
                          + (" (deo zauzela ranija zakrpa)" if zauzeto else ""),
            })
            continue
        ukupno += velicina
        fajlovi.append({"path": rel, "sha256": otisak, "content": tekst})

    return {
        "task_id": zadatak.public_id,
        "title": zadatak.title,
        "why": zadatak.why,
        "adr": zadatak.adr,
        "allowed_paths": list(zadatak.allowed_paths),
        "required_gates": list(zadatak.required_gates),
        "protected_paths": list(policy.config.protected_paths()),
        "reference": referenca,
        "files": fajlovi,
        "files_from": IZVOR_FAJLOVA,
        "previous_patch": prethodna,
        "truncated": odsečeno,
        "open_findings": _nalazi(zadatak),
        "failed_gates": _pale_kapije(zadatak),
        "bytes": ukupno + zauzeto,
    }

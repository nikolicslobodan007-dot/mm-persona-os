"""manage.py signali — GitHub Signals (githubsignals.io) kao izvor za sakupljač.

--lista:  pročita javni /export.csv, filtrira po zvezdicama, dedupe po repo_slug,
          NABRAJA kandidate (+ koju `sakupi` komandu bi pozvao). Bez troška.
--sakupi: za prvih --najvise NOVIH kandidata pozove `sakupi --url <repo>` i upiše
          veštine po repou u --izlaz-dir (preskače već obrađene). Troši LLM, pa
          traži --najvise N (N > 0) kao branu na trošak.

CSV kolone (11): published_at, provider, post_url, repo_slug, repo_url,
repo_stars, repo_keywords, caption, likes, plays, comments.

Primeri:
  python manage.py signali --lista --min-zvezdica 20 --maks 40
  python manage.py signali --sakupi --najvise 5 --min-zvezdica 50
  python manage.py signali --lista --csv-fajl /put/export.csv   # lokalni CSV (bez mreže)
"""

from __future__ import annotations

import csv
import io
import json
import os
import time
import urllib.request
from collections import defaultdict
from urllib.parse import quote

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

CSV_URL = "https://githubsignals.io/export.csv"
IZLAZ_DIR = "korpus/vestine/github-signals"
SKRIPTA_DEFAULT = "korpus/vestine/github-signals/_uvoz.sh"
#: Podrazumevane teme = Slobodanovi domeni (Persona OS/PickStar/MercatoMaster/farma).
TEME_PODRAZUMEVANE = ("ai agent", "agent", "llm", "mcp", "automation", "browser",
                      "scrap", "video", "marketing", "crm", "rag", "self-host")


def _ceo_broj(s: str) -> int:
    try:
        return int((s or "").strip() or 0)
    except ValueError:
        return 0


def _parsiraj(csv_tekst: str) -> list[dict]:
    """CSV tekst → lista normalizovanih redova (samo bitne kolone)."""
    redovi: list[dict] = []
    for r in csv.DictReader(io.StringIO(csv_tekst)):
        slug = (r.get("repo_slug") or "").strip()
        repo = (r.get("repo_url") or "").strip()
        if not slug or not repo:
            continue
        redovi.append({
            "slug": slug,
            "repo_url": repo,
            "zvezdica": _ceo_broj(r.get("repo_stars")),
            "kljucne_reci": (r.get("repo_keywords") or "").strip(),
            "provajder": (r.get("provider") or "").strip().lower(),
            "post_url": (r.get("post_url") or "").strip(),
        })
    return redovi


def _filtriraj(redovi: list[dict], min_zvezdica: int,
               teme: tuple[str, ...] = ()) -> list[dict]:
    """Prag zvezdica + (opc.) filter po temama + dedup po slug-u + sort opadajuće.

    `teme` se poredi kao podniz (case-insensitive) sa `repo_keywords`; prazno =
    bez filtera. Repo bez ključnih reči ispada kad je filter po temama uključen.
    """
    vidjeno: set[str] = set()
    izlaz: list[dict] = []
    for r in sorted(redovi, key=lambda x: x["zvezdica"], reverse=True):
        if r["zvezdica"] < min_zvezdica or r["slug"] in vidjeno:
            continue
        if teme and not any(t in r["kljucne_reci"].lower() for t in teme):
            continue
        vidjeno.add(r["slug"])
        izlaz.append(r)
    return izlaz


def _teme_iz(o) -> tuple[str, ...]:
    """CSV string `--teme` → tuple malih slova; prazno → bez filtera."""
    sirovo = (o.get("teme") or "").strip()
    if not sirovo:
        return ()
    return tuple(t.strip().lower() for t in sirovo.split(",") if t.strip())


def _komande(r: dict) -> list[str]:
    """Koje bi `sakupi` komande ovaj unos pozvao (repo uvek; YouTube video ako ga ima)."""
    kom = [f'manage.py sakupi --url "{r["repo_url"]}"']
    if r["provajder"] == "youtube" and r["post_url"]:
        kom.append(f'manage.py sakupi --klip-url "{r["post_url"]}"')
    return kom


def _putanja(izlaz_dir: str, slug: str) -> str:
    """Izlazni JSON za repo: owner/repo → owner__repo.json."""
    return os.path.join(izlaz_dir, slug.replace("/", "__") + ".json")


def _za_obradu(kandidati: list[dict], izlaz_dir: str, najvise: int,
               uvezeni: frozenset[str] | set[str] = frozenset()) -> list[tuple[dict, str]]:
    """Prvih `najvise` kandidata koji nisu ni u bazi (`uvezeni`) ni kao fajl (dedup)."""
    out: list[tuple[dict, str]] = []
    for r in kandidati:
        if r["slug"] in uvezeni:
            continue
        put = _putanja(izlaz_dir, r["slug"])
        if os.path.exists(put):
            continue
        out.append((r, put))
        if len(out) >= najvise:
            break
    return out


def _uvezeni_slugovi(prefiks: str = "GitHub Signals: ") -> set[str]:
    """Slugovi repoa već uvezenih u bazu (KnowledgeSource title '<prefiks><slug>')."""
    from apps.memory.models import KnowledgeSource
    out: set[str] = set()
    for t in (KnowledgeSource.objects
              .filter(title__startswith=prefiks)
              .values_list("title", flat=True)):
        out.add(t[len(prefiks):].strip())
    return out


def _auto_uvoz(izlaz_abs: str, izlaz_dir: str, actor: str = "user:slobodan") -> dict:
    """Uvezi sabrane JSON-ove u bazu sa pravom kutijom (ADR-0059).

    SLOBODNA → upotrebljivo; NEPOZNATA/ZARAZNA/ZABRANJENA → zabeleženo ali
    NEupotrebljivo (sistem pušta samo SLOBODNA). Beleženje svih spречava da
    dnevni „top N" ostane zaglavljen na istim repoima i da se ponovo plaća.
    `actor` je `user:slobodan` — njegova stajaća odluka za auto-uvoz.
    """
    from django.core.management import call_command
    stats = {"repoa": 0, "SLOBODNA": 0, "NEPOZNATA": 0, "ZARAZNA": 0, "ZABRANJENA": 0}
    if not os.path.isdir(izlaz_abs):
        return stats
    for f in sorted(x for x in os.listdir(izlaz_abs) if x.endswith(".json")):
        owner, _, repo = f[:-5].partition("__")
        if not repo:
            continue
        slug = f"{owner}/{repo}"
        box, naziv = _spdx_u_kutiju(_github_licenca(owner, repo))
        call_command("vestina", datoteka=os.path.join(izlaz_dir, f),
                     izvor=f"GitHub Signals: {slug}", uri=f"https://github.com/{slug}",
                     licenca=box, naziv_licence=naziv, actor=actor)
        stats["repoa"] += 1
        stats[box] = stats.get(box, 0) + 1
    return stats


_SLOBODNE = frozenset({
    "MIT", "APACHE-2.0", "BSD-2-CLAUSE", "BSD-3-CLAUSE", "BSD-3-CLAUSE-CLEAR",
    "ISC", "0BSD", "UNLICENSE", "ZLIB",
})
_ZARAZNE = ("GPL-", "AGPL-", "LGPL-", "SSPL-", "BUSL-", "MPL-", "EPL-", "OSL-", "CDDL-")


def _github_licenca(owner: str, repo: str) -> str:
    """Repoova DEKLARISANA SPDX licenca (GitHub API). '' ako nema/greška/limit."""
    url = f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "mm-persona-os-sakupljac",
        "Accept": "application/vnd.github+json",
    })
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 — fiksni host
            podaci = json.loads(r.read(1_000_000).decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 — API greška/limit → nepoznata licenca
        return ""
    lic = (podaci or {}).get("license") or {}
    return (lic.get("spdx_id") or "").strip()


def _spdx_u_kutiju(spdx: str) -> tuple[str, str]:
    """SPDX id → (kutija, naziv). Nepoznato/prazno → NEPOZNATA (nema dozvole)."""
    s = (spdx or "").strip().upper()
    if not s or s in ("NOASSERTION", "OTHER"):
        return "NEPOZNATA", ""
    if s in _SLOBODNE:
        return "SLOBODNA", spdx.strip()
    if s.startswith(_ZARAZNE):
        return "ZARAZNA", ""
    if "-NC" in s or s.startswith("CC-BY-NC"):
        return "ZABRANJENA", ""
    return "NEPOZNATA", ""


def _vestina_komanda(put: str, izvor: str, repo_url: str, box: str, naziv: str) -> str:
    """Gotova `vestina` komanda za uvoz jednog repo-JSON-a (čovek je pokreće)."""
    delovi = [
        "python manage.py vestina",
        f'--datoteka "{put}"',
        f'--izvor "{izvor}"',
        f'--uri "{repo_url}"',
        f"--licenca {box}",
    ]
    if naziv:
        delovi.append(f'--naziv-licence "{naziv}"')
    delovi.append("--actor user:slobodan")
    return " ".join(delovi)


class Command(BaseCommand):
    help = "GitHub Signals izvor: nabroji (--lista) ili saberi (--sakupi) kandidate."

    def add_arguments(self, p):
        p.add_argument("--lista", action="store_true", help="Nabroji kandidate (bez troška).")
        p.add_argument("--sakupi", action="store_true",
                       help="Pozovi sakupi po kandidatu (troši LLM; traži --najvise).")
        p.add_argument("--licence", action="store_true",
                       help="Za sabrane JSON-ove: pročitaj SPDX licencu i emituj vestina komande.")
        p.add_argument("--csv-url", default=CSV_URL, help="URL CSV izvoza.")
        p.add_argument("--csv-fajl", help="Lokalni CSV umesto mreže (za test/offline).")
        p.add_argument("--min-zvezdica", type=int, default=20, help="Prag broja zvezdica.")
        p.add_argument("--teme", default=",".join(TEME_PODRAZUMEVANE),
                       help="Filter po repo_keywords (CSV). Prazno (--teme \"\") = sve teme.")
        p.add_argument("--maks", type=int, default=50,
                       help="--lista: najviše kandidata za ispis.")
        p.add_argument("--najvise", type=int, default=0,
                       help="--sakupi: koliko NOVIH repoa obraditi (obavezno > 0).")
        p.add_argument("--maks-vestina", type=int, default=8,
                       help="--sakupi: najviše veština po repou.")
        p.add_argument("--izlaz-dir", default=IZLAZ_DIR,
                       help="--sakupi/--licence: folder sa rezultatima po repou.")
        p.add_argument("--skripta", nargs="?", const=SKRIPTA_DEFAULT, default="",
                       help="--licence: upiši vestina komande u pokretljiv .sh skript.")
        p.add_argument("--auto", action="store_true",
                       help="sakupi + auto-uvoz (SLOBODNA upotrebljivo, ostalo zabeleženo).")
        p.add_argument("--actor", default="user:slobodan",
                       help="--auto/--reklasifikuj: actor (ADR-0074).")
        p.add_argument("--pregled", action="store_true",
                       help="Izveštaj: stanje u bazi + non-SLOBODNA za pregled.")
        p.add_argument("--reklasifikuj", default="",
                       help="Naslov izvora čiju kutiju licence menjaš (posle pregleda).")
        p.add_argument("--licenca", default="", help="--reklasifikuj: nova kutija licence.")
        p.add_argument("--naziv-licence", default="",
                       help="--reklasifikuj: naziv licence (obavezno za SLOBODNA).")

    def handle(self, *args, **o):
        if o.get("reklasifikuj"):
            return self._reklasifikuj(o)
        if o.get("pregled"):
            return self._pregled(o)
        if o.get("auto"):
            return self._auto(o)
        if o.get("sakupi"):
            return self._sakupi(o)
        if o.get("licence"):
            return self._licence(o)
        if o.get("lista"):
            return self._lista(o)
        raise CommandError("Daj --lista, --sakupi ILI --licence.")

    def _lista(self, o):
        teme = _teme_iz(o)
        svi = _parsiraj(self._ucitaj(o))
        kandidati = _filtriraj(svi, o["min_zvezdica"], teme)

        opis_tema = f"; teme: {', '.join(teme)}" if teme else "; sve teme"
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"# GitHub Signals: {len(svi)} redova, "
            f"{len(kandidati)} kandidata (≥ {o['min_zvezdica']}★{opis_tema})"))

        jutjub = 0
        for r in kandidati[:o["maks"]]:
            reci = f"  [{r['kljucne_reci']}]" if r["kljucne_reci"] else ""
            self.stdout.write(f"\n- {r['slug']}  ({r['zvezdica']}★){reci}")
            for k in _komande(r):
                self.stdout.write(f"    {k}")
            if r["provajder"] == "youtube" and r["post_url"]:
                jutjub += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nIspisano {min(len(kandidati), o['maks'])} od {len(kandidati)} "
            f"kandidata; {jutjub} sa YouTube videom (ide i kroz --klip-url)."))

    def _sakupi(self, o):
        najvise = o["najvise"]
        if najvise <= 0:
            raise CommandError("--sakupi traži --najvise N (N > 0) da ograniči trošak.")
        baza = getattr(settings, "BASE_DIR", os.getcwd())
        izlaz_dir = o["izlaz_dir"]
        izlaz_abs = izlaz_dir if os.path.isabs(izlaz_dir) else os.path.join(baza, izlaz_dir)
        os.makedirs(izlaz_abs, exist_ok=True)

        kandidati = _filtriraj(_parsiraj(self._ucitaj(o)), o["min_zvezdica"], _teme_iz(o))
        uvezeni = _uvezeni_slugovi()
        za_obradu = _za_obradu(kandidati, izlaz_abs, najvise, uvezeni)

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"# sakupi: {len(za_obradu)} novih repoa "
            f"(od {len(kandidati)} kandidata ≥ {o['min_zvezdica']}★; "
            f"{len(uvezeni)} već u bazi)"))
        if not za_obradu:
            self.stdout.write("Nema novih repoa (svi već obrađeni).")
            return

        obradjeno = 0
        for i, (r, put) in enumerate(za_obradu, 1):
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\n[{i}/{len(za_obradu)}] {r['slug']} ({r['zvezdica']}★)"))
            try:
                call_command("sakupi", url=r["repo_url"], izlaz=put, maks=o["maks_vestina"])
                obradjeno += 1
            except Exception as e:  # noqa: BLE001 — jedan repo ne sme da sruši ceo batch
                self.stdout.write(self.style.ERROR(f"  greška: {str(e)[:120]}"))
            time.sleep(1)

        self.stdout.write(self.style.SUCCESS(
            f"\nObrađeno {obradjeno}/{len(za_obradu)} repoa → {izlaz_dir}/"))

    def _licence(self, o):
        baza = getattr(settings, "BASE_DIR", os.getcwd())
        izlaz_dir = o["izlaz_dir"]
        izlaz_abs = izlaz_dir if os.path.isabs(izlaz_dir) else os.path.join(baza, izlaz_dir)
        if not os.path.isdir(izlaz_abs):
            raise CommandError(f"Nema foldera: {izlaz_abs} (prvo --sakupi).")
        fajlovi = sorted(f for f in os.listdir(izlaz_abs) if f.endswith(".json"))
        if not fajlovi:
            self.stdout.write("Nema sabranih JSON-ova (prvo pokreni --sakupi).")
            return

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"# licence: {len(fajlovi)} repoa u {izlaz_dir}/"))
        komande: list[str] = []
        for f in fajlovi:
            owner, _, repo = f[:-5].partition("__")
            if not repo:
                continue
            slug = f"{owner}/{repo}"
            repo_url = f"https://github.com/{slug}"
            box, naziv = _spdx_u_kutiju(_github_licenca(owner, repo))
            self.stdout.write(f"\n- {slug}  → {box}" + (f" ({naziv})" if naziv else ""))
            put = os.path.join(izlaz_dir, f)
            kom = _vestina_komanda(put, f"GitHub Signals: {slug}", repo_url, box, naziv)
            self.stdout.write("    " + kom)
            komande.append(kom)
            time.sleep(0.5)

        if o.get("skripta") and komande:
            self._upisi_skriptu(baza, o["skripta"], komande)

        self.stdout.write(self.style.SUCCESS(
            "\nPregledaj kutije pa pokreni vestina komande sam (ADR-0074). "
            "SLOBODNA sme u klijentske projekte; ostalo se čuva uz zabeleženu kutiju."))

    def _upisi_skriptu(self, baza, skripta, komande):
        put = skripta if os.path.isabs(skripta) else os.path.join(baza, skripta)
        os.makedirs(os.path.dirname(put) or ".", exist_ok=True)
        telo = (
            "#!/usr/bin/env bash\n"
            "# Uvoz veština iz GitHub Signals u bazu znanja (ADR-0074: pokreće čovek).\n"
            "# Pregledaj pa pokreni UNUTAR web kontejnera, iz /app:\n"
            "#   bash " + skripta + "\n"
            "set -euo pipefail\n\n"
            + "\n".join(komande) + "\n"
        )
        with open(put, "w", encoding="utf-8") as fh:
            fh.write(telo)
        os.chmod(put, 0o755)
        rel = os.path.relpath(put, baza)
        self.stdout.write(self.style.SUCCESS(
            f"\nUpisana skripta uvoza ({len(komande)} komandi) → {rel}. "
            f"Pregledaj pa: bash {rel}"))

    def _auto(self, o):
        self._sakupi(o)
        baza = getattr(settings, "BASE_DIR", os.getcwd())
        izlaz_dir = o["izlaz_dir"]
        izlaz_abs = izlaz_dir if os.path.isabs(izlaz_dir) else os.path.join(baza, izlaz_dir)
        stats = _auto_uvoz(izlaz_abs, izlaz_dir, actor=o["actor"])
        self.stdout.write(self.style.SUCCESS(
            f"\nAUTO-UVOZ: {stats['repoa']} repoa — "
            f"{stats['SLOBODNA']} SLOBODNA (upotrebljivo), "
            f"{stats['repoa'] - stats['SLOBODNA']} ostalo (zabeleženo, čeka pregled)."))
        return None

    def _pregled(self, o):
        from apps.memory.vestine import spisak
        redovi = spisak(izvor="GitHub Signals")
        if not redovi:
            self.stdout.write("Nema GitHub Signals veština u bazi.")
            return
        po_izvoru: dict = {}
        vest_kut: dict = defaultdict(int)
        for r in redovi:
            po_izvoru[r["izvor"]] = r["licenca"]
            vest_kut[r["licenca"]] += 1
        izv_kut: dict = defaultdict(int)
        for b in po_izvoru.values():
            izv_kut[b] += 1
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"# GitHub Signals u bazi: {len(po_izvoru)} repoa, {len(redovi)} veština"))
        for b in ("SLOBODNA", "NEPOZNATA", "ZARAZNA", "ZABRANJENA"):
            if izv_kut.get(b):
                ozn = "upotrebljivo" if b == "SLOBODNA" else "čeka pregled"
                self.stdout.write(
                    f"  {b}: {izv_kut[b]} repoa, {vest_kut[b]} veština ({ozn})")
        pending = sorted(n for n, b in po_izvoru.items() if b != "SLOBODNA")
        if pending:
            self.stdout.write(self.style.MIGRATE_HEADING("\n# Za pregled (non-SLOBODNA):"))
            for naslov in pending:
                slug = naslov.replace("GitHub Signals: ", "", 1)
                self.stdout.write(f"- {slug}  → https://github.com/{slug}")
                self.stdout.write(
                    f'    ako je slobodna: signali --reklasifikuj "{naslov}" '
                    f"--licenca SLOBODNA --naziv-licence <SPDX>")

    def _reklasifikuj(self, o):
        from api.context import bind
        from apps.memory import vestine
        actor = o["actor"]
        if not actor.startswith("user:"):
            raise CommandError("ADR-0074: --actor mora da počne sa 'user:'.")
        if not o["licenca"]:
            raise CommandError("--reklasifikuj traži --licenca <kutija>.")
        with bind(actor_id=actor):
            try:
                promenjen = vestine.reklasifikuj(
                    naslov_izvora=o["reklasifikuj"], license_box=o["licenca"],
                    license_note=o["naziv_licence"], actor=actor)
            except ValueError as e:
                raise CommandError(str(e)) from e
        if not promenjen:
            raise CommandError(f"Izvor nije nađen: {o['reklasifikuj']}")
        self.stdout.write(self.style.SUCCESS(
            f"Reklasifikovano: {o['reklasifikuj']} → {o['licenca']}"))

    def _ucitaj(self, o) -> str:
        if o.get("csv_fajl"):
            baza = getattr(settings, "BASE_DIR", os.getcwd())
            put = o["csv_fajl"]
            put = put if os.path.isabs(put) else os.path.join(baza, put)
            if not os.path.isfile(put):
                raise CommandError(f"Nema CSV fajla: {put}")
            with open(put, encoding="utf-8") as fh:
                return fh.read()
        from apps.libri import uvoz_web
        try:
            return uvoz_web.preuzmi(o["csv_url"])
        except Exception as e:  # noqa: BLE001 — mreža/robots sme da padne, javi jasno
            raise CommandError(f"CSV preuzimanje nije uspelo: {e}") from e

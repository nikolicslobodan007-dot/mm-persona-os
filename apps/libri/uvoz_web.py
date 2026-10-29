"""Uvoz javnog web izvora u sloj znanja (ADR-0031 sloj 2, §4 — širi korpus).

Jedan javni URL -> HTML -> blokovi -> `KnowledgeSource` (PUBLIC_WEB_SOURCE) +
`LibriDocument` + `Block`-ovi, isti cevovod kao PDF uvoz. Čovek pokreće (ADR-0074):
`--actor user:` i navodi licencu (ADR-0059 §2). Više izvora => ose nezavisnost/
potkrepljenost u pouzdanosti postaju stvarne, ne degenerisane.

**Brane (lagani Libri fetch — bez Exec/transport konteksta):**
- SSRF: samo http/https; host se razreši i IP ne sme biti privatan/loopback/
  link-local/rezervisan (blok internih servisa i metapodataka 169.254.169.254);
  redirekti se proveravaju na svakom skoku.
- `robots.txt` se poštuje (A-03, aneks A): bez dozvole se ne čita.
- Deklarisani `User-Agent` (web.read_public kapabilnost, uz fallback) + Accept-Language.
- Cap veličine (5 MB) i tip sadržaja mora biti HTML/tekst.
- Poverenje izvora je NIŽE od first-party (PUBLIC_WEB_SOURCE, trust 0.5): javni web
  nije proveren. Sadržaj se čuva kao OBSERVED dokaz uz izvorni URL; licenca se
  navodi i ostaje na izvoru (verbatim u klijentski projekat samo iz SLOBODNA, ADR-0059).

Mreža je odvojena (`preuzmi`) od parsiranja+upisa (`ugradi`), pa se parser i upis
testiraju bez mreže. Pacing po hostu je van obima (ručni uvoz jednog URL-a).
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
import urllib.error
import urllib.request
import urllib.robotparser
from decimal import Decimal
from html.parser import HTMLParser
from urllib.parse import urlsplit

from django.db import transaction
from django.utils import timezone

from apps.libri.models import Block, LibriDocument
from apps.libri.uvoz import UvozError
from apps.memory.models import KnowledgeSource
from common import enums as E

VERSION_ID = "v1"
TRUST_PUBLIC_WEB = Decimal("0.500")  # javni web nije proveren (< first-party 1.000)

_MAX_BYTES = 5 * 1024 * 1024
_TIMEOUT = 15
_UA_FALLBACK = "MMPersonaOSBot/1.0 (+https://webkorporacija.com/bot)"

_VOKAL = re.compile(r"[aeiouAEIOUаеиоуАЕИОУ]")
_WS = re.compile(r"\s+")


# --- jezik/skript i kvalitet (samostalno, bez sprezanja sa grind->PyMuPDF) ---

def _znacajan(t: str) -> bool:
    return sum(1 for c in t if c.isalpha()) >= 3 and bool(_VOKAL.search(t))


def _skript_jezik(text: str) -> tuple[str, str]:
    cyr = sum(1 for c in text if "Ѐ" <= c <= "ӿ")
    lat = sum(1 for c in text if "a" <= c.lower() <= "z")
    return ("sr-Cyrl", "cyrillic") if cyr > lat else ("sr-Latn", "latin")


# --- SSRF zaštita ---

def _ip_zabranjen(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return (a.is_private or a.is_loopback or a.is_link_local or a.is_reserved
            or a.is_multicast or a.is_unspecified)


def proveri_bezbedan(url: str) -> None:
    """Diže UvozError ako URL nije bezbedan za server-side fetch (SSRF)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UvozError(f"Dozvoljeni su samo http/https, ne {parts.scheme!r}.")
    host = parts.hostname
    if not host:
        raise UvozError("URL nema host.")
    # Literalni IP: proveri direktno (bez DNS-a).
    try:
        ipaddress.ip_address(host)
        if _ip_zabranjen(host):
            raise UvozError(f"Zabranjena (interna) adresa: {host}.")
        return
    except ValueError:
        pass
    # Ime hosta: razreši i proveri SVAKI IP.
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror as e:
        raise UvozError(f"Host se ne razrešava: {host} ({e}).") from e
    for info in infos:
        ip = info[4][0]
        if _ip_zabranjen(ip):
            raise UvozError(f"Host {host} pokazuje na internu adresu {ip}.")


class _SigurniRedirekt(urllib.request.HTTPRedirectHandler):
    """Proveri svaki redirekt-cilj (SSRF se ne sme zaobići kroz Location)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        proveri_bezbedan(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# --- fetch (mreža) ---

def _ua() -> str:
    try:
        from apps.runtime.adapters.web import user_agent
        return user_agent() or _UA_FALLBACK
    except Exception:
        return _UA_FALLBACK


def _robots_odluka(robots_txt: str, ua: str, url: str) -> bool:
    """Čista odluka nad tekstom robots.txt (bez mreže)."""
    rp = urllib.robotparser.RobotFileParser()
    rp.parse((robots_txt or "").splitlines())
    return rp.can_fetch(ua, url)


def _robots_dozvoljava(url: str, ua: str) -> bool:
    """Povuci robots.txt NAŠIM deklarisanim UA (kao F6 web adapter), pa odluči.

    RobotFileParser.read() koristi podrazumevani Python-urllib UA, koji mnogi
    sajtovi (npr. Wikimedia) vraćaju 403 → lažna zabrana. Zato fetch ide našim UA.
    401/403 na sam robots.txt = izričita zabrana botova; 404/greška = nema robots
    (dozvoljeno).
    """
    parts = urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    req = urllib.request.Request(robots_url, headers={"User-Agent": ua})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            data = r.read(_MAX_BYTES).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code not in (401, 403)  # 401/403 → zabrana; ostalo → dozvoljeno
    except Exception:
        return True  # robots.txt nedostupan → nije zabrana
    return _robots_odluka(data, ua, url)


def preuzmi(url: str) -> str:
    """Bezbedno preuzmi HTML javnog URL-a (SSRF + robots + cap). Vraća tekst."""
    proveri_bezbedan(url)
    ua = _ua()
    if not _robots_dozvoljava(url, ua):
        raise UvozError("robots.txt zabranjuje čitanje ovog URL-a.")
    req = urllib.request.Request(url, headers={
        "User-Agent": ua, "Accept-Language": "sr-RS,sr;q=0.9,en;q=0.7"})
    opener = urllib.request.build_opener(_SigurniRedirekt())
    try:
        with opener.open(req, timeout=_TIMEOUT) as r:
            ctype = (r.headers.get_content_type() or "").lower()
            if "html" not in ctype and "text" not in ctype:
                raise UvozError(f"Nije HTML/tekst (content-type: {ctype or '?'}).")
            raw = r.read(_MAX_BYTES + 1)
            charset = r.headers.get_content_charset() or "utf-8"
    except urllib.error.URLError as e:
        raise UvozError(f"Preuzimanje nije uspelo: {e}") from e
    if len(raw) > _MAX_BYTES:
        raise UvozError("Stranica je prevelika (> 5 MB).")
    return raw.decode(charset, errors="replace")


# --- HTML -> blokovi (stdlib, bez dodatne zavisnosti) ---

class _Izvlakac(HTMLParser):
    _SKIP = frozenset(("script", "style", "noscript", "nav", "header", "footer",
                       "aside", "form", "svg", "template", "iframe", "button"))
    _BLOK = frozenset(("p", "li", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6",
                       "article", "section", "td", "dd", "figcaption", "pre"))
    _HEAD = frozenset(("h1", "h2", "h3", "h4", "h5", "h6"))

    def __init__(self):
        super().__init__()
        self._skip = 0
        self._in_title = False
        self.naslov = ""
        self._buf: list[str] = []
        self._stack: list[str] = []
        self.delovi: list[tuple[str, str]] = []

    def _flush(self):
        text = _WS.sub(" ", "".join(self._buf)).strip()
        self._buf = []
        if text:
            tag = self._stack[-1] if self._stack else "p"
            self.delovi.append((tag, text))

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
            return
        if self._skip:
            return
        if tag == "title":
            self._in_title = True
            return
        if tag in self._BLOK:
            self._flush()
            self._stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self._SKIP:
            if self._skip:
                self._skip -= 1
            return
        if self._skip:
            return
        if tag == "title":
            self._in_title = False
            return
        if tag in self._BLOK:
            self._flush()
            if self._stack:
                self._stack.pop()

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.naslov += data
            return
        self._buf.append(data)


def naslov_i_blokovi(html: str) -> tuple[str, list[dict]]:
    """HTML -> (naslov, blokovi). Čista funkcija (bez mreže i baze)."""
    izvl = _Izvlakac()
    izvl.feed(html)
    izvl._flush()
    naslov = _WS.sub(" ", izvl.naslov).strip()
    full = " ".join(t for _tag, t in izvl.delovi)[:5000]
    lang, script = _skript_jezik(full)

    blocks: list[dict] = []
    heading_path: list[str] = []
    for tag, text in izvl.delovi:
        text = _WS.sub(" ", text).strip()
        if not text or not _znacajan(text):
            continue
        je_naslov = tag in _Izvlakac._HEAD
        if je_naslov:
            heading_path = [text[:220]]
        blocks.append({
            "block_id": f"blk_{len(blocks) + 1:06d}",
            "block_type": "heading" if je_naslov else "paragraph",
            "text": text, "language": lang, "order": len(blocks) + 1,
            "heading_path": list(heading_path),
            "source_page": None,
            "source_section": (heading_path[-1][:220] if heading_path else ""),
            "extraction_confidence": 0.5 if je_naslov else 0.7,
            "human_verified": False,
        })
    for i, b in enumerate(blocks):
        b["previous_block_id"] = blocks[i - 1]["block_id"] if i > 0 else ""
        b["next_block_id"] = blocks[i + 1]["block_id"] if i + 1 < len(blocks) else ""
        b["parent_section_id"] = ""
    return (naslov, blocks), lang, script


# --- upis (parse + baza; testabilno bez mreže) ---

def ugradi(url: str, html: str, *, naslov="", licenca="", naziv_licence="") -> LibriDocument:
    """Parsiraj HTML i upiši izvor+dokument+blokove. Bez mreže (html je dat)."""
    try:
        box = E.LicenseBox(licenca)
    except ValueError:
        dozvoljene = ", ".join(b.value for b in E.LicenseBox)
        raise UvozError(f"Nepoznata licenca {licenca!r}. Izbor: {dozvoljene}.") from None
    if box == E.LicenseBox.SLOBODNA and not naziv_licence.strip():
        raise UvozError("Licenca SLOBODNA mora da imenuje licencu (ADR-0059 §2).")

    checksum = hashlib.sha256(html.encode("utf-8", "replace")).hexdigest()
    postojeci = LibriDocument.objects.filter(checksum=checksum).first()
    if postojeci is not None:
        raise UvozError(f"Sadržaj je već uvezen: {postojeci.document_id}.")

    (html_naslov, blokovi), lang, script = naslov_i_blokovi(html)
    if not blokovi:
        raise UvozError("Iz stranice nije izvučen tekst (prazna ili ne-HTML stranica).")
    title = (naslov or html_naslov or url)[:300]

    with transaction.atomic():
        izvor = KnowledgeSource.objects.create(
            persona=None,
            source_kind=E.SourceKind.PUBLIC_WEB_SOURCE.value,
            title=title,
            uri=url,  # web izvor MORA imati uri (check constraint web_has_uri)
            trust_score=TRUST_PUBLIC_WEB,
            checksum=checksum,
            license_box=box.value,
            license_note=naziv_licence.strip(),
        )
        dok = LibriDocument.objects.create(
            source=izvor,
            document_id="web_" + checksum[:12],
            version_id=VERSION_ID,
            title=title,
            language=lang,
            script=script,
            pages=1,
            checksum=checksum,
            ingested_at=timezone.now(),
        )
        Block.objects.bulk_create([
            Block(
                document=dok, block_id=b["block_id"], version_id=VERSION_ID,
                block_type=b["block_type"], text=b["text"], language=b["language"],
                order=b["order"], heading_path=b["heading_path"],
                source_page=b["source_page"], source_section=b["source_section"],
                extraction_confidence=Decimal(str(b["extraction_confidence"])),
                human_verified=b["human_verified"],
                previous_block_id=b["previous_block_id"],
                next_block_id=b["next_block_id"], parent_section_id=b["parent_section_id"],
            )
            for b in blokovi
        ])

    from apps.libri import vektori
    vektori.embeduj(dok.blocks.all())
    return dok


def uvezi_url(url, *, naslov="", licenca="", naziv_licence="") -> LibriDocument:
    """Preuzmi javni URL i ugradi ga u sloj znanja. Diže UvozError na grešci."""
    html = preuzmi(url)
    return ugradi(url, html, naslov=naslov, licenca=licenca, naziv_licence=naziv_licence)

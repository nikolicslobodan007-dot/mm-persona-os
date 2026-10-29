"""Testovi uvoza javnog web izvora (ADR-0031 sloj 2, §4).

Mreža je odvojena od parsiranja+upisa: SSRF brana, HTML→blokovi parser i upis se
testiraju bez mreže (HTML se ubacuje kao tekst; bezbednost URL-a preko literalnih
IP-jeva i localhost-a, bez spoljnog DNS-a).
"""

from __future__ import annotations

import pytest

from apps.libri import uvoz_web
from apps.libri.uvoz import UvozError
from common import enums as E
from tests.conftest import requires_db

_HTML = (
    "<html><head><title>Naslov Strane</title></head>"
    "<body>"
    "<nav>Meni koji se preskace</nav>"
    "<script>var x = 1;</script>"
    "<h1>Glavni naslov teksta</h1>"
    "<p>Ovo je prvi pasus sa dovoljno teksta i samoglasnika.</p>"
    "<article><p>Drugi pasus unutar clanka takodje ima smisla.</p></article>"
    "<footer>Futer koji se preskace</footer>"
    "</body></html>"
)


# ---- SSRF brana ----

@pytest.mark.parametrize("url", [
    "http://127.0.0.1/",
    "http://10.0.0.1/",
    "http://192.168.1.5/admin",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
    "ftp://example.com/x",
    "file:///etc/passwd",
    "http:///nema-host",
])
def test_proveri_bezbedan_odbija_opasno(url):
    with pytest.raises(UvozError):
        uvoz_web.proveri_bezbedan(url)


@pytest.mark.parametrize("url", ["http://8.8.8.8/", "https://93.184.216.34/strana"])
def test_proveri_bezbedan_pusta_javne_literalne(url):
    uvoz_web.proveri_bezbedan(url)   # javni literalni IP → ne diže


def test_proveri_bezbedan_localhost_blokiran():
    with pytest.raises(UvozError):
        uvoz_web.proveri_bezbedan("http://localhost/")


# ---- HTML → blokovi (čista funkcija) ----

def test_parser_izvlaci_naslov_i_blokove():
    (naslov, blokovi), lang, script = uvoz_web.naslov_i_blokovi(_HTML)
    assert naslov == "Naslov Strane"
    tekstovi = [b["text"] for b in blokovi]
    assert "Glavni naslov teksta" in tekstovi
    assert any("prvi pasus" in t for t in tekstovi)
    assert any("Drugi pasus" in t for t in tekstovi)
    assert all("preskace" not in t for t in tekstovi)   # nav/footer/script izbačeni
    glave = [b for b in blokovi if b["block_type"] == "heading"]
    assert glave and glave[0]["text"] == "Glavni naslov teksta"
    pasusi = [b for b in blokovi if b["block_type"] == "paragraph"]
    assert pasusi[0]["heading_path"] == ["Glavni naslov teksta"]
    assert pasusi[0]["source_page"] is None               # web nema strane


def test_parser_prazna_stranica_nema_blokova():
    (naslov, blokovi), _lang, _script = uvoz_web.naslov_i_blokovi(
        "<html><body></body></html>")
    assert blokovi == []


# ---- upis (bez mreže) ----

@requires_db
@pytest.mark.django_db
def test_ugradi_pravi_javni_izvor_i_blokove(db):
    dok = uvoz_web.ugradi("https://primer.rs/clanak", _HTML, licenca="NEPOZNATA")
    assert dok.document_id.startswith("web_")
    assert dok.source.source_kind == E.SourceKind.PUBLIC_WEB_SOURCE.value
    assert dok.source.trust_score == uvoz_web.TRUST_PUBLIC_WEB
    assert dok.source.license_box == "NEPOZNATA"
    assert dok.blocks.count() >= 3


@requires_db
@pytest.mark.django_db
def test_ugradi_dedup_isti_sadrzaj(db):
    uvoz_web.ugradi("https://primer.rs/a", _HTML, licenca="NEPOZNATA")
    with pytest.raises(UvozError, match="već uvezen"):
        uvoz_web.ugradi("https://primer.rs/b", _HTML, licenca="NEPOZNATA")


@requires_db
@pytest.mark.django_db
def test_ugradi_losa_licenca_pada(db):
    with pytest.raises(UvozError, match="licenca"):
        uvoz_web.ugradi("https://primer.rs/x", _HTML, licenca="IZMISLJENA")


@requires_db
@pytest.mark.django_db
def test_ugradi_slobodna_bez_naziva_pada(db):
    with pytest.raises(UvozError, match="SLOBODNA"):
        uvoz_web.ugradi("https://primer.rs/y", _HTML, licenca="SLOBODNA")


# ---- robots.txt odluka (čista, bez mreže) ----

def test_robots_odluka_dozvoljava_i_zabranjuje():
    r = "User-agent: *\nDisallow: /private/\n"
    assert uvoz_web._robots_odluka(r, "MMBot/1.0", "https://x.rs/wiki/Furnir") is True
    assert uvoz_web._robots_odluka(r, "MMBot/1.0", "https://x.rs/private/tajna") is False


def test_robots_odluka_prazno_dozvoljava():
    assert uvoz_web._robots_odluka("", "MMBot/1.0", "https://x.rs/a") is True


def test_robots_odluka_zabrani_sve():
    r = "User-agent: *\nDisallow: /\n"
    assert uvoz_web._robots_odluka(r, "MMBot/1.0", "https://x.rs/a") is False

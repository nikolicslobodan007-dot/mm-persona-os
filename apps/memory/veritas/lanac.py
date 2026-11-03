"""Veritas lanac — od tvrdnje do verdikta. Slice 4.

Jedan tok koji dele `veritas_proveri` i `veritas_klip`:
svedoci (prvoručni) → pretraga izvora (Brave) → dohvat svakog (Libri uvoz_web,
SSRF/robots brane) → Gateway oceni stav izvora → verdikt po pet osa.

`proveri_tvrdnju` vraća strukturu; ispis radi pozivalac preko `na_dogadjaj`
povratne veze, pa isti tok daje i CLI izlaz `veritas_proveri` i red po tvrdnji
u `veritas_klip`. `--suvo` svuda znači bez mreže i troška.
"""

from __future__ import annotations

from collections.abc import Callable

from apps.memory.veritas import pretraga, sud, verdikt


def nadji_izvore(tvrdnja: str, maks: int, suvo: bool) -> list[str]:
    """URL-ovi kandidati za tvrdnju (Brave, ili lažni u suvom). Pretraga sme da padne —
    pozivalac (`proveri_tvrdnju`) hvata grešku i nastavlja bez izvora."""
    trazi = pretraga._lazni if suvo else pretraga.pretrazi
    return [k["url"] for k in trazi(tvrdnja, maks)]


def _dohvati(url: str, suvo: bool) -> str | None:
    if suvo:
        return "(suvo — bez dohvata)"
    from apps.libri import uvoz_web
    try:
        uvoz_web.proveri_bezbedan(url)
        return uvoz_web.preuzmi(url)
    except Exception:  # noqa: BLE001 — dohvat sme da padne po izvoru
        return None


def proveri_tvrdnju(
    tvrdnja: str,
    *,
    llm,
    maks_izvora: int = 5,
    suvo: bool = False,
    pretrazi: bool = True,
    svedoci: list[dict] | None = None,
    dodatni_urlovi: list[str] | None = None,
    na_dogadjaj: Callable[[str, dict], None] | None = None,
) -> dict:
    """Vrati {"verdikt": <dict verdikt.oceni_tvrdnju>, "kandidati": [url]}.

    `svedoci`: [{"vrsta": "svedok"|"svedok_snimak", "opis": str}].
    `na_dogadjaj(tip, podaci)`: 'svedok' | 'pretraga' | 'pretraga_pala' |
    'izvor' | 'izvor_preskocen' — za ispis; bez njega tok radi tiho.
    """
    def javi(tip: str, podaci: dict) -> None:
        if na_dogadjaj:
            na_dogadjaj(tip, podaci)

    izvori: list[dict] = []
    videno: set[str] = set()

    for i, sv in enumerate(svedoci or []):
        vrsta = sv.get("vrsta", "svedok")
        ident = f"{vrsta}-{i}"
        izvori.append({"vrsta": vrsta, "stav": verdikt.POTVRDJUJE, "id": ident})
        videno.add(ident)
        javi("svedok", {"vrsta": vrsta, "opis": sv.get("opis", "")})

    urlovi: list[str] = list(dodatni_urlovi or [])
    kandidati: list[str] = []
    if pretrazi and maks_izvora > 0:
        try:
            kandidati = nadji_izvore(tvrdnja, maks_izvora, suvo)
        except Exception as e:  # noqa: BLE001
            javi("pretraga_pala", {"greska": str(e)})
            kandidati = []
        else:
            javi("pretraga", {"kandidati": kandidati})
        urlovi += kandidati

    for url in urlovi:
        if url in videno:
            continue
        videno.add(url)
        tekst = _dohvati(url, suvo)
        if tekst is None:
            javi("izvor_preskocen", {"url": url, "razlog": "ne mogu da dohvatim"})
            continue
        ocena = sud.oceni_izvor(tvrdnja, tekst, llm)
        if not ocena or ocena["stav"] == "ne_pominje":
            javi("izvor_preskocen", {"url": url, "razlog": "ne pominje tvrdnju"})
            continue
        izvori.append({"vrsta": "web", "stav": ocena["stav"], "id": url})
        javi("izvor", {"url": url, "stav": ocena["stav"],
                       "obrazlozenje": ocena.get("obrazlozenje", "")})

    return {"verdikt": verdikt.oceni_tvrdnju(tvrdnja, izvori), "kandidati": kandidati}

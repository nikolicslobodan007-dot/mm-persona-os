"""WK — orkestracija „Sakupljenih vrata" (ADR-0074 nastavak).

Spaja tri sloja u jedan gated tok, tačno po nacrtu:

    izvor (URL/video/tekst)
      → PROVERA DOZVOLA (knowledge.collect + web.read_public)
      → DOHVAT (wk_dohvat: trafilatura / yt-dlp+whisper)   → čist tekst
      → DESTILACIJA (wk_destilacija: osnova + LLM pojačalo) → PREDLOG veština
      → GATING (Meta-revizija → kontrolisano → GO)          → AKTIVNO

NAČELO (ADR-0074): PREDLOG NE STIŽE AGENTIMA. Sakupljena veština je
`PUBLIC_WEB_SOURCE` i nije `SLOBODNA` kutija — `context.py` je ionako ne pakuje
dok ne postane `AKTIVNO`. Ovaj sloj to čini EKSPLICITNIM i NEZAOBILAZNIM:
jedini put do AKTIVNO vodi kroz PREDLOG → PRIHVACENO → KONTROLISANO → AKTIVNO,
svaki prelaz zapisan u dnevnik (ko, kad, odluka). Ne može se preskočiti.

Sve zavisnosti su UBRIZGANE (dohvat, llm) → logika se 100% testira bez mreže,
bez LLM-a, bez kvote. Produkciono vezivanje za Django (`apps/memory/vestine.py`,
`uvoz_web`, F7 Gateway, dozvole iz `common/enums.py`) ide u zasebnom koraku;
ovde je čista, prenosiva srž orkestracije i životnog ciklusa.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import wk_destilacija as DEST
import wk_pokazivac as POK

# --- Dozvole (ista imena kao common/enums.py) -------------------------------
DOZVOLA_SAKUPLJANJE = "knowledge.collect"   # upis u NAŠU memoriju
DOZVOLA_WEB = "web.read_public"             # čitanje tuđeg javnog sajta
POTREBNE_DOZVOLE = frozenset({DOZVOLA_SAKUPLJANJE, DOZVOLA_WEB})

# --- Životni ciklus sakupljene veštine --------------------------------------
PREDLOG = DEST.PREDLOG            # destilovano, čeka Meta-reviziju
PRIHVACENO = DEST.PRIHVACENO     # Meta GO prošao
KONTROLISANO = "KONTROLISANO_UZIVO"   # CONTROLLED_LIVE — proba pod nadzorom
AKTIVNO = "AKTIVNO"              # odobreno uživo → stiže agentima
ODBIJENO = DEST.ODBIJENO

# Dozvoljeni prelazi (sve ostalo je zabranjeno — nezaobilazno).
_PRELAZI = {
    PREDLOG: {PRIHVACENO, ODBIJENO},
    PRIHVACENO: {KONTROLISANO, ODBIJENO},
    KONTROLISANO: {AKTIVNO, ODBIJENO},
    AKTIVNO: set(),              # terminalno
    ODBIJENO: set(),             # terminalno
}

# Licenca — po proceni; podrazumevano NEPOZNATA (nacrt).
LICENCA_NEPOZNATA = "NEPOZNATA"


class PrelazGreska(ValueError):
    """Pokušaj nedozvoljenog prelaza stanja (npr. preskok na AKTIVNO)."""


@dataclass
class SakupljenaVestina:
    """Jedna veština kroz životni ciklus, sa dnevnikom odluka (governance)."""

    vestina: dict                       # {ime, koraci, napomene, pouzdanost}
    izvor: str                          # URL/opis izvora
    licenca: str = LICENCA_NEPOZNATA
    status: str = PREDLOG
    dnevnik: list = field(default_factory=list)

    def __post_init__(self):
        self._zapisi("nastala", ko="sistem", beleska="destilovano iz izvora")

    def _zapisi(self, dogadjaj: str, *, ko: str, beleska: str = ""):
        self.dnevnik.append({
            "vreme": round(time.time(), 3),
            "dogadjaj": dogadjaj,
            "ko": ko,
            "status": self.status,
            "beleska": beleska,
        })

    def _predji(self, u: str, *, ko: str, dogadjaj: str, beleska: str = ""):
        if u not in _PRELAZI.get(self.status, set()):
            raise PrelazGreska(
                f"zabranjen prelaz {self.status} → {u} "
                f"(dozvoljeno: {sorted(_PRELAZI.get(self.status, set())) or 'ništa'})"
            )
        self.status = u
        self._zapisi(dogadjaj, ko=ko, beleska=beleska)
        return self

    # --- Kapije (svaka beleži ko je odlučio) --------------------------------
    def meta_revizija(self, *, ko: str, go: bool, beleska: str = ""):
        """Meta-revizija (čovek ili Meta-agent): GO → PRIHVACENO, ne → ODBIJENO.
        Samo iz PREDLOG stanja."""
        cilj = PRIHVACENO if go else ODBIJENO
        return self._predji(cilj, ko=ko, dogadjaj="meta_revizija",
                            beleska=beleska or ("GO" if go else "odbijeno"))

    def pusti_kontrolisano(self, *, ko: str, beleska: str = ""):
        """Posle GO + kredencijala → proba pod nadzorom (CONTROLLED_LIVE).
        Kredencijal je u Slobodanovim rukama; ovde beležimo odobravaoca."""
        return self._predji(KONTROLISANO, ko=ko, dogadjaj="pusti_kontrolisano",
                            beleska=beleska)

    def odobri_uzivo(self, *, ko: str, beleska: str = ""):
        """GO uživo: KONTROLISANO → AKTIVNO (tek sad stiže agentima)."""
        return self._predji(AKTIVNO, ko=ko, dogadjaj="odobri_uzivo", beleska=beleska)

    def odbij(self, *, ko: str, razlog: str):
        """Odbij iz bilo kog ne-terminalnog stanja."""
        return self._predji(ODBIJENO, ko=ko, dogadjaj="odbij", beleska=razlog)

    @property
    def stize_agentima(self) -> bool:
        """Jedini uslov da context.py ovo spakuje: status == AKTIVNO."""
        return self.status == AKTIVNO

    def kao_korpus(self) -> dict:
        """Oblik za `korpus/vestine/*.json` / `vestine.uvezi` (tek kad je AKTIVNO)."""
        return dict(self.vestina)


# --- Podrazumevani adapter za dohvat (lazy import — bez mreže u testu) -------
def _dohvati_podrazumevano(izvor: str, tip: str, **kw) -> dict:
    """Mapira (izvor, tip) na wk_dohvat i normalizuje izlaz na {'ok','tekst'}."""
    import wk_dohvat as DOHVAT
    if tip == "video":
        r = DOHVAT.transkript_videa(izvor, **kw)
        if r.get("ok"):
            return {"ok": True, "tekst": r["transkript"]}
        return r
    r = DOHVAT.tekst_sa_weba(izvor, **kw)
    return r  # već {'ok','tekst'|'razlog'}


# --- Orkestracija -----------------------------------------------------------
def sakupi(
    izvor: str,
    *,
    tip: str = "web",
    dozvole,
    llm,
    dohvat_fn=None,
    izvor_opis: str | None = None,
    maks_vestina: int = 3,
    licenca: str = LICENCA_NEPOZNATA,
) -> dict:
    """Ceo tok do PREDLOG-a. Ništa se ne odobrava automatski.

    `dozvole`: skup dozvola agenta (mora sadržati obe POTREBNE_DOZVOLE).
    `llm`: callable(prompt)->str (F7 Gateway uživo; lažni u testu).
    `dohvat_fn`: callable(izvor, tip, **kw)->{'ok','tekst'|'razlog'}; podrazumevano
                 koristi wk_dohvat (lazy import). Ubrizgaj lažni za test bez mreže.

    Vraća {'ok', 'faza', 'predlozi'|'razlog'}. `predlozi` su SakupljenaVestina
    u stanju PREDLOG — čekaju meta_reviziju. Agentima NE stižu dok ne budu AKTIVNO.
    """
    # 1) Dozvole — bez obe, agent ne sme ni da krene.
    nedostaje = POTREBNE_DOZVOLE - set(dozvole or [])
    if nedostaje:
        return {"ok": False, "faza": "dozvole",
                "razlog": f"nedostaju dozvole: {sorted(nedostaje)}"}

    # 2) Dohvat → čist tekst.
    dohvat = dohvat_fn or _dohvati_podrazumevano
    rez = dohvat(izvor, tip)
    if not rez.get("ok"):
        return {"ok": False, "faza": "dohvat", "razlog": rez.get("razlog", "dohvat pao")}
    tekst = rez.get("tekst", "")

    # 3) Destilacija → PREDLOG veštine.
    opis = izvor_opis or izvor
    dest = DEST.destiluj(tekst, izvor_opis=opis, llm=llm, maks_vestina=maks_vestina)
    if not dest.get("ok"):
        return {"ok": False, "faza": "destilacija", "razlog": dest["razlog"]}

    # 4) Pakovanje u gated PREDLOG objekte (dnevnik počinje ovde).
    predlozi = [SakupljenaVestina(vestina=v, izvor=opis, licenca=licenca)
                for v in dest["vestine"]]
    return {"ok": True, "faza": "predlog", "predlozi": predlozi}


def _link_u_url(p: dict) -> str:
    """Normalizuj pokazivač-link na pun URL za dohvat."""
    v = p["vrednost"]
    if p["vrsta"] == "github":
        return f"https://github.com/{v}"
    if p["vrsta"] == "www":
        return f"https://{v}"
    return v  # već url


def sakupi_pametno(
    tekst: str,
    *,
    dozvole,
    llm,
    dohvat_fn=None,
    trazi_fn=None,
    izvor_opis: str | None = None,
    licenca: str = LICENCA_NEPOZNATA,
    maks_vestina: int = 3,
) -> dict:
    """Pametna vrata: tekst (transkript/opis) → detektor → put → PREDLOG veštine.

    Prvo `wk_pokazivac.analiziraj` odluči put, pa:
      - `destiluj`        → destiluj dati tekst direktno;
      - `prati_pokazivac` → dohvati prvi link (reuse `sakupi`) pa destiluj;
      - `trazi_izvor`     → `trazi_fn(tekst)` nađe URL, pa `sakupi` taj URL;
      - `preskoci`        → ništa (reklama/prazno).

    `trazi_fn`: callable(tekst)->url|None (web pretraga; ubrizgana, lažna u testu).
    Vraća {'ok','put','preporuka', ...}: na uspehu i 'predlozi' (PREDLOG veštine) + 'izvor'.
    """
    nedostaje = POTREBNE_DOZVOLE - set(dozvole or [])
    if nedostaje:
        return {"ok": False, "put": "dozvole",
                "razlog": f"nedostaju dozvole: {sorted(nedostaje)}"}

    nalaz = POK.analiziraj(tekst or "")
    put = nalaz["preporuka"]
    osnova = {"put": put, "preporuka": put, "obrazlozenje": nalaz["obrazlozenje"],
              "pokazivaci": nalaz["pokazivaci"]}

    if put == "preskoci":
        return {"ok": False, **osnova, "razlog": nalaz["obrazlozenje"]}

    if put == "destiluj":
        opis = izvor_opis or "tekst"
        dest = DEST.destiluj(tekst, izvor_opis=opis, llm=llm, maks_vestina=maks_vestina)
        if not dest["ok"]:
            return {"ok": False, **osnova, "faza": "destilacija", "razlog": dest["razlog"]}
        predlozi = [SakupljenaVestina(vestina=v, izvor=opis, licenca=licenca)
                    for v in dest["vestine"]]
        return {"ok": True, **osnova, "izvor": opis, "predlozi": predlozi}

    # prati_pokazivac / trazi_izvor → svedi na URL, pa reuse sakupi()
    if put == "prati_pokazivac":
        linkovi = [p for p in nalaz["pokazivaci"] if p["vrsta"] in ("url", "github", "www")]
        url = _link_u_url(linkovi[0])
    else:  # trazi_izvor
        trazi = trazi_fn
        if trazi is None:                 # podrazumevano: živa pretraga (van proxy-ja)
            import wk_pretraga as PRET
            trazi = PRET.trazi_izvor
        url = trazi(tekst)
        if not url:
            return {"ok": False, **osnova, "razlog": "trazi_izvor: pretraga nije našla izvor"}

    rez = sakupi(url, tip="web", dozvole=dozvole, llm=llm, dohvat_fn=dohvat_fn,
                 izvor_opis=url, licenca=licenca, maks_vestina=maks_vestina)
    if not rez["ok"]:
        return {"ok": False, **osnova, "izvor": url,
                "faza": rez.get("faza"), "razlog": rez["razlog"]}
    return {"ok": True, **osnova, "izvor": url, "predlozi": rez["predlozi"]}


if __name__ == "__main__":
    import json

    def lazni_llm(_p):
        return json.dumps([{
            "ime": "Kako kvalifikovati lead",
            "koraci": ["Proveri da li ima budžet i potrebu.",
                       "Utvrdi ko donosi odluku.",
                       "Dogovori sledeći konkretan korak."],
            "pouzdanost": 0.8,
        }], ensure_ascii=False)

    def lazni_dohvat(izvor, tip):
        return {"ok": True, "tekst": ("Kvalifikacija leada ide ovako. Prvo proveri "
                "budžet i potrebu. Zatim nađi donosioca odluke. Na kraju zakaži "
                "sledeći korak. Dovoljno teksta za prag destilacije.")}

    out = sakupi("https://primer.test/prodaja", tip="web",
                 dozvole={DOZVOLA_SAKUPLJANJE, DOZVOLA_WEB},
                 llm=lazni_llm, dohvat_fn=lazni_dohvat)
    print("sakupi:", out["ok"], out["faza"])
    v = out["predlozi"][0]
    print("status po sakupljanju:", v.status, "| stiže agentima:", v.stize_agentima)
    v.meta_revizija(ko="Slobodan", go=True)
    v.pusti_kontrolisano(ko="Slobodan")
    v.odobri_uzivo(ko="Slobodan")
    print("status posle GO:", v.status, "| stiže agentima:", v.stize_agentima)
    print("dnevnik:")
    for d in v.dnevnik:
        print("  ", d["dogadjaj"], "→", d["status"], "(", d["ko"], ")")

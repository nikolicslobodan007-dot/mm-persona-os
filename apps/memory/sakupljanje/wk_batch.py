"""WK — batch runner „Sakupljenih vrata" (cela lista izvora → korpus).

Krajnji cilj: agent čita svoju FB kolekciju „Zadaci za AI Agente" i obrađuje svaki
unos redom. Ovaj modul je ta petlja: za svaki zadatak pribavi TEKST pa ga pusti
kroz pametna vrata (`wk_sakupljanje.sakupi_pametno`), skupi PREDLOG veštine i
napravi izveštaj po stavci (koji put, koliko veština, ili zašto preskočeno).

Zadatak (jedan unos liste) je jedan od:
- {"vrsta": "tekst",  "tekst": "...", "izvor": "opis"}  — tekst već u ruci
  (caption/transkript).
- {"vrsta": "video",  "izvor": "<url|fajl>"}            — prvo transkript (wk_dohvat).
- {"vrsta": "web",    "izvor": "<url>"}                 — prvo dohvat teksta (wk_dohvat).

Robustno: pad jedne stavke (npr. nedostupan video) se zabeleži i petlja ide dalje.
Sve spoljne funkcije su UBRIZGANE (llm, dohvat_fn, transkript_fn, trazi_fn) → ceo
batch se testira bez mreže/LLM/kvote.
"""

from __future__ import annotations

import wk_sakupljanje as S


def _pribavi_tekst(z: dict, *, dohvat_fn, transkript_fn) -> dict:
    """Vrati {'ok','tekst','izvor'} ili {'ok':False,'razlog','izvor'} za jedan zadatak."""
    vrsta = (z.get("vrsta") or "tekst").lower()
    izvor = z.get("izvor") or "tekst"
    if vrsta == "tekst":
        t = z.get("tekst") or ""
        if not t.strip():
            return {"ok": False, "razlog": "prazan tekst", "izvor": izvor}
        return {"ok": True, "tekst": t, "izvor": izvor}
    if vrsta == "video":
        tf = transkript_fn or _zivi_transkript
        r = tf(izvor)
        if r.get("ok"):
            return {"ok": True, "tekst": r.get("transkript", ""), "izvor": izvor}
        return {"ok": False, "razlog": f"transkript: {r.get('razlog','pao')}", "izvor": izvor}
    if vrsta == "web":
        df = dohvat_fn or S._dohvati_podrazumevano
        r = df(izvor, "web")
        if r.get("ok"):
            return {"ok": True, "tekst": r.get("tekst", ""), "izvor": izvor}
        return {"ok": False, "razlog": f"dohvat: {r.get('razlog','pao')}", "izvor": izvor}
    return {"ok": False, "razlog": f"nepoznata vrsta: {vrsta}", "izvor": izvor}


def _zivi_transkript(izvor: str) -> dict:
    """Podrazumevani živi transkript (wk_dohvat). Van proxy-ja (PC/server)."""
    import wk_dohvat as DOHVAT
    return DOHVAT.transkript_videa(izvor, jezik=None)


def obradi_zadatke(
    zadaci,
    *,
    dozvole,
    llm,
    dohvat_fn=None,
    transkript_fn=None,
    trazi_fn=None,
    maks_vestina: int = 3,
) -> dict:
    """Obradi celu listu zadataka. Vraća izveštaj + sve PREDLOG veštine.

    Rezultat: {
      'ukupno': int, 'uspesno': int,
      'po_zadatku': [{izvor, vrsta, put, ok, broj_vestina, razlog?}],
      'predlozi': [SakupljenaVestina, ...],   # svi PREDLOZI iz celog batcha
      'zbir_putanja': {destiluj: n, prati_pokazivac: n, trazi_izvor: n, preskoci: n, ...},
    }
    """
    po_zadatku = []
    svi_predlozi = []
    zbir = {}

    for z in (zadaci or []):
        vrsta = (z.get("vrsta") or "tekst").lower()
        pt = _pribavi_tekst(z, dohvat_fn=dohvat_fn, transkript_fn=transkript_fn)
        if not pt["ok"]:
            stavka = {"izvor": pt["izvor"], "vrsta": vrsta, "put": "dohvat",
                      "ok": False, "broj_vestina": 0, "razlog": pt["razlog"]}
            po_zadatku.append(stavka)
            zbir["dohvat_pao"] = zbir.get("dohvat_pao", 0) + 1
            continue

        rez = S.sakupi_pametno(
            pt["tekst"], dozvole=dozvole, llm=llm, dohvat_fn=dohvat_fn,
            trazi_fn=trazi_fn, izvor_opis=pt["izvor"], maks_vestina=maks_vestina,
        )
        put = rez.get("put", "?")
        zbir[put] = zbir.get(put, 0) + 1
        predlozi = rez.get("predlozi", []) if rez.get("ok") else []
        svi_predlozi.extend(predlozi)
        po_zadatku.append({
            "izvor": rez.get("izvor", pt["izvor"]), "vrsta": vrsta, "put": put,
            "ok": bool(rez.get("ok")), "broj_vestina": len(predlozi),
            **({"razlog": rez["razlog"]} if not rez.get("ok") and rez.get("razlog") else {}),
        })

    uspesno = sum(1 for s in po_zadatku if s["ok"])
    return {"ukupno": len(po_zadatku), "uspesno": uspesno,
            "po_zadatku": po_zadatku, "predlozi": svi_predlozi, "zbir_putanja": zbir}


def odobri_sve(predlozi, *, ko: str, beleska: str = "batch GO"):
    """Provuče sve PREDLOGE kroz kapije do AKTIVNO (Slobodanovo odobrenje). Vrati aktivne."""
    aktivne = []
    for v in predlozi:
        v.meta_revizija(ko=ko, go=True, beleska=beleska)
        v.pusti_kontrolisano(ko=ko, beleska=beleska)
        v.odobri_uzivo(ko=ko, beleska=beleska)
        aktivne.append(v)
    return aktivne


def korpus_iz(predlozi) -> list[dict]:
    """Oblik za korpus/vestine/*.json — samo AKTIVNE veštine."""
    return [v.kao_korpus() for v in predlozi if v.stize_agentima]


if __name__ == "__main__":
    import json

    def llm(_p):
        return json.dumps([{"ime": "Primer veština",
                            "koraci": ["Prvi korak.", "Drugi korak."],
                            "pouzdanost": 0.8}], ensure_ascii=False)

    def dohvat(izvor, tip):
        return {"ok": True, "tekst": ("Postupak. Prvo A. Zatim B. Na kraju C. "
                "Dovoljno dugačak tekst za prag destilacije.")}

    def transkript(izvor):
        return {"ok": True, "transkript": ("A free guide. Comment HOWTO and I will "
                "send you the repo on github.com/luongnv89/claude-howto.")}

    zadaci = [
        {"vrsta": "tekst", "izvor": "clanak-1",
         "tekst": "Uradi ovako. Prvo istraži. Zatim pripremi. Na kraju pošalji. Dovoljno teksta."},
        {"vrsta": "video", "izvor": "fb-klip-1"},       # promo → prati github link iz transkripta
        {"vrsta": "web", "izvor": "https://primer.rs/clanak"},
        {"vrsta": "tekst", "izvor": "reklama", "tekst": "Kupi odmah! Najbolje ikad! Ne propusti!"},
    ]
    r = obradi_zadatke(zadaci, dozvole={S.DOZVOLA_SAKUPLJANJE, S.DOZVOLA_WEB},
                       llm=llm, dohvat_fn=dohvat, transkript_fn=transkript)
    print(f"ukupno={r['ukupno']} uspešno={r['uspesno']} zbir={r['zbir_putanja']}")
    for s in r["po_zadatku"]:
        print(f"  {s['izvor']:28} vrsta={s['vrsta']:6} put={s['put']:16} "
              f"veština={s['broj_vestina']}" + (f"  ({s.get('razlog','')})" if not s['ok'] else ""))
    aktivne = odobri_sve(r["predlozi"], ko="Slobodan")
    print(f"AKTIVNIH posle GO: {len(korpus_iz(aktivne))}")

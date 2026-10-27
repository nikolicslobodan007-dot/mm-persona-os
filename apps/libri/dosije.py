"""Dosije dokumenta — izlaz za čoveka (ADR-0031 sloj 4c, §3.4).

Sastavlja istraživački dosije od onoga što već imamo u Libri: blokovi (sloj 2),
tvrdnje (4a), entiteti + odnosi + dvostruko vreme (4b) i pouzdanost po 5 osa (4b+).
Dvanaest sekcija po Veritas prototipu (`veritas_dosije.py`), sa ispravljenom
numeracijom (prototip preskače 11) — sekcija 11 je Hronologija iz dvostrukog vremena.

**Deterministički, bez LLM (Canon §21).** Sekcije koje traže zaključivanje —
9. Konkurentske hipoteze, 10. Otvorena pitanja — ostaju „—" dok ne uđe LLM sloj;
ništa se ne izmišlja. Dosije je IZVEDEN dokument (ne čuva se u bazi): komanda ga
ispiše. Ne bira pobednika među protivrečnim tvrdnjama (ADR-0006 §3) — Kontradikcije
se samo navedu.
"""

from __future__ import annotations

from typing import Any

TVRDNJA_PREDIKAT = "libri.tvrdnja"


def _datum(dt) -> str:
    return dt.date().isoformat() if dt else "?"


def _prikupi(document) -> dict[str, Any]:
    """Prikupi sve podatke za dosije iz baze (jedini deo koji dira ORM)."""
    from apps.libri.models import Entitet, Odnos
    from apps.memory.models import KnowledgeFact

    try:
        from apps.libri.models import OcenaTvrdnje
    except ImportError:  # pragma: no cover
        OcenaTvrdnje = None

    izvor = document.source
    blokovi = list(document.blocks.all())
    po_bloku = {b.block_id: b for b in blokovi}

    tvrdnje = []
    if izvor is not None:
        for f in KnowledgeFact.objects.filter(source=izvor, predicate=TVRDNJA_PREDIKAT):
            oj = f.object_json or {}
            tvrdnje.append({
                "subject": f.subject, "relacija": oj.get("relacija", ""),
                "vrednost": oj.get("vrednost", ""), "block_id": oj.get("block_id", ""),
            })

    entiteti = list(Entitet.objects.filter(source=izvor)) if izvor else []
    akteri = [{"name": e.name, "kind": e.kind} for e in entiteti
              if e.kind in ("osoba", "organizacija")]
    dogadjaji = [{"name": e.name, "desilo_se": e.desilo_se, "objavljeno": e.objavljeno}
                 for e in entiteti if e.kind == "dogadjaj"]

    odnosi = []
    if izvor is not None:
        for o in Odnos.objects.filter(source=izvor).select_related("subject", "object"):
            odnosi.append({"subject": o.subject.name, "tip": o.relation_type,
                           "confidence": float(o.confidence), "object": o.object.name})

    ose = {"pouzdanost": 0.0, "nezavisnost": 0.0, "blizina": 0.0,
           "potkrepljenost": 0.0, "stabilnost": 0.0, "ukupno": 0.0, "broj": 0}
    kontradikcije = []
    if OcenaTvrdnje is not None and izvor is not None:
        ocene = list(OcenaTvrdnje.objects.filter(fact__source=izvor).select_related("fact"))
        for oc in ocene:
            for k in ("pouzdanost", "nezavisnost", "blizina", "potkrepljenost",
                      "stabilnost", "ukupno"):
                ose[k] += float(getattr(oc, k))
            if float(oc.stabilnost) < 1.0:
                kontradikcije.append({"subject": oc.fact.subject,
                                      "stabilnost": round(float(oc.stabilnost), 3)})
        ose["broj"] = len(ocene)
        if ocene:
            for k in ("pouzdanost", "nezavisnost", "blizina", "potkrepljenost",
                      "stabilnost", "ukupno"):
                ose[k] = round(ose[k] / len(ocene), 3)

    # Dokazi: blokovi koje tvrdnje citiraju (izvod + strana), bez duplikata.
    dokazi = []
    for bid in dict.fromkeys(t["block_id"] for t in tvrdnje if t["block_id"]):
        b = po_bloku.get(bid)
        if b is None:
            continue
        isecak = " ".join((b.text or "").split())[:160]
        dokazi.append({"block_id": bid, "strana": b.source_page, "citat": isecak})

    hronologija = sorted(
        [d for d in dogadjaji if d["desilo_se"] or d["objavljeno"]],
        key=lambda d: (d["desilo_se"] or d["objavljeno"]))

    return {
        "naslov": document.title, "document_id": document.document_id,
        "poreklo": (izvor.title if izvor else "(bez izvora)"),
        "blokova": len(blokovi), "tvrdnje": tvrdnje, "akteri": akteri,
        "dogadjaji": dogadjaji, "dokazi": dokazi, "odnosi": odnosi,
        "pouzdanost": ose, "kontradikcije": kontradikcije, "hronologija": hronologija,
    }


def _markdown(p: dict[str, Any]) -> str:
    """Čisto formatiranje dosija iz prikupljenih podataka (bez baze — testabilno)."""
    L: list[str] = []
    L.append(f"# DOSIJE: {p['naslov']}")
    L.append("")
    L.append(f"**Poreklo:** {p['poreklo']}  ")
    L.append(f"**Dokument:** {p['document_id']}  ")
    L.append(f"**Blokova:** {p['blokova']}")
    L.append("")

    L.append("## 1. Sažetak")
    L.append(
        f"Dokument „{p['naslov']}” ({p['blokova']} blokova). Izvučeno: "
        f"{len(p['tvrdnje'])} tvrdnji, {len(p['akteri'])} aktera, "
        f"{len(p['dogadjaji'])} događaja, {len(p['odnosi'])} odnosa.")
    L.append("")

    L.append("## 2. Glavne tvrdnje")
    if p["tvrdnje"]:
        for t in p["tvrdnje"]:
            rep = f"{t['subject']} {t['relacija']} {t['vrednost']}".strip()
            blk = f"  _(blok {t['block_id']})_" if t["block_id"] else ""
            L.append(f"- {rep}{blk}")
    else:
        L.append("—")
    L.append("")

    L.append("## 3. Akteri")
    if p["akteri"]:
        for a in p["akteri"]:
            L.append(f"- **{a['name']}** ({a['kind']})")
    else:
        L.append("—")
    L.append("")

    L.append("## 4. Događaji")
    if p["dogadjaji"]:
        for d in p["dogadjaji"]:
            L.append(f"- {d['name']} — desilo: {_datum(d['desilo_se'])} | "
                     f"objavljeno: {_datum(d['objavljeno'])}")
    else:
        L.append("—")
    L.append("")

    L.append("## 5. Dokazi")
    if p["dokazi"]:
        for dk in p["dokazi"]:
            strana = f", str. {dk['strana']}" if dk["strana"] else ""
            L.append(f"- „{dk['citat']}”  _(blok {dk['block_id']}{strana})_")
    else:
        L.append("—")
    L.append("")

    o = p["pouzdanost"]
    L.append("## 6. Pouzdanost izvora")
    if o["broj"]:
        L.append(f"Prosek po {o['broj']} tvrdnji (0–1):")
        L.append(f"- pouzdanost {o['pouzdanost']} · nezavisnost {o['nezavisnost']} · "
                 f"blizina {o['blizina']} · potkrepljenost {o['potkrepljenost']} · "
                 f"stabilnost {o['stabilnost']}")
        L.append(f"- **ukupno: {o['ukupno']}**")
    else:
        L.append("— (nema ocena; pokreni `libri pouzdanost`)")
    L.append("")

    L.append("## 7. Kontradikcije")
    if p["kontradikcije"]:
        for k in p["kontradikcije"]:
            L.append(f"- **{k['subject']}** — stabilnost {k['stabilnost']} "
                     "(postoji protivrečan izvor; pobednik se ne bira)")
    else:
        L.append("— (nema protivrečnih izvora)")
    L.append("")

    L.append("## 8. Mreža odnosa")
    if p["odnosi"]:
        for r in p["odnosi"]:
            L.append(f"- {r['subject']} —[{r['tip']}, {r['confidence']}]→ {r['object']}")
    else:
        L.append("—")
    L.append("")

    L.append("## 9. Konkurentske hipoteze")
    L.append("— (dolazi sa LLM slojem; deterministička osnova ne izvodi hipoteze)")
    L.append("")

    L.append("## 10. Otvorena pitanja")
    L.append("— (dolazi sa LLM slojem)")
    L.append("")

    L.append("## 11. Hronologija")
    if p["hronologija"]:
        for h in p["hronologija"]:
            L.append(f"- {_datum(h['desilo_se'])}: {h['name']} "
                     f"(objavljeno {_datum(h['objavljeno'])})")
    else:
        L.append("— (nema datiranih događaja)")
    L.append("")

    L.append("## 12. Upozorenje")
    L.append("- Deterministička osnova (Canon §21): tvrdnje/entiteti/odnosi/ocene su "
             "donja granica pre LLM sloja.")
    L.append("- Tvrdnje su OBSERVED iz izvora, ne INFERRED — ništa se ne izmišlja "
             "(Canon §10.4).")
    L.append("- READY/ACTIVE i SIMULATION/LIVE nisu dokaz da agent trenutno radi.")
    L.append("")
    return "\n".join(L)


def sastavi(document) -> str:
    """Sastavi markdown dosije dokumenta (prikupljanje + formatiranje)."""
    return _markdown(_prikupi(document))

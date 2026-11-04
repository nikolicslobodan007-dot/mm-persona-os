"""Veritas izlaz — zajednički prikaz: tekst → nalazi (tri sloja) → (verdikt). Slice 3.1.

Isti blok dele `veritas_klip` (zvuk) i `veritas_slika` (OCR): kad imaš tekst,
izvuci nalaze i, ako je traženo, proveri svaku tvrdnju kroz `lanac`. Ispis ide
na `cmd.stdout`/`cmd.style` prosleđene komande, pa nema duplikata po komandama.
"""

from __future__ import annotations


def prikazi_nalaze(cmd, tekst: str, o: dict) -> None:
    """Izvuci i ispiši nalaze iz `tekst`; uz o["proveri"] donesi verdikt po tvrdnji."""
    from apps.memory.veritas import nalaz

    if not (tekst or "").strip():
        cmd.stdout.write("Prazan tekst — nema šta da se izvuče.")
        return

    llm = nalaz._lazni_llm if o["suvo"] else nalaz.napravi_llm()
    nalazi = nalaz.izvuci_nalaze(tekst, llm, o["maks_nalaza"])
    if not nalazi:
        cmd.stdout.write("Nema izdvojenih nalaza.")
        return

    cmd.stdout.write(f"# {len(nalazi)} nalaz(a):")
    for i, n in enumerate(nalazi, 1):
        cmd.stdout.write(
            f"— Nalaz {i} [{n.get('tehnika', '?')}] pouzdanost {n.get('pouzdanost', '?')}")
        cmd.stdout.write(f"   doslovno:    {n.get('doslovna', '')}")
        cmd.stdout.write(f"   implicirano: {n.get('implicirana', '')}")
        cmd.stdout.write(f"   za proveru:  {n.get('za_proveru', '')}")

    if o.get("proveri"):
        _proveri(cmd, nalazi, o)


def _proveri(cmd, nalazi, o):
    from apps.memory.veritas import lanac, sud

    sud_llm = sud._lazni_llm if o["suvo"] else sud.napravi_llm()
    koliko = min(o["maks_tvrdnji"], len(nalazi))
    cmd.stdout.write("")
    cmd.stdout.write(cmd.style.MIGRATE_HEADING(f"## Provera {koliko} tvrdnje/a:"))
    for i, n in enumerate(nalazi[:koliko], 1):
        tvrdnja = (n.get("doslovna") or "").strip()
        if not tvrdnja:
            continue
        cmd.stdout.write("")
        cmd.stdout.write(f"[{i}] {tvrdnja}")
        rez = lanac.proveri_tvrdnju(
            tvrdnja, llm=sud_llm, maks_izvora=o["maks_izvora"], suvo=o["suvo"],
            pretrazi=True, na_dogadjaj=lambda t, d: _kratko(cmd, t, d))
        r = rez["verdikt"]
        red = (f"    VERDIKT: {r['verdikt']} (izvora {r['izvori']}, "
               f"saglasnih {r['saglasnih']}, protivrečnih {r['protivrecnih']})")
        if r.get("ose"):
            red += f" · ukupno {r['ose']['ukupno']}"
        cmd.stdout.write(cmd.style.SUCCESS(red))
        if r.get("sporno_tumacenje"):
            cmd.stdout.write(cmd.style.WARNING(
                f"    tumačenje sporno ({r['sporno_tumacenje']}) — izrečeno potvrđeno, "
                "značenje osporeno."))


def _kratko(cmd, tip, d):
    if tip == "pretraga":
        cmd.stdout.write(f"    pretraga: {len(d['kandidati'])} izvora")
    elif tip == "pretraga_pala":
        cmd.stdout.write(cmd.style.WARNING(f"    pretraga pala: {d['greska']}"))

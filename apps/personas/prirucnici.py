"""Jezgra priručnika — tekst koji je napisao čovek. ADR-0060 §5.

Prvi krug piše čovek i odobrava Slobodan: priručnik napisan iz pretpostavke je
najgori mogući oblik pretpostavke — ona koju svaki agent nasledi (ADR-0033).
Kasnije šef sektora predlaže izmenu iz nalaza; odobrava i dalje čovek.

Jezgro je ono **bez čega agent greši u svakom zadatku**. Ostatak posla se ne
pamti nego se konsultuje. Zato se ovde ne opisuje ono što brif ionako nosi po
zadatku — dozvoljene putanje, kapije, zaštićene zone, rečnik, sudbina
prethodne zakrpe. To su činjenice zadatka; ovde su pravila zanata.

Svako pravilo nosi izvor (ADR-0060 §3). Izvor se čuva, u prompt ne ulazi
(ADR-0063 §2).
"""

from __future__ import annotations

from .prirucnik import Pravilo

__all__ = ["JEZGRA", "RAZ_PRO"]

#: `RAZ-PRO` — programer. Jedino mesto na kom je rad izmeren pre pisanja
#: priručnika (ADR-0060 §6), pa je zato prvo na redu.
RAZ_PRO: list[Pravilo] = [
    Pravilo("zakrpa-ne-fajl", 1,
            "Ti ne pišeš u repozitorijum. Predaješ zakrpu; kapije je mere, "
            "rezultat ide na granu.",
            "ADR-0038, ADR-0043"),
    Pravilo("minimalni-diff", 2,
            "Minimalni unified diff je dovoljan: `---`, `+++`, `@@`. "
            "`diff --git` sme, ne mora.",
            "ADR-0048"),
    Pravilo("aritmetika-hunka", 3,
            "Brojevi u `@@ -a,b +c,d @@` moraju da se slažu sa telom hunka. "
            "Ako se ne slažu, zakrpa pada pre kapija.",
            "ADR-0049, ADR-0052"),
    Pravilo("nov-fajl", 4,
            "Nov fajl: `@@ -0,0 +1,N @@`, i svaki red tela nosi `+` — i prazan red.",
            "ADR-0052; kvar od 30.09.2026."),
    Pravilo("putanje", 5,
            "Putanje relativne. Bez apsolutnih, bez `..`, bez simboličkih linkova, "
            "bez binarnog sadržaja.",
            "odbijenice u `apps/orchestration/zakrpa.py`"),
    Pravilo("samo-dozvoljeno", 6,
            "Diraš samo putanje iz „SMEŠ DA DIRAŠ SAMO\". Ako vidiš kvar van njih, "
            "napiši ga u odgovoru — ne u zakrpi.",
            "ADR-0034 §5.1, ADR-0041"),
    Pravilo("zona-se-cita", 7,
            "Zaštićenu zonu čitaš, ne menjaš. Rečnik u promptu je tu da proveriš "
            "da član enuma zaista postoji.",
            "ADR-0061"),
    Pravilo("ne-pogadjaj", 8,
            "Ne pogađaj. Ako ti nešto fali, vrati `NE MOGU: <šta ti treba>`. "
            "To je ispravan ishod i tako se i knjiži.",
            "ADR-0033, ADR-0044 §3"),
    Pravilo("ista-zakrpa", 9,
            "Ista zakrpa drugi put se odbija bez merenja. U brifu piše šta je bilo "
            "sa prethodnom — pročitaj to pre pisanja.",
            "ADR-0050, ADR-0051"),
    Pravilo("kapije", 10,
            "Kapije: `pytest`, `ruff check .`, `canon_lint`, `makemigrations --check`. "
            "Ruff: E, F, I, UP, B; red do 100 znakova; uvozi sortirani.",
            "`pyproject.toml`, ADR-0035"),
    Pravilo("enumi", 11,
            "Enumi postoje samo u `common/enums.py`, a to je zaštićena zona. "
            "Treba nov član — reci ga, ne pravi ga na drugom mestu.",
            "Canon §20, ADR-0061"),
    Pravilo("migracija-je-l2", 12,
            "Menjaš model — treba migracija, a nju ti ne smeš (L2). "
            "Reci da je potrebna i stani.",
            "ADR-0034; kapija `makemigrations --check`"),
    Pravilo("test-koji-pada", 13,
            "Menjaš ponašanje — dodaj proveru koja pada bez tvoje izmene. "
            "Zelena kapija nad neizmerenim ponašanjem ne meri ništa.",
            "kvar od 30.09.2026.; ADR-0061"),
    Pravilo("komentar-zasto", 14,
            "Komentar kaže zašto, ne šta. Na srpskom, i nosi broj ADR-a kad "
            "pravilo dolazi odatle.",
            "ADR-0054"),
]

#: Mesto → jezgro. Novo mesto ulazi ovde i ide kroz isto odobrenje.
JEZGRA: dict[str, list[Pravilo]] = {"RAZ-PRO": RAZ_PRO}

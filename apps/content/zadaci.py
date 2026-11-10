"""Vrste radnih zadataka za persone (stavka 2 — bogatiji artefakti).

Do sada je persona pravila samo kratku objavu. Ovde su bogatije vrste:
  - CONTENT vrste (objava, dubinski-clanak, nit, newsletter, video-scenario) —
    javni sadržaj; poklapaju se sa `ContentFormat`, pa se prave i čuvaju kao
    `ContentItem` kroz postojeći `service.draft` (kapije, disclosure, pravopis);
  - INTERNI artefakti (battlecard, outreach, plan-naloga) — radni dokument koji
    se NE objavljuje na kanal; zasad showcase (`agent_zadatak` ih ispisuje), model
    `Artefakt` + pregled su sledeći sloj.

Svaka vrsta kaže:
  - `upit` — kojim upitom se sastavlja kontekst (ADR-0131 digne baš pravu veštinu
    u sloj „U celini (sa koracima)"); `{ulaz}` je konkretan unos ili tema;
  - `uputstvo` — šta model treba da napravi (`{ulaz}` = tema/konkurent/prospekt);
  - `format` — `ContentFormat` pod kojim se čuva (za content vrste);
  - `interni` — True za radni artefakt koji se ne objavljuje (showcase).

Artefakt nastaje kroz isti `context.build` + `gateway.generate` — nema novog motora.
"""

from __future__ import annotations

from dataclasses import dataclass

from common import enums as E


@dataclass(frozen=True)
class Zadatak:
    kljuc: str
    naziv: str
    upit: str
    uputstvo: str
    format: E.ContentFormat = E.ContentFormat.POST
    interni: bool = False


ZADACI: dict[str, Zadatak] = {
    # -------- CONTENT: javni sadržaj, čuva se kao ContentItem --------
    "objava": Zadatak(
        "objava", "Kratka objava",
        upit="{ulaz}",
        uputstvo=("Napiši kratku objavu na temu: {ulaz}. Jedan problem, jedan "
                  "broj sa izvorom, jedan zaključak. Bez uvoda i bez hashtag-ova."),
        format=E.ContentFormat.POST),
    "dubinski-clanak": Zadatak(
        "dubinski-clanak", "Dubinski članak",
        upit="{ulaz}",
        uputstvo=("Napiši dubinski članak o temi: {ulaz}. Jasna teza, 3–4 odeljka "
                  "sa podnaslovima, svaka ključna tvrdnja sa proverljivim izvorom; "
                  "zaključak sa jednim konkretnim savetom. Bez praznog hvalospeva."),
        format=E.ContentFormat.ARTICLE),
    "nit": Zadatak(
        "nit", "Nit / carousel",
        upit="{ulaz}",
        uputstvo=("Napravi nit (thread) o temi: {ulaz}. 5–7 delova; prvi je kuka, "
                  "svaki deo samostalan i kratak, poslednji poziv na razmišljanje. "
                  "Bez hashtag-ova."),
        format=E.ContentFormat.THREAD),
    "newsletter": Zadatak(
        "newsletter", "Newsletter izdanje",
        upit="{ulaz}",
        uputstvo=("Napravi newsletter izdanje na temu: {ulaz}. 3–4 kratke stavke, "
                  "svaka: šta se desilo + zašto je važno + izvor. Uvodna rečenica "
                  "i jedna misao za kraj."),
        format=E.ContentFormat.NEWSLETTER),
    "video-scenario": Zadatak(
        "video-scenario", "Video scenario",
        upit="{ulaz}",
        uputstvo=("Napiši scenario za kratak video o temi: {ulaz}. Kuka (prvih 5 "
                  "sekundi), 3 poente sa primerom, poziv na kraju. Označi [KADAR] "
                  "i [TEKST NA EKRANU]."),
        format=E.ContentFormat.VIDEO_SCRIPT),
    # -------- INTERNI: radni artefakt, ne objavljuje se (showcase) --------
    "battlecard": Zadatak(
        "battlecard", "Konkurentski battlecard",
        upit="izrada konkurentskog battlecard-a i pozicioniranje",
        uputstvo=("Napravi battlecard protiv konkurenta po koracima veštine. "
                  "Ulaz: {ulaz}. Daj jasne odeljke: snage i slabosti konkurenta "
                  "(svaka sa činjenicom, bez preterivanja), naše prednosti sa "
                  "dokazom, odgovore na 3 tipična prigovora, i pitanja za "
                  "discovery koja otkrivaju gde smo jači."),
        interni=True),
    "outreach": Zadatak(
        "outreach", "Outreach sekvenca",
        upit="višekanalna sekvenca prospektiranja i hladni mejl",
        uputstvo=("Napravi outreach sekvencu za: {ulaz}. 3–4 koraka; za svaki: "
                  "kanal, razmak u danima, cilj koraka i poruka u tonu persone. "
                  "Bez generičkih fraza; svaka poruka ima jasan razlog kontakta."),
        interni=True),
    "plan-naloga": Zadatak(
        "plan-naloga", "Plan razvoja naloga",
        upit="plan razvoja naloga i mapiranje zainteresovanih strana",
        uputstvo=("Napravi plan razvoja naloga za: {ulaz}. Daj: uklapanje u ICP "
                  "(sa kriterijumima), mapu odlučilaca i njihovih briga, hipotezu "
                  "vrednosti, rizike, i konkretne sledeće korake sa rokovima."),
        interni=True),
}


def nadji(kljuc: str) -> Zadatak:
    try:
        return ZADACI[kljuc]
    except KeyError as e:
        raise KeyError(
            f"Nepoznata vrsta zadatka: {kljuc!r}. Postoje: {', '.join(ZADACI)}."
        ) from e

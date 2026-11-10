"""Vrste radnih zadataka za persone (stavka 2 — bogatiji artefakti).

Do sada je persona pravila samo kratku objavu. Ovde su bogatiji radni artefakti
(battlecard, outreach sekvenca, plan naloga) koje agent već ima u veštinama.
Svaka vrsta kaže:
  - `upit` — kojim upitom se sastavlja kontekst, da ADR-0131 digne baš pravu
    veštinu u sloj „U celini (sa koracima)";
  - `uputstvo` — šta model treba da napravi; `{ulaz}` je konkretan unos
    (konkurent, prospekt, nalog, tema).

Artefakt nastaje kroz isti `context.build` + `gateway.generate` kao i objava —
nema novog motora. Showcase sloj (agent_zadatak) samo ispisuje; persistencija
(model Artefakt + pregled) je sledeći sloj.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Zadatak:
    kljuc: str
    naziv: str
    upit: str
    uputstvo: str


ZADACI: dict[str, Zadatak] = {
    "objava": Zadatak(
        "objava", "Kratka objava",
        upit="{ulaz}",
        uputstvo=("Napiši kratku objavu na temu: {ulaz}. Jedan problem, jedan "
                  "broj sa izvorom, jedan zaključak. Bez uvoda i bez hashtag-ova."),
    ),
    "battlecard": Zadatak(
        "battlecard", "Konkurentski battlecard",
        upit="izrada konkurentskog battlecard-a i pozicioniranje",
        uputstvo=("Napravi battlecard protiv konkurenta po koracima veštine. "
                  "Ulaz: {ulaz}. Daj jasne odeljke: snage i slabosti konkurenta "
                  "(svaka sa činjenicom, bez preterivanja), naše prednosti sa "
                  "dokazom, odgovore na 3 tipična prigovora, i pitanja za "
                  "discovery koja otkrivaju gde smo jači."),
    ),
    "outreach": Zadatak(
        "outreach", "Outreach sekvenca",
        upit="višekanalna sekvenca prospektiranja i hladni mejl",
        uputstvo=("Napravi outreach sekvencu za: {ulaz}. 3–4 koraka; za svaki: "
                  "kanal, razmak u danima, cilj koraka i poruka u tonu persone. "
                  "Bez generičkih fraza; svaka poruka ima jasan razlog kontakta."),
    ),
    "plan-naloga": Zadatak(
        "plan-naloga", "Plan razvoja naloga",
        upit="plan razvoja naloga i mapiranje zainteresovanih strana",
        uputstvo=("Napravi plan razvoja naloga za: {ulaz}. Daj: uklapanje u ICP "
                  "(sa kriterijumima), mapu odlučilaca i njihovih briga, hipotezu "
                  "vrednosti, rizike, i konkretne sledeće korake sa rokovima."),
    ),
}


def nadji(kljuc: str) -> Zadatak:
    try:
        return ZADACI[kljuc]
    except KeyError as e:
        raise KeyError(
            f"Nepoznata vrsta zadatka: {kljuc!r}. Postoje: {', '.join(ZADACI)}."
        ) from e

"""Kućni stil izveden iz Pravopisa srpskoga jezika. ADR-0054.

Svako pravilo ovde je **prepisano iz knjige**, a ne iz nečijeg sećanja, i nosi
broj tačke po kojoj se može proveriti. To nije kićenje: pravilo bez izvora je
tvrdnja koju niko ne može da potkrepi, a takvu ADR-0033 ne prima.

Zašto baš ova pravila: to su mesta na kojima model koji piše srpski greši
sistematski, a greška se vidi u svakom tekstu — futur po hrvatskom obrascu,
engleski navodnici, crta umesto crtice. Nisu odabrana po tome koliko su
zanimljiva, nego po tome koliko često izlaze na videlo.

Pismo: agenti pišu **latinicom sa dijakriticima**, pa su i primeri takvi.
Izvornik Pravopisa ostaje ćirilični — pravila o slovima (in-j naspram nj)
gube smisao preslovljena — ali sama pravila važe u oba pisma.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Srpski navodnici, imenovani da se u kodu ne mešaju sa pravim znakom "
DONJI, GORNJI = "\u201E", "\u201C"

#: Ko je upisao ova pravila. Stoji u `created_by` svake pouke.
IZVOR = "Pravopis srpskoga jezika (Matica srpska)"


@dataclass(frozen=True)
class Pravilo:
    """Jedno pravilo kućnog stila, sa mestom u knjizi."""

    kljuc: str          # stabilan identifikator; po njemu se pouka prepoznaje
    tekst: str          # ono što model čita u promptu
    pre: str = ""       # kako NE treba
    posle: str = ""     # kako treba
    tacka: str = ""     # broj tačke u Pravopisu

    @property
    def za_prompt(self) -> str:
        rep = f" (Pravopis, t. {self.tacka})" if self.tacka else ""
        return f"{self.tekst}{rep}"


PRAVILA: tuple[Pravilo, ...] = (
    Pravilo(
        kljuc="futur-sazeti",
        tekst=("Futur glagola na -ti piši sažeto, u jednoj reči: znaću, znaćeš, "
               f"znaće, znaćemo, znaćete; trešću, čućete. Oblik {DONJI}znat ću{GORNJI}, "
               f"{DONJI}trest ću{GORNJI} je hrvatska praksa i ne koristi se. Glagoli na -ći "
               "se NE sažimaju: doći ću, peći ćeš, reći ću."),
        pre="Znat ću sutra i javit ću ti.",
        posle="Znaću sutra i javiću ti.",
        tacka="63a",
    ),
    Pravilo(
        kljuc="enklitike-odvojeno",
        tekst="Enklitički oblici pomoćnih glagola pišu se odvojeno: on je znao, "
              "znao je, znao bi, on će doći. Jedini izuzetak je sažeti futur "
              "glagola na -ti (znaću).",
        pre="On bi došao ali nije stigao.",
        posle="On bi došao, ali nije stigao.",
        tacka="63a",
    ),
    Pravilo(
        kljuc="negacija-ne",
        tekst=(f"Rečcu {DONJI}ne{GORNJI} piši ODVOJENO uz glagol: ne spava, ne znam, "
               "ne odlažući. Spojeno se piše u tvorbi imenica, prideva i priloga: "
               "nespavanje, neodložno, nehotice. Srasla su samo: nisam-nisi, "
               "neću-nećeš-neće, nemoj, nemam-nemaš, nemati, nemajući. Trpni pridev "
               "ide spojeno: nepisan, nenapisan, nepostojeći, neodgovarajući."),
        pre="Nezna se ko je poslao i ne odgovarajući nacrt je prošao.",
        posle="Ne zna se ko je poslao, i neodgovarajući nacrt je prošao.",
        tacka="63b",
    ),
    Pravilo(
        kljuc="rečca-li",
        tekst=(f"Rečca {DONJI}li{GORNJI} uz glagol uvek je odvojena: znaš li, da li znaš, "
               "hoće li doći, je li znao, ne bi li došao."),
        pre="Dali znaš kada stiže?",
        posle="Da li znaš kada stiže?",
        tacka="63c",
    ),
    Pravilo(
        kljuc="navodnici",
        tekst=(f"Koristi srpske navodnike {DONJI}ovako{GORNJI} — donji dvojni zarez na "
               "početku, gornji na kraju — ili »ovako«. Prav znak navoda (\") i "
               "engleski par (\u201C\u201D) se ne koriste. Polunavodnici se pišu "
               "kao podignuti zarez: 'navodno'. U istom tekstu drži jedan oblik."),
        pre='Nazvali su ga "prvim izborom".',
        posle=f"Nazvali su ga {DONJI}prvim izborom{GORNJI}.",
        tacka="208",
    ),
    Pravilo(
        kljuc="crta-i-crtica",
        tekst="Crtica (-) spaja delove reči i UVEK je primaknuta, bez razmaka: "
              "grčko-turski, crno-beli, rekla-kazala. Crta (—) organizuje rečenicu "
              "i piše se sa razmakom sa obe strane. Crtica nije crta i ne menjaju se.",
        pre="Odnos je bio grčko - turski, a rezultat - nikakav.",
        posle="Odnos je bio grčko-turski, a rezultat — nikakav.",
        tacka="217",
    ),
)

#: Ključevi svih pravila — za proveru da se nijedno ne izgubi tiho.
KLJUCEVI: frozenset[str] = frozenset(p.kljuc for p in PRAVILA)

"""Zlatni skup za merenje semantičke pretrage Libri blokova (ADR-0031 sloj 3).

Canon §21: isti duh kao `apps/memory/golden.py` i zlatni skup veština — mali
korpus na srpskom (stolarsko znanje, jer tu već imamo stvarni dokument na produ)
i pitanja namerno u drugim rečima / padežima, da se meri SEMANTIKA, ne leksičko
preklapanje. Svaki blok je o zasebnoj temi, pa svako pitanje ima jedan tačan
blok. `libri_eval` od ovoga pravi privremeni dokument, embeduje ga, postavlja
pitanja i meri hit@k / MRR / p95 — pa sve poništi.
"""

from __future__ import annotations

#: (block_id, tekst) — korpus. Teme su razdvojene da bi tačan odgovor bio jednoznačan.
BLOKOVI: list[tuple[str, str]] = [
    ("blk_000001",
     "Prirodno sušenje drveta odvija se na otvorenom, pod nadstrešnicom, gde "
     "vazduh slobodno struji oko naslaganih dasaka i polako odnosi vlagu."),
    ("blk_000002",
     "Konvektivno sušenje koristi zagrejani vazduh koji kroz komoru prolazi "
     "preko građe i tako ubrzano odnosi vlagu iz drveta."),
    ("blk_000003",
     "Spajanje dasaka tiplovima daje čvrst i skriven spoj bez ijednog metalnog "
     "veznika, pa se lice komada ne vidi."),
    ("blk_000004",
     "PVA lepkovi namenjeni su unutrašnjim spojevima jer njihov sloj ne "
     "podnosi vlagu i na kiši popušta."),
    ("blk_000005",
     "Brušenje se radi u nekoliko prolaza, od krupnije ka sitnijoj granulaciji, "
     "sve dok površina ne postane potpuno glatka na dodir."),
    ("blk_000006",
     "Previsoka vlaga drveta pri ugradnji kasnije dovodi do pucanja, "
     "vitoperenja i razdvajanja spojeva kada komad počne da se suši."),
    ("blk_000007",
     "Lakiranje štiti površinu od vode i habanja, a nanosi se u tankim "
     "slojevima sa laganim brušenjem između nanosa."),
    ("blk_000008",
     "Tvrdo drvo poput hrasta i bukve teže se obrađuje ručnim alatom, ali daje "
     "trajnije i otpornije komade od mekog drveta."),
    ("blk_000009",
     "Pre rezanja daska se obavezno meri dvaput, jer pogrešan rez skraćuje "
     "komad i gubi se materijal koji se ne može vratiti."),
    ("blk_000010",
     "Rende skida tanak sloj drveta i izravnava površinu; dubina reza podešava "
     "se zavrtnjem na telu alata."),
    ("blk_000011",
     "Zaštita za oči i disajne puteve obavezna je pri brušenju, jer sitna "
     "prašina drveta nadražuje pluća i oči."),
    ("blk_000012",
     "Furnir je vrlo tanak list drveta koji se lepi preko jeftinije osnove da "
     "bi komad spolja izgledao kao da je od skupog, plemenitog drveta."),
]

#: (pitanje, očekivani block_id) — druge reči/padeži nego u bloku (meri semantiku).
PITANJA: list[tuple[str, str]] = [
    ("kako se drvo osuši na vazduhu bez komore?", "blk_000001"),
    ("čime se ubrzava uklanjanje vlage toplim vazduhom?", "blk_000002"),
    ("kako spojiti dve daske a da se ne vide ekseri?", "blk_000003"),
    ("koje lepilo popušta na vlazi?", "blk_000004"),
    ("kako se dobija glatka površina pre farbanja?", "blk_000005"),
    ("šta se dešava ako ugradim nedovoljno suvo drvo?", "blk_000006"),
    ("čime se površina zaštiti od vode i trošenja?", "blk_000007"),
    ("koje drvo je izdržljivije ali teže za obradu?", "blk_000008"),
    ("zašto se meri dva puta pre sečenja?", "blk_000009"),
    ("čemu služi zaštita za oči i masku u radionici?", "blk_000011"),
    ("šta je tanki list drveta zalepljen preko jeftinije podloge?", "blk_000012"),
]


#: Zlatni skup za merenje izvlačenja tvrdnji (ADR-0031 sloj 4a).
#: (tekst bloka, očekivani subjekat tvrdnje ili None ako rečenica NIJE definiciona).
#: Meri preciznost (koliko izvučenih je tačno) i odziv (koliko očekivanih je uhvaćeno)
#: determinističke osnove — pre nego što LLM uđe kao zamenljiv sloj.
TVRDNJE_ZLATNE: list[tuple[str, str | None]] = [
    ("Furnir je vrlo tanak list drveta koji se lepi preko jeftinije osnove.", "Furnir"),
    ("Rende je ručni alat koji skida tanak sloj drveta.", "Rende"),
    ("Tipl je drveni čep koji spaja dve daske bez eksera.", "Tipl"),
    ("Lak je zaštitni premaz za drvene površine.", "Lak"),
    ("Tvrdo drvo predstavlja trajniji materijal od mekog drveta.", "Tvrdo drvo"),
    ("Brušenje se radi u nekoliko prolaza do glatke površine.", None),
    ("Majstor bira drvo prema nameni komada.", None),
    ("Pre rezanja daska se meri dvaput.", None),
]


#: Zlatni skup za merenje izvlačenja entiteta i odnosa (ADR-0031 sloj 4b).
#: (tekst bloka, očekivani entiteti [(name, kind)], očekivani odnosi [(subj, rel, obj)]).
#: Meri preciznost/odziv determinističke osnove — pre nego što LLM uđe kao
#: zamenljiv sloj kroz isti `entiteti.izvuci_*`. Negativne rečenice (bez pokazne
#: reči / bez dva entiteta) čuvaju preciznost: ne smeju da proizvedu ništa.
GRAF_ZLATNI: list[tuple[str, list[tuple[str, str]], list[tuple[str, str, str]]]] = [
    ("Milan Jovanović radi u kompaniji Vinogradi.",
     [("Milan Jovanović", "osoba"), ("Vinogradi", "organizacija")],
     [("Milan Jovanović", "radi_u", "Vinogradi")]),
    ("Ana Petrović je direktorka preduzeća Drvo Promet.",
     [("Ana Petrović", "osoba"), ("Drvo Promet", "organizacija")],
     [("Ana Petrović", "vodi", "Drvo Promet")]),
    ("Sajam Drvo održan je 12.03.2026.",
     [("Sajam Drvo", "dogadjaj")],
     []),
    ("Marko Ilić je osnovao kompaniju Tipl Sistem.",
     [("Marko Ilić", "osoba"), ("Tipl Sistem", "organizacija")],
     [("Marko Ilić", "osnovao", "Tipl Sistem")]),
    ("Preduzeće Tipl deo je udruženja Majstori Srbije.",
     [("Preduzeće Tipl", "organizacija"), ("Majstori Srbije", "organizacija")],
     [("Preduzeće Tipl", "deo_od", "Majstori Srbije")]),
    ("Brušenje se radi u nekoliko prolaza do glatke površine.", [], []),
    ("Furnir je vrlo tanak list drveta koji se lepi preko osnove.", [], []),
    ("Literatura Hidrotermička obrada drveta, Kolin Beograd, 1998.", [], []),
    ("U popisu stoje Sušenje Drveta i Tehnologija Rezanja.", [], []),
]

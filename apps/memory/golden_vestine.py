"""Zlatni skup za merenje rangiranja veština. ADR-0120; Canon §21.

Isti princip kao `golden.py` za memoriju, ali za veštine (`KnowledgeFact`,
predikat `vestina.postupak`): srpski upit koji bi agent stvarno postavio →
JEDNA veština koja je tačan odgovor. Veštine u korpusu nose engleske nazive
(slug), a srpski opis u `napomene`/`koraci` — zato leksičko poklapanje pada
preko jezika (izmereno: MRR 0.269, tačna veština tek na 121/177/308/444
mestu), a višejezični semantički model (ADR-0120) treba da je digne u vrh.

Parovi biraju jasno razdvojene domene (berza, tržište, GDPR, SOC 2, ASO,
cene, LinkedIn, patenti…) da merenje meri jezički most, ne da kažnjava model
što ne razlikuje dve skoro iste veštine. Nazivi veština MORAJU postojati u
korpusu — `vestina_eval` meri nad onim što je stvarno uvezeno, pa par na
nepostojeću veštinu znači promašaj, ne grešku skupa.

`manage.py vestina_eval` pušta skup kroz pravo rangiranje iz paketa
(`context._rangiraj_vestine`) i daje puni@4 (koliko tačnih uđe U CELINI,
ADR-0112), top@10 i MRR. Isti broj za svaki kandidat-model je osnova odluke.
"""

from __future__ import annotations

#: (srpski upit, tačan naziv veštine — `subject` u korpusu)
PAROVI: tuple[tuple[str, str], ...] = (
    ("detaljna fundamentalna analiza akcije kompanije koja je izašla na berzu",
     "stock-analysis"),
    ("kako da procenim veličinu tržišta kao TAM SAM SOM, i odozgo i odozdo",
     "market-research"),
    ("da li je naš SaaS posao zdrav po MRR-u, odlivu kupaca, LTV i CAC",
     "saas-metrics-coach"),
    ("dizajn prospektivne kliničke studije i izbor primarnog ishoda",
     "clinical-research"),
    ("pregled naučne literature i pretraga radova u PubMed bazi",
     "litreview"),
    ("napiši hladan mejl za prvi B2B kontakt koji dobija odgovor",
     "cold-email"),
    ("usklađivanje obrade ličnih podataka sa GDPR propisom",
     "gdpr-dsgvo-expert"),
    ("priprema za SOC 2 reviziju i matrica kontrola",
     "soc2-compliance"),
    ("optimizacija aplikacije u prodavnici aplikacija, istraživanje ključnih reči",
     "app-store-optimization"),
    ("izbor modela i strategije cena za naš proizvod",
     "pricing-strategist"),
    ("napiši objavu za LinkedIn",
     "linkedin-content"),
    ("pretraga patenata i analiza postojećeg stanja tehnike",
     "patent"),
)

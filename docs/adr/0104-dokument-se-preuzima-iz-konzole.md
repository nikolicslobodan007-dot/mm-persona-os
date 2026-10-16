# ADR-0104 — Dokument se preuzima iz konzole

- **Status:** prihvaćen (16.10.2026.)
- **Povod:** Posle ADR-0103 agent pravi fajl, ali se do njega dolazi samo kroz
  `manage.py shell`. To nije isporuka nego demonstracija.
- **Prethodi:** ADR-0010 (konzola), ADR-0018 (skladište), ADR-0103
- **Menja:** `console/views.py`, `console/urls.py`,
  `console/templates/console/content.html`, `apps/content/dokument.py`
- **Canon:** §15 (konzola je mesto gde čovek odlučuje i preuzima)

## Izmereno pre odluke

Ruta `/console/assets/<public_id>` **već postoji** (ADR-0018) i služi bajtove
svakom prijavljenom operateru. Dokument je time već bio dohvatljiv — ali:

| Šta je falilo | Posledica |
|---|---|
| nema `Content-Disposition` | `.odt` stiže kao bezimeni fajl, pregledač pokušava da ga prikaže |
| nema linka na stranici Sadržaj | niko ne zna da fajl postoji |
| nema dugmeta da se napravi | pravljenje je moglo samo iz ljuske |

Manje posla nego što je izgledalo: nova je jedna ruta i jedan red u šablonu,
ne nov podsistem.

## Odluka

**1. Slika se prikazuje, dokument se preuzima.** `asset` dodaje
`Content-Disposition: attachment` sa imenom `<public_id><nastavak>` **samo**
za `AssetKind.DOCUMENT`. Ponašanje slika se ne menja, i za to postoji test.

**2. Veza nacrt → dokument ide preko ključa u skladištu, ne preko modela.**
Ključ se računa iz posla (ADR-0103 tačka 6), pa je isti pre i posle pravljenja
fajla. `dokument.kljuc_za`, `postojeci` i `postojeci_za` su javni za tu svrhu.
Spisak sadržaja traži sve dokumente **jednim upitom**, ne jednim po stavci.

Ovo i dalje nije prava veza u modelu — `AssetRole` nema vrednost za dokument,
a to je zaštićeni `common/enums.py` i zaslužuje svoju odluku (dug iz ADR-0103
ostaje otvoren). Ali ključ je deterministički i dovoljan da konzola radi.

**3. Pravljenje dokumenta iz konzole ide POST-om i traži ulogu.** Nema
spoljašnjeg efekta, ali jeste radnja koju neko pokreće; ista uloga kao za
ostale radnje nad sadržajem (`_DRAFTERS`). Uloga koja ne sme dobija poruku i
ništa se ne upisuje.

**4. Format je zasad samo `odt`**, jer je jedini koji radi bez LibreOffice-a u
slici (ADR-0103). Dugme šalje `oblik`, pa kad LibreOffice uđe, `.docx` i
`.pdf` su jedna opcija u obrascu, ne nov kod.

## Šta ovo NE radi

Konzolu i dalje otvara čovek. Ovo nije „prozor za razgovor sa Ivanom" — to je
poseban posao i stoji u redu čekanja. Ovde je zatvorena samo poslednja rupa u
lancu **nacrt → fajl → čovekov disk**.

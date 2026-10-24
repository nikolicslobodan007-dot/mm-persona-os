# Web Korporacija · PR-B5 — Executive Office Premium Pilot

**Status:** izolovani kod i asseti pripremljeni za Claudeov PR pregled; nije spojeno ni deployovano.

## Tačna osnova

- Repozitorijum: `nikolicslobodan007-dot/mm-persona-os`
- Bazni `origin/main`: **`a52ed5cecbaabf21b7ee6320d09217fae661f264`** (PR-B4, 23.10.2026)
- Provereni Git blobovi:
  - `tools/office_v14b/src/campus.mjs` — `d7cfaef96f27b5290383a3d37dffdef1aeef5548`
  - `console/templates/console/office.html` — `109926ef48f7ba7cffe32bb2841b6609bf555e28`
- B5 **ne menja** Django modele, migracije, V1.2 Office API, permission/TOTP, runtime, orkestraciju, glavnu navigaciju ili logo.

## Sadržaj paketa

`PR_B5_Executive_Pilot.patch` je standardna Git binary zakrpa, spremna za primenu na zasebnoj grani. ZIP dodatno sadrži izmenjeni izvorni kod, nove testove i sedam PNG resursa. `generate_b5_assets.py` omogućava reprodukovanje resursa lokalno korišćenjem `cairosvg` i `Pillow`; nije produkciona zavisnost.

Novi fajlovi:
- `tools/office_v14b/src/executive-pilot.mjs` — strogi allowlist lokalnih URL-ova i dozvoljeni izbor Uprave i dva agenta
- `tools/office_v14b/tests/executive-pilot.test.mjs` — 10 nezavisnih Node testova
- `tools/office_v14b/generate_b5_assets.py` — reproduktivan generator slojeva
- `console/static/console/office-premium-b5/*.png` — 7 grafičkih resursa

Promene u postojećim fajlovima: **samo** `tools/office_v14b/src/campus.mjs` i `console/templates/console/office.html`.

## Primena

```bash
# Na PC-u, iz poslednjeg origin/main, u ČISTOJ zasebnoj grani:
git fetch origin
git switch -c feature/virtual-office-v14b5-executive origin/main
# Ako je main napredovao, pregledati diff i uskladiti pre primene.
git apply --check PR_B5_Executive_Pilot.patch
git apply PR_B5_Executive_Pilot.patch

cd tools/office_v14b
npm ci
npm run check
npm run build
cd ../..

python tools/canon_lint.py
ruff check .
python manage.py makemigrations --check --dry-run
python -m pytest
python manage.py collectstatic --noinput
```

B5 ostavlja postojeći `pixi.js/unsafe-eval` bez promene. JS/PNG fajlovi učitavaju se samo sa istog Django origin-a, bez CDN-ova, bez inline JavaScript-a i bez izlaganja identifikatora `IMG-*`.

**Četiri kapije** (Canon lint, Ruff, check migracija, pytest) moraju biti zelene nad finalnim kandidatom pre tvog odobrenja merge-a. Produkcioni browser/WebGL i stvarni CSP potrebno je proveriti uz realnu korisničku sesiju.

## Kako B5 radi

1. Django kroz `{% static %}` generiše lokalne URL-ove 7 B5 resursa (uključujući hashovane putanje iz `ManifestStaticFilesStorage`).
2. `executive-pilot.mjs` proverava URL bez remote hostova, query/hash, alternativnih ekstenzija ili javnih portreta.
3. PixiJS u postojećoj sceni bira B5 slojeve **samo** za stvarnu prostoriju `Uprava` (`Department.code` ili ime) sa postojećim `room.theme === 'executive'`.
4. Za ostala odeljenja ostaju B4 teksture/proceduralni prikaz.
5. Stilizovani B5 avatari koriste se samo za **Ivanu Đurić i Tamása Kovácsa kada ih stvarni registracioni API rasporedi u Upravu**. ID-jevi se ne izmišljaju niti hardkoduju; upoređuje se `public_id` sa prisutnim `room.people`.
6. U whole-building prikazu koristi se `executive-room-overview`, a u fokusu Uprave `executive-room-detail`.
7. Čuva se stari transparentni PixiJS hit target; klik na figuricu i dalje prolazi kroz `wk:scene-agent-select`, a na naziv sobe kroz `wk:scene-department-focus`.
8. Ako osnovna B5 slika nedostaje, automatski se koristi PR-B4. Ako avatar nedostaje, automatski se koristi postojeća proceduralna figurica. Nema blokiranja API-ja ili zastoja pri preuzimanju resursa.

### Bezbednosna ograničenja

- Sintetičke fotografije iz zaštićenog `office/portraits/` **nisu korišćene, kopirane niti uključene u statičke PNG fajlove**.
- Figurice su **ilustrativne predstave**, nisu portretno verne. Za tačno vizuelno poklapanje potrebna je posebna, odobrena procedura i procena prava pristupa.
- PR-B5 **ne proizvodi nikakve radne animacije** i ne interpretira READY/ACTIVE/SIMULATION/LIVE kao potvrđeni posao; eventualna oznaka RUNNING ostaje vezana za postojeći `confirmedRunning` tok.
- Nije menjana niti dopunjavana lista podataka koju Office API vraća. Nema novih backend endpointa.

## QA u browseru (obavezno pre merge-a)

1. Otvoriti `/console/office`; 33 agenta učitavaju se iz postojećeg Django registra (stvarna cifra iz API-ja, ne hardkodirati je).
2. Cele zgrade: sve osim Uprave izgledaju identično PR-B4 verziji; Uprava ima B5 pozadinu i nameštaj.
3. Ući u Upravu: prikaz se fokusira; `executive-room-detail` i funkcionalna selekcija.
4. Klik na Ivanu i Tamása pojedinačno: odgovarajući stvarni profil je u desnom inspektoru.
5. Izabrati agenta iz druge prostorije: inspektor se usklađuje sa odeljenjem; nema fiktivnih statusa.
6. U DevTools blokirati jednu B5 pozadinu/figuricu: fallback; nema JS crash-a.
7. CSP console bez grešaka, samo same-origin zahtevi; collectstatic uspešno razrešava hashove.
8. Testirati mobilni ekran i DOM režim `Lista prostorija`.
9. Pregledati performanse i memoriju posle 20 smena Office ⇄ department focus, uz `ResizeObserver`.
10. Pripremiti screenshot **realne** cele zgrade i fokusirane Uprave; lokalni `docs/` JPG u paketu je **samo offline kompozicija grafičkih slojeva**, ne dokaz WebGL integracije.

## Ograničenja i naredni koraci

- Ovo je **prvi realni layered 2.5D tehnički pilot**, ne finalni Pixar/Blender nivo.
- Za standard pune arhitektonske izometrije, karakterne rigove i višestruko osvetljenje potrebni su naknadno odobreni 3D/2D umetnički resursi.
- PixiJS bundle **nije izgrađen u ChatGPT okruženju** (nema lokalne pixi.js npm instalacije); Claude mora da izvrši `npm ci && npm run build`.
- Nisu izvršene četiri Django kapije u ovom okruženju; Claude ih izvršava na svom checkout-u uz PostgreSQL/pgvector servis.
- PR-B5 je namenjen **samo Claudeovom pregledu i tvojој odluci**. Ne spajati automatski.

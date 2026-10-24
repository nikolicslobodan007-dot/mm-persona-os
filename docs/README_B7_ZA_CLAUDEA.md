# Web Korporacija — PR-B7 / Campus Focus & Legibility + Executive Art

**Polazni `main`:** `c4251b29298576d93dd40719c43ef7e66b16cec2` (PR-B5).
**Odnos prema B6:** B6 **nije bio spojen** u `main` kada je B7 pripremljen. **B7 je kumulativan**: sadrži B6 grafiku/integraciju PLUS B7 poboljšanja kamere, prostora i upotrebljivosti. Ne primenjivati zasebno i B6 i B7.

## Šta sadrži B7

- Pet originalnih, lokalnih, višerezolucionih B6 grafičkih resursa za **Upravu**: overview, detail, foreground, Ivana, Tamás.
- Izolovanu PixiJS integraciju sa prioritetom `B6 art → B5 art → B4/procedural`, bez korišćenja privatnih portreta u javnom folderu.
- Kompaktniju geometriju kampusa: 10 odeljenja se u testnom prikazu 1050 × 530 uklapa u **4 kolone, 3 reda**, sa ~993 × 506 iskorišćenih px.
- Fokus kamere na **svako** odeljenje, ne samo Upravu, sa kontrolisanim marginama i bez gubitka `showAll` ponašanja.
- Čitljivije nazive odeljenja u udaljenoj mapi (cilj ~13 px), dok širina ostaje ograničena da ne prekrije broj agenata.
- Klik na **praznu površinu sobe** da otvori odeljenje; klik na figuricu i dalje bira agenta, bez duple selekcije. Diskretan hover outline samo kod korisničke interakcije.
- Ažuriran UI broj verzije u zaglavlju na PR-B7.

## Primena (bez spajanja u `main` bez odobrenja)

1. Proveri da je repo na `main` sa commitom navedenim iznad. Ako je `main` odmakao, proveri konflikte pre primene.
2. Otvori novu granu, npr. `feature/virtual-office-v14b7`.
3. Kopiraj `PR_B7_Cumulative_From_B5.patch` iz ZIP-a u koren repo-a.
4. Pokreni:

```bash
git apply --check PR_B7_Cumulative_From_B5.patch
git apply --binary PR_B7_Cumulative_From_B5.patch
cd tools/office_v14b
npm ci
npm run check
npm run build
```

5. Pokreni četiri projektne kapije iz korena repo-a uz odgovarajuće Django/PostgreSQL okruženje:

```bash
python tools/canon_lint.py
ruff check .
python manage.py makemigrations --check --dry-run
python -m pytest
```

6. U browser-u proveri: celu zgradu na 1920×1080, 1366×768, 1024px i mobilnom; zoom točkićem; izbor agenta preko Pixi figure i levo; izbor odeljenja klikom na naslov i **prazan pod**; povratak dugmetom **Cela zgrada**; uvećanu Upravu i druga odeljenja; DOM fallback; učitavanje i namerno blokiranje / 404 B6 slika; CSP bez `unsafe-eval`; static hash nazive kroz `collectstatic`.
7. Dostavi stvarni browser screenshot **cele zgrade** i **fokusirane Uprave**, plus rezultate testova. Bez automatskog merge-a u `main`.

## Granice bezbednosti

Nema promena Django modela, migracija, agent runtime-a, approval toka, sesija, 2FA, niti zaključanog V1.2 API ugovora. Nema novih network zahteva ka drugim domenima. Grafika ne prikazuje simulirani rad: READY / ACTIVE i dalje **nisu** dokaz RUNNING. Premium ilustracije agente vezuju isključivo preko stvarnog allowlisted registra i pripadnosti Upravi, ne preko pretpostavljenih ID-jeva.

## Evidencija provera pre slanja

- Lokalni **Node subset**: 27/27 testa (kamera, B6 resursi i identitet, B5 pravila i B7 geometrija).
- Statika PNG: proveriti u izveštaju `QA_B7.md`.
- Proverena čista primena zakrpe na lokalnoj kopiji baseline-a.
- **Nije** izvršen npm PixiJS build, browser WebGL test ni Django CI. Ovi koraci ostaju odgovornost integracione faze.

## Vizuelna istina

B6 grafikoni jesu glatki 2.5D renderi, ali **nisu 3D fotorealistički renderi**. B7 primarno rešava preglednost i interakciju; ne obećava Pixar završni nivo. Pre masovnog redizajna 10 ostalih odeljenja potreban je zaseban izbor odgovarajuće 3D produkcije i zajedničkog asset standarda.

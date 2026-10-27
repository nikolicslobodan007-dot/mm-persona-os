# WK 3D Virtual Office — Implementacioni plan V1.0
**Datum:** 26.10.2026.
**Projekat:** Web Korporacija / Persona OS / mm-persona-os
**Status:** F1/F2 inicijalni read-only pilot pripremljen; integracioni i CI testovi na serveru čekaju izvršenje
**Izvor istine:** Canon v1.1 i postojeći Office API V1.2 (LOCKED).

## 1. Rezime odluke

Novi interaktivni 3D prikaz poslovne zgrade uvodi se **pored**, a ne **umesto** postojećeg 2D/2.5D Mission Control UI-ja. Novi prikaz čita zaključani Office API; ne upisuje u bazu, ne upravlja agentima, ne menja šeme, enum katalog, katalog događaja ili dozvole.

**Prvi kod koji se isporučuje:** statički WebGL prikaz kancelarije, pet proceduralno nacrtanih radnih mesta, kamera koja se okreće i zumira, izbor odeljenja i radnog mesta, panel detalja i postojeći portreti iz zaštićenog proxy-ja. Podaci su stvarni (učitani iz zaključanog API-ja), dok su geometrija i pozicije u sceni demonstracioni.

**Druga tehnološka odluka:** 3DCodeVerse nije deo HTTP request-response puta. Radi isključivo *offline/asynchronous* u posebnom sandbox worker-u, a odobreni GLB/glTF modeli izlagali bi se korisnicima kao **pasivni podaci**, nikada kao proizvoljan JavaScript ili Python kod. Njegova integracija sledi nakon usvajanja prvog 3D pilot prikaza.

## 2. Identiteti, prava i podaci

Iz postojećih podataka čitamo `public_id`, `display_name`, `department`, `position`, `status`, `runtime_environment`, `trust_level`, `portrait_url`, `active_plan`, `active_step`. Nema privatnog dosijea, ličnih detalja, promptova, sadržaja planova, DB ID-ja ili direktnih MinIO putanja. Profil i portret uvek se dobijaju kroz postojeći `/console/office/api/v1/agents/{public_id}` i `/console/office/portraits/{public_id}`.

- `status` i `runtime_environment` su različita polja; vizuelni signal boje ne znači da agent trenutno izvršava zadatak.
- Autentifikacija: postojeći Django operator + TOTP sesija (isti `console_view` dekorator).
- Korisnički unos i API stringovi: DOM `textContent`, nikada `innerHTML`.
- Nema API POST/PUT/PATCH/DELETE poziva sa novog ekrana.
- Pristup: `Cache-Control: no-store`, odgovarajući CSP, dozvoljeni sadržaj samo sa istog origin-a.
- Bez novog Django app-a; `canon_lint` ostaje nepromenjen.

## 3. Arhitektura

```text
+---------------------------------------------+
| Browser: /console/office/3d                 |
| WebGL geometrija + HTML accessible controls |
+----------------------+----------------------+
                       | HTTPS GET, session + TOTP
+----------------------v----------------------+
| Django console.office_bridge.py (V1.2)      |
| /summary, /agents, /agents/{id}, /events     |
| /portraits/{id}                             |
+----------------------+----------------------+
                       | ORM samo kroz postojeći bridge
+----------------------v----------------------+
| Persona OS (postojeća baza i orkestrator)    |
+---------------------------------------------+

   [3DCodeVerse worker] ----> [quarantine/QA]
                                | GLB, hash, validation
                                v
                        [odobreni asset storage]
                                |
                            [3D klijent]
```

## 4. Faze i obim

### F0 — Audit i tehnički izbor (urađeno)
- Identifikovan odgovarajući GitHub projekat i aktivna Office V1.2 implementacija.
- Uočen postojeći V1.4B front-end (zadržati kao rollback).
- Potvrđen Canon lint: trinaest domen app-ova; ne dodavati novi app.
- Proverena razlika licence 3DCodeVerse izvornog koda (Apache-2.0) i skupa podataka (CC-BY-NC-SA).

### F1 — Sigurna 3D scena (početni PR)
- Ruta `/console/office/3d`, samo GET, operator + TOTP.
- Browser-native WebGL bez eksternih CDN-a, mrežnih zavisnosti ili novih Python paketa.
- Kamera: rotiranje prevlačenjem i kontrolama, zumiranje, reset.
- Proceduralno generisana kancelarija sa najviše pet vidljivih radnih mesta.
- HTML overlay imena i spisak dostupni i sa tastature.
- Nema izvršavanja modelskog/LLM koda u pregledaču.
- Podržan rezervni prikaz liste kada WebGL nije dostupan.

### F2 — Povezivanje sa Persona OS (početni PR)
- Čita postojeći `summary` i prvu stranicu (`limit=100`) agenta.
- Izbor odeljenja i pregled radnih mesta u koracima od 5.
- Klik na agenta čita postojeći detaljni endpoint.
- Portret se prikazuje samo kroz zaštićeni proxy.
- Jasno upozorenje da su podaci read-only, a geometrija simulacija.
- Granica F1/F2: prvih 100 agenata; skaliranje server-side filtera u F6.

### F3 — Prostorna organizacija (plan)
- Stabilan room_id nezavisan od Django modela, npr. `wk:hq:floor01:sales`.
- Odeljenja i radna mesta povezana isključivo sa postojećim `public_id` identitetima.
- Učitaj izabrani sprat/sobu, ne ceo svet; LOD i instancing.
- Konfiguracija rasporeda u odvojenom manifestu kao podaci, ne kao generator poslovnih događaja.
- Role-aware kontrolni panel i fallback u 2D.

### F4 — Aktivnosti i integritet (plan)
- Read-only označavanje potvrđenih statusa i dozvoljenog event feed-a.
- Vizuelni sloj nikada ne prevodi `READY` u `currently working` niti `SIMULATION` u `LIVE`.
- Svaka naredba, delegiranje ili odobravanje nastavlja isključivo postojeći servisni tok sa RBAC/approval/audit, a ne klik direktno na 3D objekat.
- Kasnije moguće povezivanje Mission Control kontrola kao otvaranje postojećih zaštićenih ekranâ.

### F5 — 3DCodeVerse Asset Studio (plan, nije implementirano)
- Izdvojeni worker (Linux x86-64; Python 3.13; Node 20.6+, Blender opciono u odgovarajućim tokovima).
- Konkretni track-ovi za pilot: `static_object` (`blender` / `cadquery`) i `scene` (`scene_threejs`).
- Primarne narudžbine modela: stolica, radni sto, ekran, stolna lampa, zid, konferencijska sala.
- Puni 3DCodeVerse harness izvodi se u izolovanom okruženju: bez mreže posle preuzimanja zavisnosti, bez korisničkih tajni i pristupa produkcionoj bazi, ograničen CPU/RAM/GPU, disk, vreme i broj pokušaja.
- Verifikacija: izlazni format GLB, glTF validator, hash/checksum, veličina datoteke, broj poligona, teksture, položaj, orijentacija, metarska skala, nema spoljašnjih URI-ja, nema skripti, humano odobrenje.
- Čuvanje: `draft` -> `validated` -> `approved` -> `published` -> `retired` kao statusi zasebnog asset registra (ne novi Canon enum; dizajn i ADR pre uvođenja u postojeći backend).
- Rezultat se isporučuje kroz kontrolisani storage i predvidive URL-ove.
- Izbegavati upotrebu objavljenog 3DCodeVerse-2M nekomercijalnog dataseta u našem komercijalnom proizvodnom toku bez izričite licence.

### F6 — 10.000 agenata (plan)
- Početna scena: zgrada + odeljenja, nikada 10.000 avatara istovremeno.
- Paginacija/kursor, filtriranje po odeljenju i server-side pretraga.
- LOD/instancing i viewport-culling, samo aktivna soba.
- Inkrementalni statusi preko dozvoljenih događaja ili umerenog polling-a; stroga deduplikacija eventa.
- Poseban mobilni degradacioni režim i 2D alternativa.

## 5. Funkcionalni zahtevi

| Oznaka | Zahtev | U prvom PR? |
|---|---|---|
| WK3D-001 | 3D kancelarija u pregledaču bez CDN-a | DA |
| WK3D-002 | Kontrole kamere (touch/miš/tastatura preko dugmadi) | DA |
| WK3D-003 | Živi identiteti i statusi iz V1.2 API-ja | DA |
| WK3D-004 | Klik radnog mesta otvara inspektor agenta | DA |
| WK3D-005 | V1.2 i Canon nepromenjeni | DA |
| WK3D-006 | TOTP/RBAC zaštita i CSP | DA |
| WK3D-007 | Dinamički raspored odeljenja i spratova | NE, F3 |
| WK3D-008 | 3DCodeVerse generisanje pasivnih 3D asseta | NE, F5 |
| WK3D-009 | Vizuelno označavanje odobrenja i događaja | NE, F4 |
| WK3D-010 | 10.000 agenata uz LOD i page-based fetch | NE, F6 |

## 6. Kriterijumi prihvatanja prve verzije

1. Prijava i TOTP su obavezni, bez njih pregled `/console/office/3d` ne radi.
2. Ekran prikazuje agente samo nakon uspešnog odgovora postojećeg API-ja; nema izmišljenih poslovnih podataka.
3. Nema HTTP upisa niti migracija, novih Canon enum-a ili event tipova.
4. Na stranici se vide status i runtime kao odvojeni podaci.
5. Kamera se kreće, radna mesta se biraju mišem i tastaturom, panel se otvara.
6. Ako WebGL nije podržan, spisak agenata ostaje upotrebljiv.
7. `pytest`, `ruff`, `canon_lint`, `makemigrations --check --dry-run` prolaze na CI.
8. V1.4B ostaje funkcionalan; vraćanje na staro je jednostavno uklanjanje nove rute.
9. U browseru se proveravaju mobilna rezolucija, TOTP sesija i profil sa/bez portreta.

## 7. Sigurnost i rizici

| Rizik | Nivo | Kontrola |
|---|---|---|
| LLM generiše opasan Python/JS | Kritičan | Samo u sandbox worker-u, bez mreže/tajni, stroga izlazna konverzija u pasivni GLB |
| Curenje privatnih informacija | Visok | Samo postojeći read-only allowlist API i portrait proxy |
| Mešanje režima/statusa | Visok | Zasebni UI atributi, testovi i legenda |
| Velika GPU/CPU potrošnja | Srednji | 5 radnih mesta, dpr ≤1.5, on-demand render, budžet poligona u F5 |
| Nejasna licenca dataseta | Visok | Apache kod odvojen od CC-BY-NC-SA podataka; bez dataseta u produkciji |
| Neuspeh 3DCodeVerse | Srednji | Proceduralni WebGL F1 potpuno radi bez harness-a |
| Nema WebGL-a / spor uređaj | Srednji | HTML lista i 2D postojeći UI |

## 8. Procena resursa (radne, ne ugovorne vrednosti)

- F1/F2: 3–5 programerskih dana za kod, pregled i testiranje sa stvarnim podacima. Početni kostur pripremljen, ali nije verifikovan u produkciji.
- F3/F4: 2–4 nedelje, zavisno od kompleksnosti prikaza i UX revizija.
- F5: 1–3 nedelje za izolovani worker i QA nad 10–20 modela (bez fine-tuninga modela).
- F6: zasebna optimizacija i load-test; ne obećavati broj istovremeno prikazanih agenata dok se ne izvrše merenja.
- F1 računarska infrastruktura: običan browser koji podržava WebGL, bez posebnog GPU servera.
- F5 trošak: model API tokeni, harness pokušaji, provere i eventualni GPU/Blender; limit i budžet tek nakon malog merenog uzorka.

## 9. Preporučeni redosled

1. Otvoriti draft PR za F1/F2 na `zadatak/TSK-WK3D-001`, pregledati diff.
2. CI sva četiri gate-a (pytest, ruff, canon_lint, migracije).
3. Deployment na staging sa već postojećim agentima i njihovim portretima.
4. Proveriti interakcije, TOTP, 3D performanse, mobilne uređaje i rollback.
5. Tek nakon odobrenja spojiti PR u `main`.
6. Zatim posebni ADR i grana za offline 3DCodeVerse Asset Studio.

## 10. Referentni izvori

- 3DCodeVerse: https://github.com/gaoypeng/3dcodeverse
- 3DCodeVerse harness: https://github.com/gaoypeng/3dcodeverse/tree/main/harness
- Rad: https://arxiv.org/abs/2610.22341
- Veb demo: https://3dcodeverse.com/
- Naš repozitorijum: https://github.com/nikolicslobodan007-dot/mm-persona-os

Ovaj dokument ne tvrdi da je 3DCodeVerse integrisan ili da je novi 3D prikaz već instaliran na produkcionom serveru.

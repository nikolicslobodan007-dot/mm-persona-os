# ADR-0063 — Priručnik je izmeren pogrešnim metrom

- **Status:** prihvaćen (01.10.2026.)
- **Prethodi:** ADR-0060 (priručnik radnog mesta), ADR-0054 (kućni stil u
  promptu), ADR-0041 (brif i plafoni), ADR-0061 (zaštićena zona se čita),
  ADR-0033 (pravilo nula)
- **Menja:** ADR-0060 §2 — jezgro se ne meri prema `PROMPT_BUDGET_CHARS`;
  ADR-0060 §Posledice — nosilac je zaseban model, ne `KnowledgeFact`
- **Canon:** §17 (radna mesta), §10 (memorija i poreklo), §6.4

## Šta se desilo

ADR-0060 §2 kaže: „Budžet je 4000 znakova (`PROMPT_BUDGET_CHARS`)". Po tom
broju je 30.09. izmereno jezgro za `RAZ-PRO` i objavljeno kao **37,5 % budžeta**.

`PROMPT_BUDGET_CHARS` je budžet **pouka urednika**, a pouke urednika ne ulaze u
prompt za kod. Provereno 01.10. — `lessons.prompt_section` se zove na tačno dva
mesta:

```
apps/content/service.py:174       ← nacrt sadržaja
apps/content/management/commands/content_eval.py:107
```

`pisac._prompt` (ADR-0044) ne zove nijedno. Priručnik za `RAZ-PRO` ide **u
prompt za kod**, čiji je plafon brif: `MAX_TOTAL_BYTES = 200 000` (ADR-0041 §1).

Izmereno nad gotovim jezgrom:

| | izmereno | kako je 30.09. prijavljeno |
|---|---|---|
| jezgro, znakova | **1495** | 1502 |
| jezgro, bajtova | **1551** | — |
| udeo u plafonu koji stvarno važi | **0,78 %** (od 200 kB) | **37,5 %** (od 4000) |
| izvori, znakova | **309** | 345 |
| udeo izvora u odeljku | **17,1 %** | „8,6 % budžeta" |

Dakle: brojilac je bio blizu, **imenilac je bio tuđi**, a zaključak koji je iz
njega izvučen („jezgro je skupo, seci ga") nije imao osnova. Procenat bez
imenioca je ukras.

## Odluka

### 1. Priručnik ima svoj plafon, vezan za plafon koji stvarno važi

`PRIRUCNIK_BUDGET_CHARS = 3000` u `apps/personas/prirucnik.py`. Nije procena
potrebe nego **granica rasta**: jezgro je 1495 znakova, pa ovo ostavlja prostor
za dopune, a i dalje je ispod jednog procenta plafona brifa.

Odeljak ulazi u **isti** plafon brifa kao referenca (ADR-0061 §5) i ranija
zakrpa. Ono što ne stane ide u `truncated` sa razlogom, kao i svaki fajl. Budžet
koji ima izuzetak nije budžet nego predlog.

Ostaje ADR-0060 §2 u onom delu koji je bio tačan: **ako jezgro ne stane, seče se
jezgro, ne podiže se plafon.** To sad proverava `test_jezgro_staje_u_budzet`.

### 2. Izvor se čuva uz pravilo; u prompt ne ulazi

ADR-0060 §3 traži da pravilo nosi odakle je. To je zahtev nad **zapisom**, i
ispunjava se poljem `source` koje je u bazi obavezno (`CheckConstraint`, pada i
kad se servis zaobiđe).

U prompt ne ulazi, i razlog nije ušteda od 309 znakova nego ovo: **agent ne može
da otvori `docs/adr/`.** To je zaštićena zona i nije u brifu (ADR-0061). Citat
koji čitalac ne može da otvori ne pomaže mu ni u čemu, a 17,1 % odeljka jeste.
Čovek izvor vidi kroz `prirucnik --spisak`; model ga ne vidi uopšte.

### 3. Nosilac je zaseban model, i to je sad izmereno

ADR-0060 je ostavio da odluči merenje: zaseban model ili `KnowledgeFact`.
Izmereno nad gotovim jezgrom — `KnowledgeFact` traži `source` kao **strani ključ
ka zapisu izvora**, plus trojku `subject`–`predicate`–`object_json` i
`confidence`. Pravilo priručnika nije tvrdnja o svetu nego uputstvo sa
**redosledom** i **ključem po kom se gasi**; da bi ušlo u tu tabelu, moralo bi
da se izmisli izvor-zapis i da se redosled sakrije u `object_json`.

Zato `PositionHandbookRule` uz `Position`, sa osam polja koja su zaista
potrebna: mesto, ključ, redosled, tekst, izvor, aktivno, razlog gašenja, potpis.

Dva uslova stoje u **bazi**, ne u servisu:

| uslov | zašto baš u bazi |
|---|---|
| izvor ne sme biti prazan | ADR-0060 §3 je inače tvrdnja koju ništa ne proverava |
| ugašeno pravilo ima razlog i potpis | ADR-0036 §1 — tiho ugašenih pravila nema |

### 4. Priručnik visi o otvorenom primarnom rasporedu

`mesto_persone` gleda `Assignment` bez `ended_at`, `is_primary=True`. Ko pređe na
drugo mesto, istog dana vidi drugi priručnik; ko nema raspored, ne vidi nijedan i
prompt radi kao i pre. To je ADR-0060 §1 sproveden, a ne samo izgovoren.

## Šta je odbačeno

- **Podići `PRIRUCNIK_BUDGET_CHARS` na nekoliko hiljada „jer ima mesta".** Ima
  mesta danas, kad je priručnik jedan i kratak. Granica rasta koja se postavlja
  prema trenutnom slobodnom prostoru nije granica.
- **Slati izvore u prompt pa neka model odluči šta mu treba.** Model ne može da
  otvori nijedan od njih. Vidi §2.
- **Gurnuti pravila u `EditorialLesson` sa praznom personom.** Kućni stil tako
  već radi (ADR-0054), pa je bilo privlačno. Ali pouka se prepoznaje po tekstu, a
  pravilo priručnika mora da ima ključ — inače ispravka zareza pravi duplikat, a
  `--ugasi` nema za šta da se uhvati. Uz to bi priručnik za `RAZ-PRO` otišao
  **svim** agentima, jer `EditorialLesson` nema pojam radnog mesta.
- **Pustiti da pravila nastaju iz nalaza automatski.** Ostaje odbačeno
  (ADR-0060 §5): nalaz je jedan slučaj, priručnik je pravilo.
- **Ispraviti ADR-0060 §2 tiho, u mestu.** Broj je bio objavljen i po njemu je
  donet zaključak; ispravka ide u svoj ADR, kao i 1083 → 1084 (ADR-0058).

## Posledice

- `apps/personas/models.py` → `PositionHandbookRule`; migracija
  `personas 0004_adr_0060_position_handbook`.
- `apps/personas/prirucnik.py` → `upisi`, `spisak`, `ugasi`, `prompt_section`,
  `mesto_persone`, `PRIRUCNIK_BUDGET_CHARS`.
- `apps/personas/prirucnici.py` → jezgro `RAZ-PRO`, 14 pravila sa izvorima.
- `manage.py prirucnik --mesto … --spisak | --upisi | --prompt | --ugasi … --zasto …`.
- `brif.build` → `handbook`, `handbook_position`; `pisac._prompt` ih prikazuje
  **iznad** rečnika i fajlova.
- `tests/test_prirucnik.py` — 34 provere; `tests/test_models.py` dopunjen novim
  modelom. Ukupno **1139**.
- Merilo iz ADR-0060 §6 ostaje netaknuto: osnova je snimljena 30.09., i ako se
  posle priručnika ne pomeri, priručnik se gasi.

## Zapisano za ADR-0033

**Prva:** procenat je dve brojke, a proverio sam jednu. Brojilac (1502) sam
izmerio, imenilac (4000) sam **pročitao iz ADR-a i prepisao** — i taj imenilac je
pripadao drugom promptu. Rezultat je bio broj koji zvuči izmereno a nije:
„37,5 % budžeta" umesto „0,78 % plafona". **Kad se meri udeo, imenilac se
proverava isto koliko i brojilac.**

**Druga:** to je ista greška kao u ADR-0062, dva dana zaredom i u istom obliku —
rečenicu iz ranijeg dokumenta uzeo sam kao činjenicu umesto da je izmerim. Tamo
je bio broj pokušaja, ovde imenilac. **Dokument koji smo sami napisali nije
izvor; izvor je kod.**

**Treća:** greška se videla tek kad je trebalo napisati kod. Dok sam pisao ADR i
spisak pravila, broj 4000 je prolazio neprimećeno; čim je trebalo odlučiti gde
odeljak ulazi u prompt, moralo se pogledati ko taj prompt gradi — i tu je stajalo
da pouke tu nikad nisu ni bile. **Odluka koja se ne sprovede do koda nije
proverena**, ma koliko puta bila pročitana.

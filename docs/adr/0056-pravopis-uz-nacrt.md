# ADR-0056 — Nalaz Pravopisa stoji uz nacrt

- **Status:** prihvaćen (28.09.2026.)
- **Prethodi:** ADR-0055 (Rečnik), ADR-0054 (kućni stil), ADR-0010 (konzola), ADR-0033
- **Menja:** ADR-0055 — provera se više ne zove samo rukom

## Šta se desilo

ADR-0055 je uveo 8.797 odrednica i proveru nad 330 oblika koje knjiga izričito
odbija. Ali pozvati je mogao je samo čovek, kucanjem
`manage.py recnik --proveri "…"`. Urednik ne radi tako. On otvori stranicu
Sadržaj i pročita nacrt.

To je isti obrazac koji je ADR-0051 već jednom zapisao: **provera je bila gotova
na sloju koji je zgodan, a ne na sloju koji dela.** Zato je ADR-0055 i rekao
otvoreno da nije gotovo — ovaj ADR to zatvara.

## Odluka

### 1. `ContentItem.pravopis` — nalaz se čuva uz sam tekst

```json
{"provereno": true,
 "nalazi": [{"oblik": "havliju", "odrednica": "avlija",
             "tekst": "avlija (ne havlija)", "tacke": ["157e"]}]}
```

Provera se zove u `content.service.draft`, nad gotovim telom, unutar iste
transakcije u kojoj nastaje nacrt. Bez poziva modelu i bez troška.

**Proverava se svaki nacrt, i onaj koji je napisao čovek.** Urednik gleda sve što
ide napolje; poreklo teksta ne menja šta Pravopis kaže o njemu.

### 2. `provereno` postoji zato što prazan spisak laže

Nula nalaza i neuvezen Rečnik izgledaju isto — prazan spisak. Urednik koji vidi
„nema primedbi" mora da zna da li je iko gledao. Zato:

- `{"provereno": true, "nalazi": []}` — provereno, čisto;
- `{"provereno": false, "nalazi": []}` — Rečnik nije uvezen, ništa nije gledano;
  konzola to i napiše: „Pravopis: nije provereno — Rečnik nije uvezen";
- `{}` — nacrt je stariji od ove izmene. Konzola tada ne tvrdi ništa, jer ničega
  nema ni da se tvrdi. Migracija ne izmišlja nalaze unazad.

### 3. Nalaz ne obara nacrt

Status ostaje `DRAFT`, `status_reason` ostaje prazan. Spisak zabranjenih oblika
je izveden obrascem iz teksta odrednica i ume da pogreši (ADR-0055 meri: 4
pogotka na 35.704 reči, od toga dva sporna). Provera koja obara nacrt na osnovu
takvog spiska stajala bi između agenta i posla, a merila bi nas, ne njega.

Uz nalaz u konzoli stoji i rečenica da spisak ume da pogreši. Lažan oblik se gasi
sa `manage.py recnik --utisaj <oblik> --zasto "…"`.

### 4. Nalaz ide na oba mesta gde se nacrt gleda

- **konzola**, stranica Sadržaj — tamo urednik zaista radi (ADR-0010);
- **API**, `item_out` → polje `pravopis`.

Testovi dodiruju oba: jedan renderuje stranicu i traži „havliju" i „t. 157e" u
HTML-u, drugi čita JSON. Bez toga bi „gotovo" opet značilo „radi u funkciji koju
niko ne poziva".

## Šta je odbačeno

- **Automatska ispravka** („havliju" → „avliju"). Isto obrazloženje kao u
  ADR-0054 i 0055: popravljač krije koliko model greši, a to je broj koji nam
  treba pre nego bilo koja popravka.
- **Slanje nacrta modelu na drugi krug sa nalazima.** To je još jedan poziv i još
  jedan trošak, za grešku koja se u tekstu vidi golim okom. Ako se izmeri da ih
  urednik stalno ispravlja rukom, to je svoj ADR.
- **Odvojena tabela za nalaze.** Nalaz važi za tačno jedan tekst i umire s njim;
  strani ključ i migracija zbog spiska od nula do tri stavke bili bi teži od
  problema.
- **`status_reason` umesto novog polja.** Tamo stoji zašto je nacrt odbijen, a
  nalaz Pravopisa ne odbija ništa. Spajanje to dvoje bi značilo da se kasnije ne
  zna ko je koga oborio.
- **Provera i pri izmeni nacrta.** Za sada se zove samo pri nastanku. Kad urednik
  izmeni telo, nalaz zastareva — i to ovde **piše**, umesto da se otkrije kasnije.

## Posledice

- `ContentItem.pravopis` (**migracija `0007_pravopis_nalazi`**, samo dodaje polje),
  `recnik.dostupan()`, `recnik.nalaz_za_zapis()`, poziv u `content.service.draft`,
  polje u `item_out`, prikaz u `console/templates/console/content.html`.
- 10 novih provera; ukupno **1064**.
- Posle deploy-a ide `migrate`. Ako Rečnik nije uvezen, nacrti dobijaju
  `provereno=false` i sve radi — samo ne proverava ništa, i tako i piše.

## Zapisano za ADR-0033

Ovo je ADR koji postoji zato što je prethodni rekao istinu o sebi. ADR-0055 je u
odeljku Posledice imao red **„Nije urađeno: provera se još ne zove iz
`content.service.draft`."** Da tog reda nije bilo, danas bi u sistemu stajao
rečnik od 8.797 odrednica koji niko ne poziva, i svi bismo mislili da agenti
prolaze pravopisnu proveru.

Pravilo je već zapisano u ADR-0051 i ovde se samo potvrđuje: **posao je gotov kad
ga vidi onaj kome je namenjen.** Novo je samo to koliko je jeftino bilo reći da
nije gotov — jedan red u ADR-u.

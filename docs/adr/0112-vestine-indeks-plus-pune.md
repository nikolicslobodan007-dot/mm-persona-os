# ADR-0112 — Veštine: indeks + pune, da agent zna ceo svoj alat

- **Status:** prihvaćen (18.10.2026.)
- **Povod:** Deklarisani prioritet je sakupljanje veština za agente, a u paket
  je stizalo samo ~4 od 451. Uzrok izmeren 18.10: puna linija veštine (svi
  koraci + opis + izvor) je ~984 znaka ≈ **246 tokena**, pa u plafon od 1000
  (profil `content_creation`) stane samo četiri. Agent je znao 4 veštine.
- **Prethodi:** ADR-0096 (veštine u paketu), ADR-0101 (sektor bira redosled),
  ADR-0084 (znanje nosi poreklo)
- **Menja:** `apps/memory/context.py`, `tests/test_memory.py`
- **Ne dira:** `apps/orchestration/brif.py` — on ima svoj put za veštine
  (agent za kod/aider) i svoj plafon; ovo je samo paket persone.

## Odluka

**1. Dva sloja u istom odeljku.** Vrh rangiranja (ADR-0101) ulazi **u celini**
— sa koracima; ostatak iz istog budžeta ide kao **indeks**: ime veštine i
čemu služi, bez koraka. Tako agent zna ceo svoj alat (~30-40 veština), a
detaljne korake ima za ono najverovatnije potrebno. Ovo je obrazac koji
koriste i pravi sistemi veština (ime+opis uvek, puni postupak po potrebi).

**2. Koliko punih** — `VESTINE_PUNIH = 4`, postavljeno rukom, menja se ADR-om
kad merenje kaže. Ako puna linija ne stane u preostali budžet, veština ne
ispada nego ulazi kao indeks (makar ime).

**3. I indeks nosi izvor** (ADR-0084): znanje bez porekla se ne šalje, pa i
kratka linija ima oznaku `izvor <title>`.

**4. Provenijencija se seče iz opisa.** Napomena je u korpusu nosila i opis i
rep provenijencije („… | Uvezeno iz …", „Destilovano iz …"). Rep duplira
`izvor` i samo troši tokene — seče se pre nego što uđe u red (i kad napomena
počinje provenijencijom). Opis se skraćuje na reč: 200 znakova za punu, 80 za
indeksnu liniju.

**5. Rangiranje i `vestina_ids` se ne menjaju.** Isti redosled kao ADR-0101;
`vestina_ids` beleži sve što je ušlo, pune i indeksne, u tom redosledu.

## Cena, merena

Indeksna linija je ~23 tokena naspram ~246 za punu. U isti plafon od 1000
sada staje 4 pune + ~30 indeksnih umesto 4 pune. Agent prelazi sa „zna 4
veštine" na „ima 4 u celini, svestan ~30 po imenu".

## Šta ovo NE radi

- **Nema još „traži korake kad zatrebaju" na delu.** Indeks najavljuje veštinu;
  dovlačenje punih koraka indeksne veštine usred rada je sledeći korak (svoj
  handler/šav), kad se pokaže da je potrebno. Za sada indeks daje svest o
  alatu i gist iz imena/opisa.
- **Ne menja koje veštine su podobne** (licenca SLOBODNA, izvor aktivan) ni
  njihov redosled — samo koliko ih i u kom obliku stane.

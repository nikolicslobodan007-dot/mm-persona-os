# ADR-0046 — Ispravka nalaza

- **Status:** prihvaćen (26.09.2026.)
- **Prethodi:** ADR-0045 (nalaz koji piše čovek), ADR-0042 (merenje), ADR-0034 §5.2
  (nema samoodobravanja), ADR-0033 (pravilo nula)

## Povod

Prva dva ljudska nalaza upisana su **bez dijakritike** — „sece", „kaze",
„precutano". Ja sam ih tako otkucao: plašio sam se navodnika i razmaka u
`--tvrdnja`, pa sam preventivno skinuo slova. Nisam proverio da li treba, a pola
sata ranije je `--zasto "Ograniči ukupnu dužinu…"` prošlo netaknuto. Dakle
pretpostavka, i to u komandi kojom se upisivao nalaz **o pretpostavci**.

Trajni zapis prve recenzije u firmi ostao je u lošem srpskom. Način da se to
ispravi nije postojao.

## Zašto ne dupliranjem

Prvo rešenje koje se nudi — upisati dva nova nalaza sa ispravnim tekstom i
zatvoriti stara — **kvari merenje**. `ucinak` broji nalaze po agentu (ADR-0042),
pa bi Lazar dobio četiri nalaza umesto dva. Mera bi lagala da bi pravopis bio
lep.

Drugo rešenje — zatvoriti stara kao `REJECTED` — laže o ishodu: prigovor nije
odbijen, nego prepisan.

## Odluka

`manage.py nalaz --izmeni <prefiks> --tvrdnja "…"` ispravlja **tvrdnju** nalaza.
Tri granice, i sve tri razdvajaju ispravku od prepravljanja:

### 1. Samo otvoren nalaz

Zatvoren nalaz je presuđen; njegov tekst je deo te presude. Ako je presuda
pogrešna, ide **nov** nalaz, a ne prepravka starog. Istorija recenzije koja se
može naknadno doterati nije istorija.

### 2. Težina se ne menja

Naknadno podizanje na `BLOCKER` je nova odluka o tuđem radu, ne ispravka — i
zaobišlo bi pravilo iz ADR-0045 da se težina daje pri upisu, sa izvorom. Promena
težine ide kao nov nalaz.

### 3. Izvršilac ne dira nalaz na sopstveni rad

Isto kao kod zatvaranja (ADR-0045 §3). Provera je po `actor`-u.

Stara tvrdnja ostaje u auditu (`task.finding.amended`, polja `pre` i `posle`), pa
se svaka ispravka vidi i posle.

## Šta je odbačeno

- **Dupliranje nalaza radi ispravke teksta** — kvari `ucinak`.
- **`REJECTED` kao „prepisano"** — laž o ishodu.
- **Ispravka zatvorenog nalaza.**
- **Ispravka težine i fajla.** Tada bi „ispravka" značila novu presudu pod starim
  identifikatorom.
- **Brisanje nalaza.** Nalaz koji nestane bez traga je nalaz koji se nikad nije
  desio; za povučen prigovor postoji `REJECTED` sa napomenom.

## Posledice

- `zadaci.amend_finding`, `manage.py nalaz --izmeni`, 8 novih provera u
  `tests/test_nalaz.py`. Nema migracije.
- Obe tvrdnje iz prve recenzije ispravljene su ovim putem, a ne novim nalazima.

## Zapisano za ADR-0033

Skidanje dijakritike „za svaki slučaj" je isti oblik greške kao `PERSONA_REPO` i
`base_sha`: mera opreza uvedena bez provere da li je potrebna. Razlika je što je
ova ostavila trag u podacima, a ne u kodu — i zato je bilo potrebno napraviti
način da se trag ispravi, umesto da se sakrije.

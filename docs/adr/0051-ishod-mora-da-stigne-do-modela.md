# ADR-0051 — Ono što brif zna mora da stigne do modela

- **Status:** prihvaćen (27.09.2026.)
- **Prethodi:** ADR-0050 (piscu se kaže šta je bilo sa njegovim radom), ADR-0041
  (brif), ADR-0044 (pisac), ADR-0033 (pravilo nula)
- **Menja:** ADR-0050 — njegova tvrdnja nije važila za ceo lanac

## Šta se desilo

Posle ADR-0050 su nalazi vraćeni na `OPEN`, upisan je nov nalaz sa tačnim
brojevima pogrešnih `@@` zaglavlja, i `brif.build` je na serveru vratio:

```
ISHOD: ODBIJENA je i nije ušla u kod. Razlog: nema napretka — ista zakrpa je već predata
BLOCKER … MAJOR … MAJOR (sa brojevima)
```

Pokušaj posle toga vratio je **ponovo isti diff**, četvrti put. 7 centi.

Promenjen ulaz koji daje identičan izlaz je znak da promena nije stigla do modela.
Nije ni stizala: `ishod` postoji u `brif.build`, a tekst prompta sastavlja
`pisac._prompt`, koja ga **nije čitala**. Ono što je model zaista dobijao glasilo je,
za svaku raniju zakrpu bez razlike:

```
TVOJA RANIJA ZAKRPA NA OVOM ZADATKU (stoji na grani, NIJE spojena u glavnu
granu, pa je u fajlovima ispod nema):
```

Za odbijenu zakrpu je to neistina, i to ona najgora vrsta: kaže mu da je rad na
mestu. Sa takvom rečenicom iznad teksta, vraćanje istog diffa je razumna odluka —
i model ju je doneo tri puta zaredom, svaki put plaćeno.

## Odluka

### 1. `_prompt` čita `ishod`

Umesto nepromenljive rečenice o grani, iznad teksta zakrpe stoji ono što se
stvarno desilo (ADR-0050 §1).

### 2. Zakrpa bez commita nosi izričitu zabranu ponavljanja

Kad `applied_sha` nije upisan, prompt dodaje:

> Ova zakrpa NIJE nigde primenjena. Ne šalji je ponovo: ista zakrpa se odbija bez
> merenja. Napiši novu, koja otklanja ono što piše iznad. Tekst ispod ti služi
> samo da vidiš šta si ranije napisao.

Otisak je i do sad odbijao ponovljenu zakrpu — ali **posle** naplaćenog poziva.
Kočnica koja se aktivira tek kad je novac potrošen nije kočnica nego zapisnik.

### 3. Provera se piše nad promptom, ne nad brifom

Novi testovi zovu `pisac._prompt` i gledaju tekst koji model dobija. Provera nad
`brif.build` ovo ne može da uhvati — što se i videlo: taj izlaz je bio tačan sve
vreme dok je prompt govorio suprotno.

## Šta je odbačeno

- **Izbacivanje ranije zakrpe iz prompta.** Bez nje je brif protivrečan (ADR-0047):
  nalazi opisuju kod kog u priloženim fajlovima nema.
- **Provera otiska pre poziva modelu.** Otisak se računa nad diffom koji model tek
  treba da napiše; pre poziva nema šta da se poredi. Ono što se može uraditi
  unapred je da mu se kaže da ne ponavlja — i to je ono što se radi.
- **Podizanje plafona pokušaja.** Plafon nije bio problem; sadržaj prompta jeste.

## Posledice

- `pisac._prompt` — blok o ranijoj zakrpi.
- 5 novih provera nad tekstom prompta; ukupno 980.
- Nema migracije.

## Zapisano za ADR-0033

ADR-0050 sam isporučio uz tvrdnju „brif kaže piscu šta je bilo sa njegovim radom".
Ta tvrdnja je važila za `brif.build` i nije važila za tekst koji model čita — a taj
tekst je jedino mesto gde je uopšte bila bitna.

Proveru sam napravio tako što sam na serveru ispisao izlaz `brif.build` i video
tačan `ishod`. To je sloj koji je bilo lako pogledati, a ne sloj koji dela. Isti
oblik greške kao jutros u 09:25, kad sam zaključio o brifu ne pogledavši ga —
razlika je samo u tome što sam ovog puta gledao, ali pogrešnu stvar.

Pravilo koje iz toga sledi, uz ono iz ADR-0048 o statusu: **provera se radi nad
slojem koji dela, ne nad slojem koji je zgodan.** Za prompt to znači sam prompt.

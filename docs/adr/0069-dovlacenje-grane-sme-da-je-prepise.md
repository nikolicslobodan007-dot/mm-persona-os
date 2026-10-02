# ADR-0069 — Dovlačenje agentove grane mora da sme da je prepiše

- **Status:** prihvaćen (02.10.2026.)
- **Prethodi:** ADR-0043 (rezultat ide u granu), ADR-0038 §6 (`main` menja čovek),
  ADR-0033 (pravilo nula)
- **Menja:** `grane.Command.handle` — ispisani refspec dobija `+`
- **Canon:** §6.4, §20

## Šta se desilo

`TSK-01M3Y4Q9H1WK9M9WN7J5HZEDZE` je zatvoren posle osam pokušaja. Grana
`zadatak/TSK-01M3Y4Q9…` je u međuvremenu nosila osam različitih commita — jer
poslušnik svaki pokušaj gradi iz **čistog primerka** i gura sa
`--force-with-lease`. Grana zadatka nije istorija, nego poslednji ishod.

Komandu za dovlačenje ispisuje `manage.py grane`, i ona je od ADR-0043 glasila:

```
git fetch persona:apps/mm-persona-os 'refs/heads/zadatak/*:refs/remotes/agent/*'
```

Bez `+`. Izmereno 02.10.2026. na radnoj mašini:

| korak | ishod |
|---|---|
| `git fetch` po ispisanoj komandi | `! [rejected] zadatak/TSK-01M3Y4Q9… (non-fast-forward)` |
| šta je ostalo u `agent/TSK-01M3Y4Q9…` | `2e36011` — commit prvog pokušaja |
| šta je na serveru | `e98cd30` — commit osmog |
| `git merge agent/TSK-01M3Y4Q9…` | prošlo **čisto**, 17 dodatih redova |
| šta je ušlo u radni primerak | `if not sender or BOUNCE_SENDER.search(...)` |

Taj red je **kvar koji je recenzija već odbila**: pošiljalac čija se adresa ne
može pročitati proglašava se obaveštenjem o nedostavljivosti. Zbog njega je
zadatak i išao dalje, pet pokušaja i tri izmerena sata.

Spajanje je poništeno (`git reset --hard origin/main`) i nije otišlo na GitHub.
Prošlo je bez ijedne poruke o grešci: `git fetch` je odbijanje prijavio, a
`git merge` je posle toga radio tačno ono što je tražen — nad starim commitom.

## Odluka

### 1. Refspec nosi `+`

```
git fetch persona:apps/mm-persona-os '+refs/heads/zadatak/*:refs/remotes/agent/*'
```

`+` ne znači „nasilno" nego „ova grana sme da se prepiše", što je tačan opis
grane zadatka. Lokalni `refs/remotes/agent/*` je ogledalo serverske grane i nema
sopstvenu istoriju koju bi `+` mogao da uništi.

### 2. Zašto ne obrnuto — da grana zadatka postane istorija

Razmotreno i odbačeno u §„Šta je odbačeno". Ukratko: commit pre kapija (ADR-0043,
`runner.py:148`) postoji da bi se merio **svaki** pokušaj, a devet commita po
zadatku na grani koju čovek gleda nije pregled nego šuma.

### 3. Dovlačenje i spajanje su dva koraka, i između njih se gleda

Komanda koja spaja ne sme da se daje u istom dahu sa komandom koja dovlači. Ovo
je pravilo o radu, ne o kodu, i upisano je ovde jer je 02.10. prekršeno:
spajanje je dato pre nego što je iko pogledao ishod dovlačenja.

## Šta je odbačeno

- **Ostaviti kako jeste i pamtiti da treba `+`.** Pravilo koje se pamti je
  pravilo koje se jednom zaboravi; ovo se već zaboravilo prvi put kad je bilo
  potrebno.
- **Dodati `--force` umesto `+` u refspec.** Isto dejstvo, ali tupo: `--force`
  važi za sve refspecove u komandi, `+` samo za ovaj. Uža alatka za uži posao.
- **Praviti po granu po pokušaju (`zadatak/TSK-…/3`).** Rešilo bi prepisivanje
  tako što ga ukida, ali bi čoveku na sto stavilo osam grana umesto jedne, i
  tražilo pravilo o tome koja je poslednja. Grana po zadatku je tačan oblik;
  problem je bio u dovlačenju, ne u njoj.
- **Da poslušnik ne gura dok nije poslednji pokušaj.** Ne znamo unapred koji je
  poslednji — to i jeste razlog zbog kog se meri svaki.

## Posledice

- `apps/orchestration/management/commands/grane.py` → `+` u ispisanom refspecu,
  i objašnjenje zašto, u dokumentaciji modula i uz sam red.
- `tests/test_rezultat.py` → `test_refspec_nosi_plus`; provera traži `+` i
  izričito odbija oblik bez njega, da se stara varijanta ne vrati tiho.
- Ukupno **1171** provera.

## Zapisano za ADR-0033

**Prva:** ovaj kvar je bio vidljiv svaki put kad bi se grana ponovo gurnula, a
primećen je tek kad je u radni primerak ušao kod koji smo ranije odbili. **Alat
koji greši tiho čeka da ga neko nasamari.** `git fetch` je odbijanje uredno
prijavio — jednim redom među dvanaest, i niko ga nije pročitao, uključujući mene.

**Druga:** dao sam komandu za spajanje u istoj poruci sa komandom za dovlačenje,
„da ne gubimo vreme". Dobitak je bio jedan krug razgovora; trošak je bio pokvaren
kod u radnom primerku i pola sata vraćanja. **Korak koji proverava prethodni se
ne pakuje zajedno s njim.**

**Treća:** ADR-0043 je ispisao komandu za dovlačenje i time preuzeo odgovornost
za nju, ali je nije nijednom izvrtao nad granom koja je **već jednom** dovučena.
Provera je postojala i prolazila — tražila je da u ispisu stoji `git fetch`, ne
da taj `git fetch` radi. **Provera koja gleda tekst komande nije provera
komande.**

# ADR-0087 — Zakrpu pravi `git`, pa `git` ulazi u sliku

- **Status:** prihvaćen (14.10.2026.)
- **Povod:** Šav iz ADR-0086 treba zakrpu, a u slici nema `git`-a. Pitanje je
  postavljeno kao izbor, ne kao navika.
- **Prethodi:** ADR-0086 (šav za Aidera), ADR-0085 (Aider je napisao zakrpu),
  ADR-0082 (aider u kavezu), ADR-0079 (prvo potraži gotovo rešenje), ADR-0033
- **Menja:** `Dockerfile` — `git` u postojeći `apt-get` sloj. Jedna reč.
- **Canon:** §7.3

## Izmereno

13.10., u `web` kontejneru: `sh: 1: git: not found`. Zato je Aider tog dana
pušten sa `--no-git`, a `git diff` je vrćen rukom na hostu.

14.10., u `deploy/aider/pokretac.py`, funkcija `_izvestaj_iz_codera` vraća
**tačno sedam ključeva**:

```
model, tokens_sent, tokens_received, cache_read, cache_write, finish, greska
```

Ni spiska izmenjenih fajlova, ni zakrpe. **To nije propust pokretača** — njegov
posao je mera, i meru radi tačno (ADR-0086). Ali znači da zakrpu mora da napravi
neko drugi, unutar kontejnera, jer šav se vrti tamo.

## Odluka

`git` ulazi u sliku, u sloj koji već postoji (`build-essential libpq-dev`).
Jedna reč, nijedan nov sloj.

Alternativa je bila da razliku računamo sami, u Pajtonu, preko `difflib`. Odbija
se po pravilu od 07.10. („vadimo sve što možemo, ne pišemo kod bez veze") i po
ADR-0079: `git diff` je rešen problem — preimenovanja, prava fajla, binarni
sadržaj, prazni redovi na kraju. Naš differ bi te slučajeve otkrivao jedan po
jedan, kroz odbijene zakrpe, i svaki bi koštao po jedan pokušaj modela.

ADR-0085 je rekao da `git` ulazi u sliku „tek kad za njega postoji izmeren
razlog". Ovo je taj razlog, i on je izmeren, ne pretpostavljen.

## Šta se ovim NE menja

Aider i dalje radi sa `--no-git`. To što `git` postoji u slici ne znači da ga
Aider sme koristiti: sa upaljenim `git`-om on pravi mapu repozitorijuma i ume da
commituje, a oboje je neizmereno. Mapa je i dalje otvoreno pitanje iz ADR-0085 i
meri se zasebno, kad za to dođe red.

Dakle `git` je ovde **naš alat za jednu stvar** — da napravi zakrpu iz radnog
primerka. Ništa drugo mu se ne poverava dok se ne izmeri.

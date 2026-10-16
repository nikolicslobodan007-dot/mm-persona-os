# ADR-0094 — Aider dobija pravi koren, a zakrpa osnovu

- **Status:** prihvaćen (16.10.2026.)
- **Povod:** Posle ADR-0092 nov fajl je prvi put stigao u zakrpu — i stigao je
  na pogrešno mesto: `apps/memory/apps/memory/migrations/0008_…py`.
- **Prethodi:** ADR-0093, ADR-0092, ADR-0087, ADR-0085, ADR-0086, ADR-0033
- **Menja:** `deploy/aider/pokretac.py` — `--no-git` izlazi iz argv,
  `--no-dirty-commits` ulazi. `apps/orchestration/pisac.py` — `_git_osnova` i
  `_git_diff_od_osnove` umesto `_git_diff_cached`. Testovi uz oboje.
- **Canon:** §7.3

## Izmereno

`aider/utils.py:260`:

```python
def find_common_root(abs_fnames):
    if len(abs_fnames) == 1:  return dirname(...)
    elif abs_fnames:          return commonpath(...)
    ...
    return safe_abs_path(os.getcwd())
```

A `aider/coders/base_coder.py`:

```
447:  self.root = self.repo.root
476:  self.root = utils.find_common_root(self.abs_fnames)
```

Sa `--no-git` repozitorijuma nema, pa ide red 476: koren je najmanji zajednički
direktorijum **fajlova u razgovoru**. Pošto je `tests/test_vestine.py` bio
odsečen (ADR-0093), svi fajlovi su bili pod `apps/memory` — i taj direktorijum
je postao koren. Svaki nov fajl je zato dobio `apps/memory/` ispred putanje koju
je model napisao tačno.

U `aider/args.py` **nema zastavice kojom se koren zadaje**; postoji samo
`--subtree-only`, koji traži git. Dakle koren se dobija jedino tako što Aider
ima repozitorijum.

## Odluka

`--no-git` izlazi. Radni primerak je i dosad bio pravi `git clone --local`, pa
je `repo.root` tačno ono što nam treba.

To Aideru daje i pravo da commituje, pa se dodaje `--no-dirty-commits` uz
postojeći `--no-auto-commits`.

I, što je važnije od zastavica: **zakrpa se više ne računa od HEAD-a nego od
osnove zabeležene pre pokretanja.** `git diff --cached` poredi HEAD sa indeksom;
commit pomera HEAD, razlika bi bila prazna, i dobili bismo `PRAZNA_ZAKRPA` sa
lažnim imenom — tačno onakav kvar kakav smo lovili tri dana. Sa osnovom je ishod
isti bez obzira da li je commitovano. Ovo nije zasebno poboljšanje nego
**posledica** prve odluke i zato stoji u istom ADR-u.

## Šta se ovim NE menja

`git add -A` se i dalje nikad ne koristi; u indeks idu ograde zadatka (ADR-0092).

Otvoreno i **mora se izmeriti na prvom pokretanju**: ADR-0085 je zabeležio da
`--no-git` gasi Aiderovu mapu repozitorijuma (`Repo-map: disabled`). Sa git-om
mapa može da se upali; trebalo bi da je drži ugašenom `use_repo_map: false` iz
fajla podešavanja, ali to je **pretpostavka dok se ne pročita ispis**. Ako se
mapa upali, menja se i cena i sadržaj konteksta, i tada ide svoj ADR.

# ADR-0043 — Rezultat rada ide u granu

- **Status:** prihvaćen (25.09.2026.)
- **Prethodi:** ADR-0038 (zakrpa i ljudska kapija pred `main`), ADR-0039 (tačke za
  poslušnika), ADR-0040 (red drži nemeren posao), ADR-0042 (merenje), ADR-0033
  (pravilo nula)

## Problem

Lanac je radio do kraja, a proizvoda nije bilo. Poslušnik napravi radni primerak,
primeni zakrpu, izvrti četiri kapije — i obriše sve. Ostane zapis da je bilo zeleno
i **nijedan red koda koji bi čovek mogao da pogleda.**

To je merenje bez proizvoda. Agent radi, brojevi rastu, a nema šta da se spoji.

## Odluka

Kad su sve tražene kapije zelene **nad tom zakrpom**, poslušnik pravi commit i gura
ga u granu `zadatak/TSK-…` lokalnog repozitorijuma na serveru. `POST
/tasks/{id}/result` to beleži. `main` se ne dodiruje.

### 1. Commit se pravi PRE kapija, ne posle

Kapije za sobom ostavljaju keš i artefakte. Commit posle njih uhvatio bi i to.
Ovako commit sadrži tačno ono što je zakrpa donela.

Dobija se i jedna ispravka: do sada se uz svaki ishod kapije slala **osnova**
(`base_sha`) kao „commit nad kojim je mereno". To nije bila istina — osnova je ono
nad čim je zakrpa pisana, a merilo se nad osnovom **plus zakrpom**. Sada se šalje
sha tog commita, pa `GateResult.commit_sha` konačno pokazuje na stablo koje je
zaista mereno.

### 2. Autor je agent, pošiljalac je sistem

`git` razlikuje `author` i `committer`; koristimo to. Autor je agent, sa adresom
`p-000xx@agenti.webkorporacija.com` — jedinstvenom, da `git log --author` radi.
Pošiljalac je uvek `MM Persona OS <poslusnik@agenti.webkorporacija.com>`.

Ko je napisao i ko je pustio su dva pitanja i posle godinu dana se ni iz čega
drugog ne mogu rekonstruisati.

**Poddomen `agenti.webkorporacija.com` ne sme da dobije MX zapis.** Adresa je
oznaka, ne sanduče; ako počne da prima poštu, postaje kanal koji niko nije odobrio.

### 3. Ime grane i poruka se prave u aplikaciji

Naslov i obrazloženje zadatka piše agent. Da poslušnik sam sastavlja poruku, taj
tekst bi ušao u komandnu liniju. Zato aplikacija šalje gotovo ime grane i gotovu
poruku, poslušnik im **proverava oblik** i poruku prosleđuje kroz fajl (`git commit
-F`), nikad kao argument.

Iz istog razloga se iz imena autora uklanjaju `<`, `>` i sve upravljačke znakove:
bez toga agent sam sebi bira ime autora commita jednim prelomom reda u naslovu.

### 4. Grana se pomera samo sa onoga što aplikacija zna

Poslušnik gura sa `--force-with-lease=refs/heads/<grana>:<commit_sha koji
aplikacija ima>`. Ako se grana na disku razlikuje, guranje pada — neko ju je dirao
rukom, a to je tačno trenutak kada mašina treba da stane, ne da pregazi.

Kad grane još nema, guranje je obično, pa pada ako grana ipak postoji. I to je
ispravno: grana koju aplikacija ne zna nije njena.

### 5. Zadatak se ovde NE zatvara

Grana je ponuda na sto. `zadaci.finish` i spajanje u `main` ostaju ljudska ruka
(ADR-0038 §6). Poslušnik i dalje ne zatvara ništa — pravilo iz ADR-0039 §3 stoji.

### 6. Ključ za guranje nije potreban

Ovo je bilo zapisano kao otvorena odluka („treba deploy ključ sa pravom pisanja i
zaštita grane `main`"). Pokazalo se da je pretpostavka (ADR-0033).

Server ne gura nikuda. Grana nastaje u **lokalnom** repozitorijumu na serveru, a
radna mašina je dovlači preko `ssh`:

```
git fetch persona:apps/mm-persona-os 'refs/heads/zadatak/*:refs/remotes/agent/*'
```

Put je server → radna mašina → GitHub, i na njemu je čovek. Serverski ključ ostaje
read-only, `main` ostaje bez automatskog pisca, a ništa od toga ne treba menjati.

## Šta je odbačeno

- **Guranje na GitHub sa servera.** Tražilo bi ključ sa pravom pisanja na mašini
  koja vrti tuđi kod. Cena nesrazmerna koristi — vidi §6.
- **Grana po zakrpi** (`zadatak/TSK-…/zakrpa-…`). Uredno, ali se pravi šuma grana
  koju niko ne čisti. Jedna grana po zadatku, a stariji commit ostaje dostupan po
  `TaskPatch.applied_sha`.
- **Zatvaranje zadatka po zelenim kapijama.** Zeleno znači da kod prolazi kapije, ne
  da radi ono što je traženo. To je i dalje ljudska ocena.
- **Čuvanje imena grane u bazi.** Izvedeno je iz `public_id`; kolona bi samo mogla
  da se razmimoiđe sa zadatkom.

## Posledice

- `apps/orchestration/rezultat.py`, `POST /tasks/{id}/result`, `manage.py grane`.
- `deploy/runner/runner.py`: `zapamti()`, `gurni()`, i izmenjen redosled — commit
  pre kapija.
- `ucinak`: `APPLIED` se broji kao prihvaćena zakrpa i dobija svoju kolonu
  (`GRANA`). Bez toga bi agentu **uspeh smanjivao** broj prihvaćenih — mera bi
  kažnjavala upravo ono što meri.
- `tests/test_rezultat.py` (29 provera), dopune u `test_api_zadaci.py` i
  `test_runner.py`. Nema migracije: `CodeTask.commit_sha` i `TaskPatch.applied_sha`
  postoje od ADR-0035 i do sada su stajali prazni.

## Nalaz uz ovaj ADR

Testovi koji traže bazu su se u radnom okruženju mesecima **preskakali**, pa su se
pisali naslepo i proveravali tek na serveru. Baza je ovde bila dostupna sve vreme —
samo nije bila podignuta. Od ovog ADR-a se podiže lokalno i pun `pytest` se vrti pre
isporuke. Pretpostavka je bila moja, ne mašinina (ADR-0033).

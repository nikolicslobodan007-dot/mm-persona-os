# ADR-0040 — Red drži nemeren posao

- **Status:** prihvaćen (25.09.2026.)
- **Prethodi:** ADR-0039 (tri tačke za poslušnika), ADR-0038 (izvršilac i zakrpa),
  ADR-0035 (model zadatka), ADR-0033 (pravilo nula)

## Šta se desilo

Prvi pravi prolaz poslušnika je uspeo: zakrpa primenjena, sve četiri kapije zelene,
3 minuta i 8 sekundi po prolazu. Pa opet. Pa opet. **Osam puta zaredom** — 13:58,
14:01, 14:05, 14:08, 14:12, 14:15, 14:18, 14:22, 14:25 — dok ga čovek nije zaustavio.
Pola sata procesora na isti posao.

Uzrok je rupa u mom sopstvenom modelu. ADR-0039 §3 kaže da poslušnik **ne zatvara
zadatak**, i to je ispravno. Ali red je vraćao zadatke sa prihvaćenom zakrpom koji
nisu `DONE` — a zadatak ne postaje `DONE` sam od sebe. Postavio sam pravilo „poslušnik
ne zatvara zadatak" i nisam odgovorio na pitanje **šta onda izbacuje posao iz reda.**

## Odluka

**Red drži nemeren posao, ne „nezatvoren".**

`GateResult` dobija vezu ka zakrpi koju meri. Zadatak je u redu dok ima prihvaćenu
zakrpu **bez ijednog ishoda kapije**. Prvi upisan ishod — svejedno da li zelen ili
crven — znači da je merenje počelo i posao izlazi iz reda. Nova zakrpa je nov posao
i ponovo ulazi.

Tri stvari koje ovo rešava bez ijednog novog ovlašćenja:

- **Nema petlje.** Izmeren posao ne kruži.
- **Pad ne pravi beskonačan krug.** Poslušnik i na grešci prijavljuje palu kapiju sa
  zakrpom, pa i neuspeh izlazi iz reda. Ponavljanje traži novu zakrpu — to jest,
  ljudsku ili agentovu odluku, ne automatski ponovni pokušaj.
- **Poslušnik ne dobija ništa novo.** Ne zatvara zadatak, ne menja status, ne
  proglašava gotovo. I dalje samo meri i prijavljuje (ADR-0039 §3).

Uz to, `/tasks/{id}/work` izdaje **najnoviju prihvaćenu a neizmerenu** zakrpu i vraća
njen `patch_id`; `/tasks/{id}/gate` prima taj `patch_id` i odbija zakrpu koja ne
pripada tom zadatku.

## Šta je odbačeno

- **Da poslušnik zatvara zadatak** kad su sve kapije zelene. To je bila najbrža
  ispravka i pogrešna: zelene kapije nisu ispravnost (ADR-0038 §6).
- **Rezervacija posla pri preuzimanju** (`ACCEPTED` → `UZETA` na `work`). Zvuči
  uredno, ali laže: posao nije obavljen kad je preuzet, a pad bi ostavljao zakrpe
  zaglavljene u međustanju.
- **Poređenje po vremenu** („kapija novija od zakrpe"). Radi dok satovi rade.
- **Automatsko ponavljanje palog prolaza.** Ponovni pokušaj nad istim kodom daje isti
  ishod; ono što treba da se promeni je zakrpa.

## Posledice

- `GateResult.patch` + migracija `0007`.
- `queued` gleda neizmerene zakrpe; `work` vraća `patch_id`; `gate` ga prima.
- `tests/test_api_zadaci.py`: šest provera koje brane baš ovu petlju.
- Ostaje otvoreno, i nije ovim rešeno: **zelene kapije ne dokazuju koji je kod meren.**
  Slika aplikacije ima kod u `/app`, a kapije se vrte u `/rad`. Sledeći korak je
  zakrpa koja namerno obara test — ako i ona bude zelena, poslušnik meri pogrešno
  stablo.

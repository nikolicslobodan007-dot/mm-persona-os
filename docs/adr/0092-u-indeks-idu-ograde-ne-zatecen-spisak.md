# ADR-0092 — U indeks idu ograde zadatka, ne zatečen spisak fajlova

- **Status:** prihvaćen (15.10.2026.)
- **Povod:** Zadatak „KnowledgeSource dobija commit i putanju fajla" dvaput je
  vratio zakrpu sa **dva** fajla umesto pet. Nedostajala je, između ostalog,
  nova migracija. Izgledalo je kao da agent ne razume brif.
- **Prethodi:** ADR-0091, ADR-0090, ADR-0089, ADR-0086 (šav za Aidera),
  ADR-0052/0066/0067, ADR-0038 §3, ADR-0033
- **Menja:** `apps/orchestration/pisac.py` — `_za_indeks`, pozvana pre
  `_git_add`. `tests/test_pisac.py` — jedan test izmenjen, jedan nov.
- **Canon:** §7.3

## Izmereno

U `pisac._aiderom`:

```
fajlovi = [f["path"] for f in (b.get("files") or [])]
...
_git_add(radni, fajlovi)
```

A u `brif.py:433` ti fajlovi se **čitaju sa diska**. Dakle spisak sadrži
isključivo putanje koje su postojale u trenutku sastavljanja brifa.

Posledica je jednostavna i tvrda: **kroz ovaj šav agent nije mogao da napravi
nov fajl.** Čak i da ga je napisao, `git add` ga nikad ne bi dodao, pa ga
`git diff --cached` nikad ne bi prikazao. Zakrpa bi se vratila bez njega, bez
ijedne poruke o tome — tiho.

To nije otkriveno ranije samo zato što se nijedan zadatak do 15.10. nije
sudario s tim: svi su menjali postojeće fajlove.

Greška je moja (ADR-0086). Prvo sam je pripisao brifu, pa i agentu; oboje je
bilo pogrešno, i tako je i rečeno vlasniku čim se izmerilo.

## Odluka

U indeks idu **ograde zadatka** (`allowed_paths`), ne zatečen spisak fajlova.

Pravilo od 13.10. ostaje netaknuto: `git add -A` se i dalje nikad ne koristi.
Ograde su tačno navedene putanje, Aiderovi sopstveni fajlovi (dnevnik
razgovora) stoje u **korenu** radnog primerka — van ogradā — pa ih ovo ne
uvlači. Sve van ogradā `zakrpa.check` ionako odbija.

Ograda koje u radnom primerku nema se preskače, jer bi `git add` na njoj pukao;
ako ne ostane nijedna, vraća se stari spisak, da se ponašanje ne menja tiho.

## Šta se ovim NE menja

Aider i dalje u razgovor dobija samo postojeće fajlove (`--fajl`) — to je ono
što on čita. Ovo menja isključivo ono što **mi** posle sakupljamo kao zakrpu.

Otvoreno: zakrpa koja bi dodala fajl van ogradā i dalje biva odbijena, i to je
namerno. Ako zadatku treba nov fajl, njegova putanja mora biti u `--putanje`.

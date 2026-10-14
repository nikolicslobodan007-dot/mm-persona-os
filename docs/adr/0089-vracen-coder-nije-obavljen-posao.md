# ADR-0089 — Vraćen coder nije obavljen posao

- **Status:** prihvaćen (14.10.2026.)
- **Povod:** Šav je tri puta prošao do kraja sa izlaznim kodom 0 i vratio
  praznu zakrpu. Ime je stiglo u ADR-0086 (`PRAZNA_ZAKRPA`), detalj u
  ADR-0088 — i detalj je pokazao da Aider nije rekao ništa o modelu.
- **Prethodi:** ADR-0088 (detalj u dnevnik), ADR-0086 (šav za Aidera),
  ADR-0082 (aider u kavezu), ADR-0033 (pretpostavka je majka svih zajeba)
- **Menja:** `deploy/aider/pokretac.py` — `_pozovi_aider` dobija tekst brifa i
  poziva `coder.run`; `--message-file` izlazi iz argv.
  `tests/test_aider_pokretac.py` — jedan nov test.
- **Canon:** §7.3

## Izmereno

Ceo ispis pokretača, iz dnevnika (ADR-0088):

```
izlazni kod 0: Analytics have been permanently disabled.
Warning: it's best to only add files that need changes to the chat.
Warning: Input is not a terminal (fd=0).
```

Nijedan red o modelu. Uzrok je u `/opt/aider/lib/python3.12/site-packages/aider/main.py`:

```
1018:    if return_coder:
1019:        analytics.event("exit", reason="Returning coder object")
1020:        return coder
```

Taj `return` je na **1018**, a petlja razgovora — ono što čita `--message-file`
i jedino što zove model — je sve **ispod** njega. `main(argv, return_coder=True)`
je Aiderov režim za skriptovanje: sastavi codera i vrati ga. Naš pokretač je
taj coder uredno primao, upisivao izveštaj i izlazio sa kodom 0.

Dve zablude koje je ovo usput oborilo, obe moje:

- upozorenje o broju fajlova (`base_coder.py:2262`) je obično `tool_warning`
  posle kojeg se nastavlja — 22 fajla iz brifa **nisu** bila uzrok;
- „tokeni izmereni" nije značilo „model pozvan". `pisac.py:481` proverava
  `if tin is None`, a `total_tokens_sent` na svežem coderu je **nula**, ne
  `None`. Nula je prošla kroz kapiju kao izmerena vrednost.

## Odluka

Pokretač zove Aidera **dva puta, ne jednom**: `main(..., return_coder=True)`
sastavi kavez, a `coder.run(with_message=…)` obavi posao. Brif se predaje kao
tekst, pa `--message-file` izlazi iz argv — mrtva zastavica koja izgleda kao da
nešto radi gora je od nijedne.

## Šta se ovim NE menja

ADR-0086 propisuje red zastavica u argv; taj red ostaje, samo je jedna
zastavica uklonjena, i test to i dalje proverava u celini.

Ostaje otvoreno, zapisano da se ne izgubi: `pisac.py:481` i dalje propušta
**nulu** kao izmerenu vrednost. Posle ove ispravke nula znači „model nije
pozvan", a ne „model je ćutao", i to zaslužuje svoje ime i svoju kapiju. Ne
dira se u istom koraku — jedan ADR, jedna izmena.

Nijedan token nije bio potrošen u sva tri pokušaja. Račun to potvrđuje: trošak
se računa iz izveštaja, a izveštaj je svaki put nosio nulu.

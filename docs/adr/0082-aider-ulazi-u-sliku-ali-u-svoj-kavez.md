# ADR-0082 — Aider ulazi u sliku, ali u svoj kavez

- **Status:** prihvaćen (12.10.2026.)
- **Povod:** Slobodan, 12.10.: „Sme u web kontejner." — odluka tražena u
  ADR-0081, tačka 1.
- **Prethodi:** ADR-0081 (pisac sme da bude tuđi), ADR-0079 (tuđi kod kao
  izvor), ADR-0038 (poslušnik i podela prava), ADR-0033 (pravilo nula)
- **Menja:** `Dockerfile` — jedan sloj. Ništa u aplikaciji.
- **Canon:** §7.3

## Odluka

Aider se **ne instalira u okruženje aplikacije**. Dobija sopstveni virtuelni
prostor u slici i zove se kao spoljni program:

```
RUN python -m venv /opt/aider \
 && /opt/aider/bin/pip install --no-cache-dir aider-chat==0.86.2
```

`pisac` ga poziva kao `/opt/aider/bin/aider`. Verzija je **zakucana**, ne
`>=`: alat koji piše naš kod ne sme da se menja sam od sebe između dva
pečenja slike.

## Zašto kavez, a ne zajedničko okruženje

Izmereno 12.10. na verziji 0.86.2:

| mera | vrednost |
|---|---|
| naše zavisnosti (`pyproject.toml`) | 12 u osnovi, 4 u `dev` |
| aiderove zavisnosti | **107** |
| preklapanje sa našima | `pyyaml`, `jsonschema` (i `asgiref` kroz Django) |

Sto sedam paketa u okruženje aplikacije, zbog dva preklapanja koja bi ionako
morala da se mire — to nije razmena nego uvoz tuđe sudbine. U sopstvenom
`venv`-u aider sme da ima koji god `pydantic` ili `httpx` hoće, a Django ostaje
netaknut. Uklanjanje je brisanje jednog direktorijuma.

## Šta ovo ne otvara

Kontejner `web` već ima mrežu i ključeve — to se ovim ne menja. Ne menja se ni
podela iz ADR-0038: kapije i dalje vrti poslušnik, van aplikacije, bez mreže i
bez ključeva. Aider ne dobija `docker.sock`, ne otvara granu i ne bira putanje.

Aider se poziva sa `--analytics-disable` i `--no-check-update` (izmereno da
obe postoje), dakle ne javlja se nikome i ne proverava verziju sam.

## Šta ostaje neizmereno

Tačke 2 i 3 iz ADR-0081 — **trošak po pokušaju** i **zapis** — i dalje nisu
rešene. Dok nisu, aider u slici stoji **nepozvan**: `pisac` ga ne koristi.
Instalacija nije uvođenje u pogon. ADR-0033.

# Poslušnik za zadatke — ADR-0038

Ovaj direktorijum je jedino mesto u projektu koje dodiruje Docker. To nije slučajno.

## Zašto van aplikacije

`docker.sock` je root na hostu. Da ga dobije `web` ili neki worker, svaka greška u
Django kodu postala bi root na mašini — a zaštićene zone iz ADR-0034 dekor, jer se do
njih stiže ispod aplikacije. Zato poslušnik:

- živi kao systemd jedinica, pod korisnikom koji je u grupi `docker`;
- prima **samo `task_id`** preko API-ja;
- ništa što je agent napisao ne prosleđuje kao komandu, ime, putanju ni zastavicu;
- pokreće potprocese bez ljuske i bez nasleđenog okruženja.

Aplikacija Docker ne vidi i ne treba da ga vidi.

## Šta se vrti po zadatku

`docker-compose.zadatak.yml` diže dva kontejnera na mreži sa `internal: true`:

- **`baza`** — Postgres u `tmpfs`, nestaje sa zadatkom;
- **`kapije`** — slika aplikacije, montiran radni primerak, vrti `kapije.sh`.

Na toj mreži nema rute ka internetu, nema produkcijske baze, Redisa, MinIO-a ni
volumena `secrets`. Nijedan port ne izlazi na host.

Kapije koje se vrte su iste četiri koje vrtimo rukom: `pytest`, `ruff`,
`canon_lint`, `makemigrations --check`. Gotovo = sve četiri zelene (ADR-0035 §3).

## Instalacija

```
sudo mkdir -p /etc/mm-persona-os
sudo install -m 600 /dev/null /etc/mm-persona-os/runner.env
```

U taj fajl ide jedan red — `PERSONA_TOKEN=…`. Token se **ne kuca u ćaskanje i ne ide
u `.env.prod`**; čita se iz baze istom komandom kojom se čita za API (vidi
`stanje-rada.md`).

```
sudo cp deploy/runner/mm-runner.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mm-runner
journalctl -u mm-runner -f
```

## Šta ovde NIJE pokriveno testovima

Logika provere zakrpe jeste — `tests/test_zakrpa.py`. Ovaj direktorijum je
okruženje, i proverava se puštanjem, ne `pytest`-om. Zato prvi zadatak koji prođe
kroz njega ide uz čoveka pored ekrana.

# Browser radnik

Vadi video sa **prijavljenog** browsera (Facebook i sl.) i predaje ga sakupljaču.

## Zašto postoji

Skidanje sa servera (data-centar IP, bez prijave) Facebook/YouTube vide kao bota.
Prijavljeni browser sa rezidencijalne IP adrese (tvoj PC) to nije — on u stranici
drži direktan `progressive_url` do MP4 fajla. Radnik radi tačno to, automatski,
pa fajl šalje serveru i pokreće `sakupi`.

Danas živi na PC-u. Kad farma servera proradi, seli se tamo nepromenjen.

## Instalacija (jednom)

    pip install -r requirements.txt
    playwright install chromium

## Prijava (jednom)

    python radnik.py prijava

Otvori se browser — prijaviš se na Facebook (i YouTube ako hoćeš), vratiš se u
terminal i pritisneš Enter. Prijava se pamti u `.profil/`.

## Jedan snimak

    python radnik.py uzmi "https://www.facebook.com/reel/..."            # samo skine u ./preuzeto/
    python radnik.py uzmi "https://www.facebook.com/reel/..." --posalji  # + server + sakupi

## Cela kolekcija / kanal / stranica

Daš jedan link (sačuvana kolekcija, stranica ili kanal). Radnik sam proskroluje,
nabroji sve snimke i svaki provuče:

    python radnik.py kolekcija "<URL>"                       # nabroji i skine (do 10)
    python radnik.py kolekcija "<URL>" --najvise 3           # probaj na 3
    python radnik.py kolekcija "<URL>" --najvise 20 --posalji  # svih 20 + sakupi

`--najvise` ograničava broj snimaka; `--maks` broj veština po snimku. Snimci koji
su već u `./preuzeto/` se preskaču, pa možeš bezbedno da pokreneš ponovo.

## Server (po potrebi menja preko promenljivih okruženja)

    RADNIK_SERVER=mm@49.12.77.226
    RADNIK_REMOTE_REPO=~/apps/mm-persona-os
    RADNIK_REMOTE_SECRETS=~/apps/mm-persona-os/secrets

## Agentov profil (svoj FB nalog)

Svaka komanda prima `--profil <ime>` da agent radi iz SVOG naloga umesto podrazumevanog:

```
python radnik.py prijava   --profil mila          # jednokratna prijava agentovog FB naloga (2FA)
python radnik.py kolekcija "<URL kanala/kolekcije>" --profil mila --najvise 3 --posalji
```

- Sesija se pamti odvojeno u `.profil/<ime>/`, preuzimanja u `preuzeto/<ime>/` (oba u `.gitignore`).
- Bez `--profil` ostaje zatečeni profil (`.profil/`) — ništa se ne menja.
- Nalog i prijavu pravi/obavlja čovek (kredencijali), kao i do sada. Kanale agent prati ručno u FB-u.

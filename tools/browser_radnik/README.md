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

## Upotreba

    python radnik.py uzmi "https://www.facebook.com/reel/..."            # samo skine u ./preuzeto/
    python radnik.py uzmi "https://www.facebook.com/reel/..." --posalji  # + server + sakupi
    python radnik.py uzmi "<URL>" --maks 8 --posalji                     # najviše 8 veština

## Server (po potrebi menja preko promenljivih okruženja)

    RADNIK_SERVER=mm@49.12.77.226
    RADNIK_REMOTE_REPO=~/apps/mm-persona-os
    RADNIK_REMOTE_SECRETS=~/apps/mm-persona-os/secrets

# ADR-0128 — YouTube na serveru: Deno za n-challenge + lokalni fajl kao garancija

- **Status:** prihvaćen (04.11.2026.)
- **Povod:** `sakupi --klip-url <YouTube>` je prošao bot-detekciju (kolačići, ADR uz
  PR #35), ali YouTube vraća samo storyboard sličice: yt-dlp ne reši „n-challenge"
  (JS zagonetka za potpis stream URL-ova) bez JavaScript runtime-a. `player_client=tv`
  daje „page needs to be reloaded".
- **Prethodi:** ADR-0125 (klip/ASR), yt-dlp kolačići (PR #35)

## Odluka — dva sloja (link + garancija)

**1. Deno u sliku (link-put).** yt-dlp n-challenge rešava preko spoljnog JS runtime-a
(EJS). Dodajemo `deno` binar u Docker sliku (download u build-u, kao srpski OCR modeli).
Solver skripte yt-dlp povuče sam u radu (mreža dozvoljena). Time `--klip-url` ima šansu
da radi server-side. NAPOMENA: YouTube je mačka-i-miš; ovo nije garantovano trajno.

**2. `--klip-fajl` (garancija).** Novi ulaz: lokalni video/audio fajl se ne skida —
`klip` ga samo svede (ffmpeg, izdvojen `_konvertuj`) i preda Whisper-u. Korisnik skine
YouTube video sa svog PC-a/browsera (gde uvek radi — rezidencijalni IP, ulogovan) i
spusti fajl na server (scp, kao kolačiće). `sakupi --klip-fajl <putanja>`.
Ovo je 100% pouzdano i nezavisno od YouTube anti-bot igre.

## Tok
- `klip.transkribuj(izvor, je_fajl=False)`: URL → `_skini_audio` (yt-dlp+cookies+deno) → `_konvertuj`.
- `klip.transkribuj(izvor, je_fajl=True)`: lokalni fajl → `_konvertuj` (bez skidanja).
- `ulaz`/`sakupi`: `klip` (URL) i `klip_fajl` (lokalni fajl).

## Posledice
- Link-put možda radi (Deno); ako YouTube pojača odbranu, lokalni fajl je uvek tu.
- Slika duža za Deno binar (~40 MB). ffmpeg korak izdvojen pa ga dele oba puta.

## Rizik
- Deno + yt-dlp EJS zavisi od yt-dlp verzije i dostupnosti solver distribucije u radu;
  ako zakaže, fallback je `--klip-fajl`.

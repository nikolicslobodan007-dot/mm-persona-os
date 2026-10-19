# ADR-0117 — Naslovna strana je brendirana prijava

- **Status:** prihvaćen (19.10.2026.)
- **Povod:** Vlasnik hoće da `webkorporacija.com` bude ulazna vrata: logo,
  „WEB KORPORACIJA", „Energija novih ideja!" i polja za prijavu.
- **Prethodi:** ADR-0116 (javni sajt i /bot), ADR-0010 (konzola)
- **Menja:** `console/templates/console/login.html` (brend),
  `console/static/console/console.css` (brend blok),
  `console/static/console/logo.png` (nov resurs),
  `deploy/Caddyfile` (apex blok)

## Odluka

**1. Prava polja mora da servira aplikacija, ne statična strana.** Prijava ima
CSRF i 2FA — statični HTML ne može bezbedno da primi lozinku (nema CSRF token,
a slanje lozinke van-origin ili u URL-u otpada). Zato apex `/` renderuje naša
aplikacija.

**2. Caddy apex sada:**
- `/bot` i `/robots.txt` — statično sa diska (kao ranije),
- `/static/*` — statika aplikacije (css, logo) iz istog volumena kao konzola,
- `/` — interni `rewrite` na `/console/login`, URL u pregledaču ostaje `/`,
- ostalo (`/console`, prijava, 2FA, odjava) — na aplikaciju (`web:8000`).

Napadna površina se ne širi: `os.webkorporacija.com` je ionako već javni
poddomen iste aplikacije; apex servira isti, već izloženi sistem.

**3. Jedna prijava, brendirana.** `login.html` dobija logo + naziv + slogan
iznad polja; dugme je „Prijava". Istu stranu vidi i `os.../console/login` —
isto je firma, isti login.

**4. Sesija je host-only.** Operater koji se prijavi na `webkorporacija.com`
radi konzolu na `webkorporacija.com/console`; `os.` i dalje radi nezavisno.
`SameSite=Strict` ne smeta — isti host kroz ceo tok.

## Granica koju ne prelazim sam

- **Vlasnik, na serveru u `.env.prod`:** doda `webkorporacija.com` u
  `DJANGO_ALLOWED_HOSTS` i `https://webkorporacija.com` u
  `DJANGO_CSRF_TRUSTED_ORIGINS` (pored postojećih `os.` vrednosti). Bez toga
  aplikacija odbija host (DisallowedHost) ili prijavu (CSRF 403).
- **Deploy:** pun rebuild `web` (šablon i statika se peku u imidž) + `caddy`.
  Pre toga četiri kapije zelene i `caddy validate` → „Valid configuration".

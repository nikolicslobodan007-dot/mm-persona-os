# ADR-0116 — Javni sajt i /bot strana (webkorporacija.com)

- **Status:** prihvaćen (18.10.2026.)
- **Povod:** Bot se predstavlja sa `User-Agent`-om koji vodi na
  `https://webkorporacija.com/bot`. Ta strana nije postojala — domen je bio
  parkiran kod Loopije. UA koji pokazuje na parking je laž prema svakom sajtu
  koji nas pročita.
- **Prethodi:** ADR-0114 (bot postaje WebKorporacijaBot)
- **Menja:** `deploy/Caddyfile` (novi blok `webkorporacija.com`),
  `docker-compose.prod.yml` (caddy montira `deploy/sajt`),
  novo: `deploy/sajt/index.html`, `deploy/sajt/bot/index.html`,
  `deploy/sajt/robots.txt`

## Odluka

**1. Javni sajt servira naš Caddy, ne Loopia.** `webkorporacija.com` dobija
zaseban blok u Caddyfile-u, odvojen od `{$DOMAIN}` (to je konzola,
`os.webkorporacija.com`). Statika sa diska (`deploy/sajt`), bez prolaska kroz
Django. Razlog: naša infrastruktura, versionisano, mi održavamo; zavisi samo od
jednog A zapisa, ne od nepoznatog Loopia hostinga.

**2. `/bot` je prava strana, ista ona koju je vlasnik prihvatio.** Stoji u
`deploy/sajt/bot/index.html`, servira se na `/bot` i `/bot/`. Objašnjava ko je
`WebKorporacijaBot`, šta čita (javne GET stranice, poštuje robots.txt), šta
nikada ne radi (ne prijavljuje se, ne zaobilazi CAPTCHA, ne piše, ne profiliše
ljude) i kako da ga sajt zaustavi (`robots.txt`).

**3. Početna je namerno privremena.** `deploy/sajt/index.html` je tih
placeholder: naziv, jedna rečenica, link na `/bot` i kontakt. Prava početna
čeka vlasnikovu odluku o sadržaju — ne izmišljamo marketing.

**4. `robots.txt` dozvoljava samo `/bot`.** Ostatak (dok je placeholder) nije za
indeksiranje; početna nosi i `noindex`.

## Granica koju ne prelazim sam

Objava ima dva koraka koje mogu samo ja i jedan koji može samo vlasnik:
- **Ja (u repou):** Caddy blok, montiranje, strane — spremno u ovom komitu.
- **Vlasnik:** A zapis za `webkorporacija.com` → IP servera (49.12.77.226) u
  Loopia panelu; zatim `git push` i redeploy na serveru.

Caddy sam pribavi Let's Encrypt čim A zapis pokazuje na server. MX zapisi
(pošta `bot@`, `kontakt@`) se **ne diraju** izmenom A zapisa — pošta ostaje gde
je bila.

## Bezbednost deploya

Caddy ne sme da padne — ako padne, pada i konzola (`os.`). Zato je **prvi korak
redeploya `caddy validate`** nad tačnim imidžom pre `up -d` (vidi uputstvo u
poruci). Konfiguracija nije validirana na mašini bez dockera; validacija se radi
na serveru pre pokretanja.

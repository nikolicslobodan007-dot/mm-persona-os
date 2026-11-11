# ADR-0135 — Direktor procenjuje sa istorijom niti (ne vrti u krug)

- **Status:** prihvaćen (11.11.2026.)
- **Povod:** Živa proba (Telegram): vlasnik je dao link + „napiši članak", pa
  kroz nekoliko poruka pojašnjavao, a Ivana je stalno pitala iznova („koji
  video?", „koji link?") i nikad nije krenula — **vrtela u krug**.
- **Uzrok:** `razmisli()` (ADR-0106) je gradio prompt SAMO od poslednje poruke
  (`Poruka vlasnika:\n{telo}`), bez istorije niti. Pa „reši ovaj video" nije
  moglo da razreši link iz ranije poruke — model, ispravno za ono što vidi,
  pita „koji video?". Sistemski prompt kaže „ne pitaj za sitnice", ali bez
  konteksta nema šta drugo.
- **Prethodi:** ADR-0105 (razgovor), ADR-0106 (procena pre delegiranja)
- **Menja:** `apps/orchestration/razgovor.py` (`_istorija_niti`, `razmisli`
  prima `istorija`, `posalji` je prosleđuje, dopuna `ODLUKA_SYSTEM`), testovi.

## Odluka
`posalji` sagradi **istoriju niti** (poslednjih ~10 poruka, bez tekuće) i
prosledi je `razmisli`-ju; prompt sad nosi „Dosadašnji razgovor" pre najnovije
poruke. `ODLUKA_SYSTEM` dobija pravilo: ako je vlasnik već dao link/temu ili
odgovorio na ranije pitanje — koristi to, NE pitaj ponovo, razreši reference
poput „ovaj video"/„taj link" iz razgovora i napravi nalog uz razumnu pretpostavku.

Istorija pomaže i konzolu i Telegram (ista nit). Procena i dalje nikad ne obara
nalog (bez modela → prazno → tabela reči, kao pre).

## Posledica
- Direktor razrešava reference i ne ponavlja pitanja — krene u posao.
- Granica ostaje: „stvarno pogledati video" (klip/ASR/vizija) nije još povezano
  u delegacioni lanac — to je zaseban, veći korak.

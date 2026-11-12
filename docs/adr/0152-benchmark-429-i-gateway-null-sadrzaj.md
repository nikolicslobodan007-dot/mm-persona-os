# ADR-0152 — Benchmark otporan na rate-limit + gateway null-sadržaj

- **Status:** prihvaćen (12.11.2026.)
- **Povod:** Prva živa proba `qwen/qwen3.7-flash` kroz OpenRouter otkrila dve
  stvari koje kvare merenje:
  1. **HTTP 429 (rate-limit).** Besplatni/deljeni nivo OpenRouter-a throttluje
     brze uzastopne pozive („temporarily rate-limited upstream... is_byok:false").
     3 od 5 slučajeva nisu ni stigli do modela — to nije kvalitet, nego throttle.
  2. **Pad gatewaya na praznom odgovoru.** Kad OpenAI-kompatibilni provajder
     vrati `content: null`, gateway je radio `None.strip()` →
     `AttributeError`. Pogodilo bi i produkciju, ne samo benchmark.
- **Prethodi:** ADR-0150 (benchmark), ADR-0151 (OpenRouter rute).
- **Menja:** `apps/llm_gateway/gateway.py`, `apps/llm_gateway/benchmark.py`,
  `apps/llm_gateway/management/commands/benchmark.py`.

## Odluka
1. **Gateway: prazan odgovor → prazan string, ne pad.** OpenAI grana sada radi
   `.get("content") or ""`, a `Generation(...)` radi `(text or "").strip()`.
   Prazan odgovor ispravno postaje neuspeh slučaja (provera ga obori), a ne
   `AttributeError` koji ruši poziv.
2. **Benchmark: ponovi na 429 + pauza.** `pokreni(..., pokusaji=3, pauza=0.0)`:
   na grešci koja sadrži `429` ponovi do `pokusaji` puta sa rastućom pauzom
   (4s, 8s); `pauza` je razmak između SVIH poziva (za pacovanje free nivoa).
   Komanda dobija `--pauza` i `--pokusaji`.

## Posledice
- Benchmark meri kvalitet, ne trenutni throttle: transijentni 429 se proguta
  ponavljanjem; trajni rate-limit i dalje ostaje vidljiv kao greška.
- Gateway više ne pada na praznom odgovoru bilo kog OpenAI-kompatibilnog modela.

## Napomena
- Ako retry ne očisti 429 (trajni limit besplatnog nivoa), rešenje je van koda:
  dodati kredit na OpenRouter ili BYOK ključ provajdera za veće limite.

# ADR-0125 — Groq Whisper kao prvi TRANSCRIBE provajder; Veritas klip (URL → transkript)

- **Status:** prihvaćen (03.11.2026.)
- **Povod:** Veritas treba da „pogleda" video klip, a ne samo da čita tekst koji
  mu se dâ. Slice 3: URL klipa → audio → transkript → nalazi (tri sloja).
- **Prethodi:** ADR-0078 (svrha TRANSCRIBE, zaštićena zona), ADR-0018 (skladište),
  ADR-0009 (pogon bez mreže), ADR-0026 (base_url nije tajna), ADR-0013 (ključ u .env)
- **Ispunjava:** ADR-0078 §5 (prvi audio provajder se dodaje kad bude izmeren)
- **Canon:** §13 (merenje troška), §2.2 (MediaAsset)

## Povod

`gateway.transcribe(asset)` je od ADR-0078 sklopljen (ruta, zapis, trošak), ali je
`_call_external_audio` bio prazan stub (`UNSUPPORTED_PROVIDER`). ADR-0078 §5 kaže
da se prvi pravi provajder dodaje „kad prva ruta za TRANSCRIBE bude izmerena i
upisana". Veritasu treba taj ulaz da bi iz snimka (npr. 30-minutno gostovanje
ministra) izvukao šta je rečeno.

## Odluka

**1. Prvi TRANSCRIBE provajder je Groq Whisper (`whisper-large-v3-turbo`).**
OpenAI-kompatibilan `audio/transcriptions` endpoint, multipart (`file` + `model`
[+ `language`]). Bazni URL (`https://api.groq.com/openai/v1`) stoji u
`route.base_url` (nije tajna, ADR-0026). Ključ je `GROQ_API_KEY` u `.env`, vezan
preko `LLM_CREDENTIALS["groq"]`. Izbor: besplatan/jeftin tier, brzo, uklapa se u
FreeLLMAPI liniju; `data_training_allowed=True` jer Groq ne trenira na API podacima.

**2. Trošak se meri po trajanju, ne po tokenu.** Audio nema tokene; vraćamo
trajanje u sekundama kao `tin` (0 `tout`), pa ruta cenu računa kao „po 1000
sekundi" (`input_price_micro_eur_per_1k`). Na besplatnom tieru je 0.

**3. Ostaje pravilo ADR-0078: za TRANSCRIBE nema lokalnog šablona.** Šablon ne
može da čuje; izmišljen prepis je gori od nikakvog. Ako nema uključene spoljne
rute → jasno odbijanje, nikakav lokalni put.

**4. Skidanje: `yt-dlp` + `ffmpeg`.** yt-dlp skine najbolji audio sa URL-a,
ffmpeg ga svede na 16 kHz mono mp3 (Whisper ionako radi na 16 kHz; fajl manji,
staje u Groq-ovu granicu ~25 MB → ~30 min klipa). Duži klip → jasna greška
`AUDIO_PREVELIK`, ne tiho sečenje. `yt-dlp` je NAMERNO van `constraints.txt`
(izuzetak od ADR-0083): ekstraktori platformi trule iz nedelje u nedelju, pa
mora da pliva na najnoviju verziju.

**5. Audio u isto skladište (ADR-0018).** `storage.py` dobija audio MIME tipove;
`MediaAsset` (kind=AUDIO) pod ključem `veritas/klip/<sha>.mp3`. Ista provera, isti
S3.

## Tok (slice 3)

`veritas_klip --url <URL>` → `klip.transkribuj`:
skini (yt-dlp) → svedi (ffmpeg 16k mono) → `storage.put` + `MediaAsset` →
`gateway.transcribe` (Groq) → transkript → `nalaz.izvuci_nalaze` (doslovno /
implicirano / tehnika). `--suvo`: bez mreže i troška (probni transkript).

Verdikt protiv izvora ostaje zaseban korak (`veritas_proveri`); spajanje
klip→verdikt je sledeći slajs.

## Rizik

Skidanje sa YouTube/X sa serverskog (datacentar) IP-ja ume da naleti na
bot-detekciju platforme. Ako se desi: alternativa je lokalni fajl ili kolačići;
rešavamo ako i kad zagusti. Egress servera mora da dozvoli i Groq API i platforme.

## Posledice

- Veritas može sam da obradi snimak, ne samo dati tekst. Zatvara put od „evo
  linka" do nalaza.
- Drugi delovi sistema (Libri, buduće persone) dobijaju ASR besplatno — ruta je
  sad živa za sve kroz Gateway.

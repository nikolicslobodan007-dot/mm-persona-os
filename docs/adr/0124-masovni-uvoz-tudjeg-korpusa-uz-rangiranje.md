# ADR-0124 — Masovni uvoz tuđeg korpusa dozvoljen kad postoji rangiranje

- **Status:** prihvaćen (02.11.2026.)
- **Povod:** 922 destilovane veštine iz `agency-agents` (12 jezgro divizija)
  spremne za uvoz u bazu znanja.
- **Prethodi:** ADR-0098, ADR-0120, ADR-0074, ADR-0077, ADR-0101
- **Menja:** ADR-0098 (ukida tačku „ne uvozimo sve" i ublažava §6 o pouzdanosti).
- **Canon:** §10.4

## Povod i preokret

ADR-0098 (16.10.) je svesno odlučio da se NE uvozi ceo tuđi korpus: „uvoz svega
bi napunio bazu onim što nikad neće stići do agenta". Taj razlog je bio tačan
**u svom trenutku** — rangiranje veština nije postojalo (ADR-0096 tačka 5), pa bi
agent iz gomile dobio nerelevantno.

ADR-0120 je doneo **semantičko rangiranje** (`KnowledgeEmbedding`, `embed_vestine`):
agent sada povlači veštine po sličnosti sa zadatkom. Time „punjenje baze" više ne
šteti — pretraga filtrira relevantno, a nerelevantno prosto nikad ne ispliva.
Razlog za uzdržanost iz ADR-0098 je otpao.

## Odluka

**1. Masovni uvoz destilovanog tuđeg korpusa je dozvoljen** kada postoji
semantičko rangiranje (ADR-0120). Uvezeno je 922 veštine iz 12 jezgro divizija
agency-agents.

**2. Biramo jezgro, ne sve živo.** Uvezene su divizije relevantne za Web
Korporaciju (engineering, specialized, marketing, design, testing, sales,
project-management, paid-media, support, product, finance, security). Niša
(gis, spatial-computing, game-development, academic, healthcare, strategy,
research) je izostavljena kao van domena — selekcija po relevantnosti ostaje,
samo se pomerila sa „par po poslu" na „divizije koje nas se tiču".

**3. Pouzdanost: zadržava se LLM-ocena po veštini (0.6–0.9).** ADR-0098 §6 je
tražio ravnih 0.7 za uvezene jer nisu proverene na našem poslu. Zadržavamo
per-veština ocenu kao **polaznu procenu**, a čovek je diže/spušta kad se veština
pokaže u radu — to je i duh §6 (poverenje raste sa dokazanom upotrebom), samo sa
informativnijim početnim brojem umesto ravne vrednosti.

**4. Sektor prazan = za sve.** Relevantnost rešava pretraga, ne sektorske
pregrade (ADR-0101). Veština je dostupna svima; ko je dobije, odlučuje sličnost.

**5. Trag po diviziji.** Svaka divizija je svoj `KnowledgeSource`
(`agency-agents — <div> (destilovano)`), sa `commit_sha` i `file_path`
(ADR-0077 §3); svaka veština u napomeni imenuje tačan izvorni fajl (ADR-0098 §5).

## Šta se ovim NE menja

ADR-0074 ostaje: uvoz pokreće čovek (`--actor user:`), agent ništa spolja ne
unosi sam. Ulazi destilovano, ne prepisano (ADR-0074 tačka 3). MIT trag i naziv
licence idu uz izvor (ADR-0098 tačke 3–4). Plafon veština po zadatku (ADR-0096)
i dalje bira koliko ih stiže do agenta u jednom poslu — ovaj ADR menja samo
koliko ih sme da STOJI u bazi, ne koliko se isporučuje po zadatku.

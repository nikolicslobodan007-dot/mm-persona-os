# ADR-0081 — Pisac sme da bude tuđi; poverenje i zapis ostaju naši

- **Status:** prihvaćen (12.10.2026.)
- **Povod:** Slobodan, 12.10.: „Zašto mi nismo uzeli neko gotovo rešenje, nego
  izmišljamo toplu vodu?" — posle dana u kom je ceo posao otišao na pakovanje
  konteksta i primenu zakrpe.
- **Prethodi:** ADR-0079 (tuđi kod ulazi kao izvor), ADR-0080 (izvod koji pojede
  fajl), ADR-0044 (pisac), ADR-0038 (poslušnik), ADR-0033 (pravilo nula)
- **Menja:** ništa u kodu danas. Imenuje šav i tri stvari koje se moraju izmeriti
  pre nego što se jedan red napiše.
- **Canon:** §7.3, §10.4

## Šta se desilo

12.10. je ceo dan otišao na `_izvod`, prag reference, zaglavlja hunkova i kočnicu
protiv mlevenja. Sve četiri stvari su **rešeni problemi** u alatima koji već
postoje. Pravilo iz ADR-0079 („prvo potraži gotovo rešenje") nikada nije pušteno
unazad, preko onoga što je napravljeno pre nego što je pravilo zapisano. Mašina
za pisanje koda je od kraja septembra; pravilo je od 07.10.

## Izmereno pre pisanja (12.10.)

Kutija licence prvo, po ADR-0079 — i ona **nije prepreka**:

| alat | licenca | kutija | izvor |
|---|---|---|---|
| Aider | Apache-2.0 | SLOBODNA | ecosyste.ms metapodaci repozitorijuma |
| OpenHands | MIT | SLOBODNA | GitHub stranica projekta |
| mini-swe-agent | MIT | SLOBODNA | PyPI/CERN indeks paketa |

Aider je zatim **pokrenut i izmeren** (verzija 0.86.2, u sopstvenom okruženju, bez
ključa i bez poziva modela). Njegove zastavice se poklapaju sa našim pojmovima
skoro jedan prema jedan:

| naše | njegovo |
|---|---|
| `--zasto` (brif) | `--message-file` |
| `--putanje` (sme da menja) | `--file` |
| `--referenca` (sme da čita) | `--read` |
| `_izvod` + `MAX_REFERENCA_CELA` | `--map-tokens`, uz `--show-repo-map` koji ga ispiše |
| zakrpa koju vadimo iz odgovora | `--no-auto-commits` → izmene ostaju u radnom stablu, `git diff` **jeste** zakrpa |
| `credential_ref`, naš provajder | `--anthropic-api-key` / promenljiva okruženja |
| ništa ne sme napolje | `--analytics-disable`, `--no-check-update` |

## Odluka

Šav ide **unutar `pisac.pokusaj()`**, i nigde drugde.

Iznad šava ostaje sve naše: zadatak, persona, poverenje po putanji, Canon,
protected zone, nalaz, kočnice, trošak po agentu, audit. Ispod šava ostaje sve
naše: `zakrpa --proveri` koja i dalje odbija putanju koju agent ne sme, četiri
kapije u izolovanom kontejneru, grana koja se otvara tek kad su zelene.

Menja se samo ono između: umesto da sami spakujemo brif, pozovemo model i iz
odgovora **vadimo** unified diff, pustimo tuđi alat da u privremenom primerku
izmeni fajlove, pa uzmemo `git diff`.

Dobijamo tačno ono što nas je 12.10. koštalo dana:

1. **Pakovanje konteksta** — njihov repo map umesto našeg `_izvod`. ADR-0080
   postaje mrtav teret, i to je dobra vest, ne loša.
2. **Primena zakrpe** — alat menja fajlove direktno, pa zaglavlja hunkova ne
   postoje. Cela porodica kvarova iz ADR-0052 i ADR-0067 nestaje.

## Zašto Aider, a ne OpenHands ili mini-swe-agent

Jedan izmeren razlog, ne ukus: **Aider menja fajlove, a ne izvršava komande.**
OpenHands i mini-swe-agent su agenti sa ljuskom — njihova snaga je da pokreću
šta im treba. Kod nas komande pokreće poslušnik, van aplikacije, bez mreže i bez
ključeva (ADR-0038 §2), i to se ne otvara zbog udobnosti. Alat koji traži samo
pravo da piše po fajlovima staje u postojeću podelu; alat koji traži ljusku ne
staje.

## Tri stvari koje se moraju izmeriti pre prvog reda koda

1. **Gde se vrti.** Kapije su namerno bez mreže i bez ključeva; pisac je u `web`
   kontejneru koji oboje ima. Aider bi išao tamo gde i pisac — ali to tek treba
   izmeriti na jednom pravom zadatku, u privremenom primerku, a ne tvrditi.
2. **Trošak po pokušaju.** Danas `PromptRecord` i `LLMUsage` nose cenu i otisak
   prompta. Ako alat zove model sam, to mora da se uhvati — inače gubimo meru
   učinka agenta (ADR-0062), a mera je razlog zbog kog persona uopšte postoji.
3. **Zapis.** Ne sme da se desi da zakrpa postoji a da se ne zna kojim modelom,
   po kom brifu i uz koju cenu je nastala.

Dok to troje nije izmereno, ništa se ne menja. ADR-0033.

## Šta ovo ne menja

Ne menja se ništa u tome ko sme šta. Tuđi alat ne dobija pravo da bira putanje,
ne dobija ključ koji persona nema, i ne otvara granu. On piše predlog; sve ostalo
je i dalje naše.

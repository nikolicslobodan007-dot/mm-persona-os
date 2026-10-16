# ADR-0098 — Tuđi izvor pod MIT licencom ulazi destilovan, sa tragom

- **Status:** prihvaćen (16.10.2026.)
- **Povod:** Prvi uvoz tuđeg materijala u bazu znanja. `agency-agents`, 298
  opisa radnih mesta za AI, MIT licenca.
- **Prethodi:** ADR-0074, ADR-0059, ADR-0077, ADR-0095
- **Menja:** `korpus/vestine/agency-agents-01.json` — prvih 14 veština.
- **Canon:** §10.4

## Izmereno

Repozitorijum `msitarzewski/agency-agents`, klon 16.10.:

| Mera | Vrednost |
|---|---|
| commit | `652b2692f8d8ec2b1f1a38e559073e287dfdc469` |
| poslednja izmena | 2026-10-15 |
| licenca | MIT, „Copyright (c) 2025 AgentLand Contributors“ |
| `.md` fajlova | 329 |
| odeljenja sa agentima | 22 |
| najveća | engineering 65, specialized 59, marketing 37, game-development 21 |
| naša područja | marketing 37, strategy 16, security 12, design 10, sales 9, testing 9, project-management 7, paid-media 7, support 6, product 6, finance 5 |

Oblik jednog agenta: Markdown sa zaglavljem (`name`, `description`, `color`,
`emoji`, `vibe`) i telom — identitet, misija, pravila, isporuke, tok rada,
mere uspeha. Prosečno oko 15 kB po fajlu.

## Odluka

**1. Uzimamo, i to otvoreno.** MIT dozvoljava upotrebu, izmenu i komercijalnu
ugradnju. Ne pišemo sami ono što je neko već napisao dobro.

**2. Ulazi destilovano, ne prepisano.** ADR-0074 tačka 3 traži naš opis
postupka. To pravilo je **strože od licence** i ostaje strože: MIT bi nam
dozvolio i doslovan prepis uz zadržano obaveštenje o autorstvu, ali prepisana
tuđa uputstva nisu naše znanje nego tuđe uputstvo u našoj bazi.

Praktična posledica: veština se piše tek pošto je izvorni fajl **pročitan u
celini**. Destilovanje iz naslova je pogađanje, a pogađanje je zabranjeno
(ADR-0033).

**3. Ako ikada uzmemo doslovno, obaveštenje o autorstvu i licenci ide uz
tekst.** To je uslov MIT licence i nije stvar ukusa. Destilat u našim rečima
nije kopija, pa taj uslov ne pokreće — trag ipak upisujemo, jer je trag naše
pravilo a ne tuđe.

**4. Kutija je SLOBODNA, naziv licence je „MIT“.** Ne „slobodno sa interneta“,
ne prazno. ADR-0059 traži imenovanu licencu, a ovde je imenovana i proverena u
`LICENSE` fajlu klona, ne po sećanju.

**5. Kad izvor ima više fajlova, `file_path` imenuje skup, a svaka veština u
svojoj napomeni imenuje tačan fajl iz kog je destilovana.** Tako se svaka
pojedinačna tvrdnja može vratiti na svoj izvor, iako je red izvora jedan.

**6. Pouzdanost uvezenih veština je 0.7, naših 1.0.** Naše veštine su izvučene
iz onoga što smo sami izmerili i pogrešili; ove su tuđa praksa koju nismo
proverili na svom poslu. Kad se neka pokaže u radu, čovek joj diže pouzdanost
— ne pre toga.

## Šta se ovim NE menja

Ne uvozimo svih 298. Plafon veština po poslu (ADR-0096) prima nekoliko po
zadatku; uvoz svega bi napunio bazu onim što nikad neće stići do agenta.

Prvih 14 veština destilovano je iz **četiri** fajla pročitana u celini:
`support/support-support-responder.md`, `sales/sales-outbound-strategist.md`,
`sales/sales-discovery-coach.md`, `marketing/marketing-content-creator.md`.
Biraju se po tome da li postoji radno mesto koje bi ih koristilo — URE-SR,
MKT-DRU, PRO-REF, POD-SR.

Rangiranje veština i dalje ne postoji (ADR-0096 tačka 5). Sa 14 + 14 = 28
veština ono postaje sledeća odluka, ne ova.

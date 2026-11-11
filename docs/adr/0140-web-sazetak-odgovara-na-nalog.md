# ADR-0140 — web.sazetak odgovara na direktorov nalog (ugao), ne fiksni sažetak

- **Status:** prihvaćen (11.11.2026.)
- **Povod:** Živa proba (Telegram): na pitanje „Koliko bi ovo moglo da koristi
  u NAŠEM sistemu i kako?" handler `web.sazetak` (ADR-0139) je opet vratio
  neutralan opis Insomnije — ne analizu primene u Web Korporaciji. Direktor je
  nalog lepo preformulisao, ali handler je imao fiksni prompt („napiši sažetak")
  i ugao pitanja se gubio.
- **Prethodi:** ADR-0139 (web.sazetak), ADR-0136 (rutiranje po vrsti).
- **Menja:** `apps/memory/sakupljanje/steps.py` (prompt handlera), testovi.

## Odluka
Handler sada u prompt provlači **nalog** iz koraka (`input.tema` — direktorova
preformulacija onoga što je vlasnik tražio) kao zadatak: „Pročitaj tekst sa
URL i uradi zadatak: ‚<nalog>'". Tako isti alat ume i čist sažetak i procenu
tipa „kako bismo ovo mi koristili" — zavisno od pitanja. Bez naloga pada na
podrazumevani sažetak (šta je, čemu služi, ko stoji iza).

Granica činjenica/zaključaka: **činjenice o izvoru isključivo iz teksta** (bez
izmišljanja; ako nečega nema — reci), ali **zaključke i procene koje zadatak
traži sme da izvede** iz tih činjenica. Time analiza primene ostaje moguća, a
činjenice uzemljene.

## Granice (poznato, za kasnije)
- Nalog „Na osnovu PRETHODNOG sažetka…" i dalje izazove svež fetch+čitanje;
  korišćenje ranijeg sažetka iz niti kao ulaza je zaseban korak.

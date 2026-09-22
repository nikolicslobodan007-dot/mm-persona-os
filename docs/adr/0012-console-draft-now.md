# ADR-0012 — Nacrt na zahtev iz konzole

- **Status:** prihvaćeno
- **Datum:** 22.09.2026.
- **Canon verzija:** 1.1
- **Izvori:** Canon §7.1, §13, §15.2 · ADR-0009, ADR-0010, ADR-0011
- **Kod:** `apps/content/service.py` (`draft_now`, `manual_topic`), `console/views.py`
  (`persona_draft`), `console/templates/console/persona.html`, `tests/test_console.py::TestDraftNow`

## Kontekst

Od 21.09. Mila piše nacrte pravim modelom, ali samo u prozoru „post” svoje rutine
(radnim danom 12:30–13:30). Za procenu tona i sadržaja operateru treba više
nacrta odmah, a ne jedan dnevno. ADR-0010 je ručno pravljenje nacrta iz konzole
namerno odložio.

## Odluka

Na strani persone postoji forma **„Napiši nacrt sada”**, sa temom koja nije obavezna.

- Put je isti kao kod rutine: memorija → model (Sonnet 5, rezerva lokalni šablon) →
  tvrde zabrane i ponavljanje → predlog → odobrenje A2. U SIMULATION se piše samo
  na sandbox. Konzola i ovde nema svoja pravila (ADR-0010 §2).
- Nacrt dobija `AgentRun` sa `OPERATOR_TASK`, pa se u istoriji razlikuje od
  buđenja rutine (Canon §7.1).
- Bez upisane teme uzima se sledeća niša persone redom (AI → B2B → Prodaja), da
  uzastopni nacrti ne budu isti.
- Formu mogu da koriste `operator`, `persona_manager` i `system_admin`, i to samo
  za persone u statusu READY ili ACTIVE. `viewer` je ne vidi i ne može da je pošalje.
- **Najviše 10 ručnih nacrta u 24 h po personi**, što drži trošak modela pod
  kontrolom. Nacrti iz rutine ne ulaze u ovaj broj.
- Poziv modela ide sinhrono u zahtevu i traje oko 7–10 s, što je unutar gunicorn
  timeout-a od 60 s. Ako model ne odgovori, prelazi se na šablon, pa nacrt nastaje u svakom slučaju.

## Posledice

- Model može da se proba kad god treba, bez menjanja rutine.
- 385 testova (dodato 5).

## Dopuna 22.09. — oblik teksta iz modela

Prvi nacrt napisan modelom počeo je naslovom `**Mila Vuković (AI)**`, u markdown-u, i imao je jednu gramatičku grešku („po prideva”).

- **System prompt:** vrati samo tekst objave, bez naslova, imena, potpisa, markdown-a i hashtag-ova, jer potpis i AI oznaku dodaje sistem; tri do pet rečenica (problem, primer, zaključak); memoriju koristi kao znanje, ne prepisuj je doslovno; srpski, latinica, pravilna gramatika i padeži.
- **`clean_generated`:** ako model ipak doda prvi red sa imenom persone ili markdown oznake (`**`, `#`, `- `), sistem ih uklanja pre provera. Na tekst iz šablona se ne primenjuje.

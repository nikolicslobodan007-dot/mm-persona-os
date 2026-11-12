# ADR-0149 — Popravke PDF dostave: podnaslovi i PDF samo na uspeh

- **Status:** prihvaćen (12.11.2026.)
- **Povod:** Živa proba posle ADR-0147/0148 otkrila dve stvari:
  1. **Podnaslovi se i dalje nisu stilizovali** — heuristika (`_blokovi`) je
     tražila telo u ISTOM `\n\n` bloku, a članak ima podnaslove kao **zasebne
     blokove** (samostalna kratka linija). Naslov (`_cist_naslov`) je radio.
  2. **PDF odbijenog nacrta je ipak poslat** — posao je stao („Nije urađeno",
     recenzent odbio posle petlje ispravke, ADR-0144), a `_mozda_dokument` je
     svejedno napravio i poslao PDF tog nacrta. To obmanjuje.
- **Prethodi:** ADR-0147 (PDF dostava), ADR-0148 (naslov/podnaslovi),
  ADR-0144 (petlja ispravke).
- **Menja:** `apps/content/dokument.py` (`_blokovi`), `apps/channels/tasks.py`
  (`_mozda_dokument`).

## Odluka
1. **`_blokovi`** — podnaslov je sada **samostalna kratka linija** (ceo blok je
   jedna linija ≤70 znakova, bez završne interpunkcije, nije disclosure), ili
   `##` markdown. Tako standalone podnaslovi (kako ih model i piše) dobijaju
   heading-stil. Višelinijski/dugi blokovi ostaju pasusi (nema lažnih naslova).
2. **`_mozda_dokument`** — PDF se šalje **samo kad je `stanje == "uradjeno"`**.
   Odbijen/zastao nacrt se ne isporučuje kao uredan fajl.

## Posledice
- PDF ima vidljive podnaslove; fajl stiže samo za posao koji je prošao recenziju.

## Napomena (zasebno, za kasnije)
- Recenzent je u probi bio **vrlo strog**: odbio parafrazu dosijea („kada stigne
  do direktora") tražeći doslovan citat („kada vlasnikov problem dođe do Ivane").
  Semantički tačno, ali ne doslovno. Da li recenzent sme da prihvati vernu
  parafrazu je zasebno pitanje (PREGLED_SYSTEM), ne dira se ovde.

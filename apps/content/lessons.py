"""Pouke urednika — persona uči iz odbijanja i izmena (ADR-0014).

Svaka odluka urednika sa razlogom ili izmenom postaje kratko pravilo koje ide
u svaki sledeći prompt za pisanje. Tri nivoa (ADR-0014, prošireno ADR-0017):

  - pouka jednog agenta (`persona` popunjena);
  - pravilo sektora (`department` popunjen) — važi za sve u tom sektoru;
  - kućni stil firme (oba prazna) — važi za sve, i za one koji tek nastaju.

Pouka nije memorija: ne bledi i ne zavisi od retrieval-a. Zato se u prompt
stavlja doslovno, ograničena brojem, a urednik je gasi kad prestane da važi.
"""

from __future__ import annotations

import difflib
import re

from django.db.models import Q

from api import audit
from apps.content.models import EditorialLesson
from apps.personas.models import Persona

#: Koliko pouka ide u prompt — po nivou. Najnovije prve.
PROMPT_LIMIT_PERSONA = 10
PROMPT_LIMIT_GLOBAL = 10
PROMPT_LIMIT_DEPARTMENT = 10

#: Ukupan budžet znakova za ceo odeljak pouka u promptu. Trideset pouka po 500
#: znakova ide doslovno u svaki poziv modela — to plaćamo po pozivu i to seče
#: prostor za sam zadatak. Granica po broju pouka to ne hvata, jer pouka nema
#: ograničenu dužinu.
PROMPT_BUDGET_CHARS = 4000

#: Rečenica koja stoji umesto odsečenih pouka. Pisac mora da zna da nije video
#: sve — inače radi po pretpostavci da je spisak potpun (ADR-0033).
ODSECENO = "- [odsečeno: još {broj} pouka nije stalo u prompt]"

#: Po čemu se pravopisna pouka prepoznaje u tekstu (ADR-0054). Ključ stoji u
#: samom tekstu, pa isti marker služi i za idempotentan upis i za to da se ova
#: pouka nikad ne iseče iz prompta.
OZNAKA_PRAVOPIS = "[pravopis:"

_EXCERPT = 120


def _tokens(text: str) -> list[str]:
    return re.findall(r"\S+|\n", text)


def _clip(words: list[str]) -> str:
    s = " ".join(w for w in words if w != "\n").strip()
    return s if len(s) <= _EXCERPT else s[: _EXCERPT - 1] + "…"


def describe_edit(before: str, after: str, *, max_ops: int = 3) -> str:
    """Rečima opisuje šta je urednik promenio — bez modela, deterministički."""
    a, b = _tokens(before), _tokens(after)
    ops: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        old, new = _clip(a[i1:i2]), _clip(b[j1:j2])
        if tag == "equal" or (not old and not new):
            continue
        if tag == "replace" and old and new:
            ops.append(f"«{old}» → «{new}»")
        elif old:
            ops.append(f"ukloni «{old}»")
        else:
            ops.append(f"dodaj «{new}»")
        if len(ops) >= max_ops:
            break
    return "; ".join(ops)


def learn(*, persona: Persona, kind: str, actor: str, reason: str = "", before: str = "",
          after: str = "", everyone: bool = False, department=None,
          source_action=None) -> EditorialLesson | None:
    """Pravi pouku iz odluke. Vraća None kad nema šta da se nauči.

    Domet je tačno jedan: `everyone` (cela firma) > `department` (sektor) >
    agent. Šira odluka poništava užu, da pouka ne bi važila dvaput.
    """
    reason = (reason or "").strip()
    if kind == "edited":
        change = describe_edit(before, after)
        if not change and not reason:
            return None
        text = reason or f"Urednik je ispravio tekst: {change}. Ne ponavljaj isto."
        ex_before, ex_after = before[:300], after[:300]
    elif kind == "rejected":
        if not reason:
            return None
        text, ex_before, ex_after = f"Urednik je odbio nacrt: {reason}", before[:300], ""
    else:
        if not reason:
            return None
        text, ex_before, ex_after = reason, "", ""
    dep = None if everyone else department
    target = None if (everyone or dep is not None) else persona
    dup = EditorialLesson.objects.filter(persona=target, department=dep, text=text[:500],
                                         is_active=True).first()
    if dup:
        return dup
    lesson = EditorialLesson.objects.create(
        persona=target, department=dep, kind=kind, text=text[:500],
        example_before=ex_before, example_after=ex_after, source_action=source_action,
        created_by=actor[:120])
    scope = "all" if everyone else (dep.code if dep is not None else persona.public_id)
    audit.record("content.lesson.learned", persona=persona,
                 details={"lesson_id": str(lesson.id), "kind": kind, "scope": scope})
    return lesson


def upisi_kucni_stil(*, actor: str = "user:slobodan") -> dict[str, int]:
    """Upisuje pravopisna pravila kao kućni stil — važe za sve agente. ADR-0054.

    Nije `learn()`: te pouke nastaju iz odluke urednika nad konkretnim nacrtom,
    a ove dolaze iz knjige i ne vezuju se ni za jednu personu ni akciju.

    **Idempotentno je po ključu, ne po tekstu.** Ključ (`[pravopis:futur-sazeti]`)
    stoji u samom tekstu pouke, pa ponovni upis nađe staru i prepravi je umesto
    da napravi drugu. Da se prepoznaje po tekstu, svaka ispravka formulacije
    ostavila bi zastarelu pouku aktivnom pored nove — i obe bi išle u prompt.

    Vraća `{"upisano": n, "izmenjeno": n, "netaknuto": n}`.
    """
    from apps.content.pravopis import IZVOR, PRAVILA

    br = {"upisano": 0, "izmenjeno": 0, "netaknuto": 0}
    for p in PRAVILA:
        oznaka = f"{OZNAKA_PRAVOPIS}{p.kljuc}]"
        tekst = f"{oznaka} {p.za_prompt}"[:500]
        red = EditorialLesson.objects.filter(
            persona__isnull=True, department__isnull=True,
            text__startswith=oznaka).first()
        if red is None:
            EditorialLesson.objects.create(
                persona=None, department=None, kind="manual", text=tekst,
                example_before=p.pre[:300], example_after=p.posle[:300],
                created_by=IZVOR[:120])
            br["upisano"] += 1
            continue
        if (red.text, red.example_before, red.example_after, red.is_active) == (
                tekst, p.pre[:300], p.posle[:300], True):
            br["netaknuto"] += 1
            continue
        red.text, red.example_before = tekst, p.pre[:300]
        red.example_after, red.is_active = p.posle[:300], True
        red.save(update_fields=["text", "example_before", "example_after",
                                "is_active", "updated_at"])
        br["izmenjeno"] += 1

    audit.record("content.house_style.loaded",
                 details={"izvor": IZVOR, "actor": actor, **br})
    return br


def active_for(persona: Persona) -> tuple[list[EditorialLesson], list[EditorialLesson],
                                          list[EditorialLesson], int]:
    """(kućni stil, pravila sektora, pouke agenta, odsečeno_granicom) — aktivne,
    najnovije prve.

    Pravopisna pravila (ADR-0054) ulaze **van granice broja**. Ona su upisana
    jednom i zauvek, pa su najstarija u kućnom stilu; granica „deset najnovijih"
    bi ih izbacila prva, i to tiho, čim se upiše jedanaesto pravilo firme.

    Četvrti element je broj pouka koje je ISTA ova granica (deset po nivou)
    odsekla — pouke koje `prompt_section` inače nikad ne vidi jer dobija samo
    ono što je prošlo kroz `[:PROMPT_LIMIT...]`. Bez ovoga se odsecanje na
    ovom nivou ne broji nigde i pisac radi po pretpostavci da je spisak potpun
    (ADR-0033).
    """
    from apps.personas.org import department_of

    qs = EditorialLesson.objects.filter(is_active=True).order_by("-created_at")
    dep = department_of(persona)
    dep_odseceno = 0
    if dep is not None:
        dep_qs = qs.filter(department=dep)
        dep_rules = list(dep_qs[:PROMPT_LIMIT_DEPARTMENT])
        dep_odseceno = max(0, dep_qs.count() - len(dep_rules))
    else:
        dep_rules = []
    firma = qs.filter(persona__isnull=True, department__isnull=True)
    pravopisna = list(firma.filter(text__startswith=OZNAKA_PRAVOPIS))
    ostalo_qs = firma.exclude(text__startswith=OZNAKA_PRAVOPIS)
    ostalo = list(ostalo_qs[:PROMPT_LIMIT_GLOBAL])
    ostalo_odseceno = max(0, ostalo_qs.count() - len(ostalo))
    own_qs = qs.filter(persona=persona)
    own = list(own_qs[:PROMPT_LIMIT_PERSONA])
    own_odseceno = max(0, own_qs.count() - len(own))
    return (pravopisna + ostalo,
            dep_rules,
            own,
            dep_odseceno + ostalo_odseceno + own_odseceno)


def prompt_section(persona: Persona, *, budzet: int = PROMPT_BUDGET_CHARS) -> str:
    """Odeljak pouka za prompt, sa gornjom granicom u znakovima.

    Redosled punjenja: **pravopis, pa pouke agenta, pa sektor, pa ostali kućni
    stil.** Pravopis je prvi jer nije mišljenje urednika nego način na koji
    jezik radi: agent koji ga ne vidi greši u svakoj rečenici, dobija odbijanje
    zbog toga, i to odbijanje postaje njegova lična pouka — koja onda istiskuje
    pravopis još dalje. Petlja se zatvara na najgoru stranu (ADR-0054).

    Posle pravopisa idu pouke samog agenta: nastale su iz odbijanja baš njegovog
    rada i njemu su najpreče. Kućni stil i pravila sektora ispadaju prvi.

    Ako nešto ispadne, to se **kaže** u samom promptu. Ćutke skraćen spisak je
    gori od kratkog: pisac po njemu radi kao da je potpun.
    """
    firm, dep, own, odseceno_granicom = active_for(persona)
    if not firm and not dep and not own and not odseceno_granicom:
        return ""

    naslov = "## pouke urednika (obavezno poštuj; novije imaju prednost)"
    pravopis = [x for x in firm if x.text.startswith(OZNAKA_PRAVOPIS)]
    ostali = [x for x in firm if not x.text.startswith(OZNAKA_PRAVOPIS)]
    # Najpreče prvo — tim redom se i puni budžet.
    redom = ([f"- [svi] {x.text}" for x in pravopis]
             + [f"- {x.text}" for x in own]
             + [f"- [{x.department.code}] {x.text}" for x in dep]
             + [f"- [svi] {x.text}" for x in ostali])

    # Red o odsecanju mora da stane U budžet, ne pored njega. Rezervišemo mu
    # mesto unapred (po najvećem mogućem broju) da punjenje ne bi probilo
    # budžet dodavanjem ovog reda tek na kraju.
    najveci_moguci_broj = len(redom) + odseceno_granicom
    rezerva = len(ODSECENO.format(broj=najveci_moguci_broj)) + 1 if najveci_moguci_broj else 0

    stalo: list[str] = []
    zauzeto = len(naslov)
    for red in redom:
        if zauzeto + 1 + len(red) + rezerva > budzet:
            break
        stalo.append(red)
        zauzeto += 1 + len(red)

    odseceno = (len(redom) - len(stalo)) + odseceno_granicom
    if odseceno:
        stalo.append(ODSECENO.format(broj=odseceno))
    return "\n".join([naslov, *stalo])


def visible(persona: Persona):
    from apps.personas.org import department_of

    dep = department_of(persona)
    scope = Q(persona=persona) | Q(persona__isnull=True, department__isnull=True)
    if dep is not None:
        scope |= Q(department=dep)
    return (EditorialLesson.objects.filter(scope)
            .select_related("department").order_by("-is_active", "-created_at"))

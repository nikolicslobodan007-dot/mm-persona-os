"""Organizacija: ko kome odgovara, ko je za šta zadužen. ADR-0017.

Tri pravila koja se ovde sprovode:

  1. **Radno mesto nije dozvola.** Šef sektora ne dobija nijedno poverenje
     time što je šef; poverenje ide po capability-ju (Canon §3.11).
  2. **Čovek ostaje na kraju lanca.** Eskalacija ide agentu-šefu samo do
     granice; odobrenje koje Canon traži od čoveka nijedan agent ne daje.
  3. **Niko ne odobrava sam sebi.** Ako je eskalacija dovela do iste persone,
     lanac se prekida i ide se na čoveka.

Dosije je modelovan, ne državni identitet (Canon §17): nema matičnog broja,
broja dokumenta ni tačne adrese, a agent ima najmanje `MIN_AGE` godina.
"""

from __future__ import annotations

from datetime import date, datetime

from django.db import transaction
from django.utils import timezone

from api import audit
from apps.personas.models import (
    Assignment,
    Department,
    Persona,
    PersonaDossier,
    Position,
)
from common import enums as E

#: Agent je uvek punoletna, radno sposobna osoba u modelu.
MIN_AGE = 22
MAX_CHAIN = 6


class OrgError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- raspored


def position_of(persona: Persona) -> Position | None:
    a = (Assignment.objects.filter(persona=persona, ended_at__isnull=True,
                                   is_primary=True)
         .select_related("position", "position__department").first())
    return a.position if a else None


def department_of(persona: Persona) -> Department | None:
    pos = position_of(persona)
    return pos.department if pos else None


def holders(position: Position) -> list[Persona]:
    return [a.persona for a in Assignment.objects.filter(
        position=position, ended_at__isnull=True).select_related("persona")]


@transaction.atomic
def assign(persona: Persona, position: Position, *, actor: str,
           now: datetime | None = None, note: str = "") -> Assignment:
    """Postavlja personu na radno mesto. Prethodni raspored se zatvara, ne briše."""
    now = now or timezone.now()
    open_count = Assignment.objects.filter(position=position,
                                           ended_at__isnull=True).exclude(
        persona=persona).count()
    if open_count >= position.headcount_max:
        raise OrgError("VALIDATION_ERROR",
                       f"{position.code} je popunjeno ({position.headcount_max}).")
    (Assignment.objects.filter(persona=persona, ended_at__isnull=True)
     .update(ended_at=now))
    a = Assignment.objects.create(persona=persona, position=position, started_at=now,
                                  is_primary=True, note=note[:240])
    audit.record("org.assignment.created", persona=persona,
                 details={"position": position.code, "department": position.department.code,
                          "actor": actor})
    return a


# ---------------------------------------------------------------- lanac odgovornosti


def manager_of(persona: Persona) -> Persona | None:
    """Prvi pretpostavljeni agent, ili None ako iznad njega stoji čovek."""
    pos = position_of(persona)
    while pos is not None and pos.reports_to_id:
        pos = (Position.objects.filter(pk=pos.reports_to_id)
               .select_related("department").first())
        if pos is None:
            return None
        for p in holders(pos):
            if p.pk != persona.pk:
                return p
    return None


def chain_of_command(persona: Persona) -> list[Persona]:
    """Lanac naviše, bez ponavljanja i bez samog sebe. Najviše `MAX_CHAIN`."""
    out: list[Persona] = []
    seen = {persona.pk}
    current = persona
    while len(out) < MAX_CHAIN:
        boss = manager_of(current)
        if boss is None or boss.pk in seen:
            break
        out.append(boss)
        seen.add(boss.pk)
        current = boss
    return out


def escalation_target(persona: Persona) -> str:
    """Kome ide predlog koji personi ne prolazi sam.

    Vraća `public_id` agenta-šefa ili `human_owner` sektora. Ovo je putokaz za
    konzolu, ne dozvola: odobrenje po Canon-u i dalje daje čovek.
    """
    boss = manager_of(persona)
    if boss is not None:
        return boss.public_id
    dep = department_of(persona)
    return (dep.human_owner if dep and dep.human_owner else "user:slobodan")


def subordinates(persona: Persona) -> list[Persona]:
    """Ko odgovara ovoj personi — sva radna mesta čiji je `reports_to` njeno."""
    pos = position_of(persona)
    if pos is None:
        return []
    out: list[Persona] = []
    for below in Position.objects.filter(reports_to=pos):
        out += [p for p in holders(below) if p.pk != persona.pk]
    return out


def can_delegate(boss: Persona, worker: Persona) -> str:
    """Prazan string = sme. Inače kratak razlog zašto ne sme (ADR-0022).

    Posao se zadaje **samo nadole po organizaciji**: šef svom neposrednom
    izvršiocu. Radno mesto i dalje ne daje nijednu dozvolu — izvršilac radi sa
    svojim poverenjem i svojim sposobnostima (ADR-0017).
    """
    if boss.pk == worker.pk:
        return "Niko ne zadaje posao sam sebi."
    if worker.status not in (E.PersonaStatus.READY.value, E.PersonaStatus.ACTIVE.value):
        return f"Izvršilac je {worker.status}."
    if position_of(boss) is None:
        return "Nalogodavac nije raspoređen ni na jedno radno mesto."
    if worker.pk not in {p.pk for p in subordinates(boss)}:
        return f"{worker.public_id} ne odgovara personi {boss.public_id}."
    return ""


# ---------------------------------------------------------------- dosije


def _age_on(born: date, now: date) -> int:
    return now.year - born.year - ((now.month, now.day) < (born.month, born.day))


@transaction.atomic
def set_dossier(persona: Persona, *, actor: str, birth_date: date | None = None,
                now: datetime | None = None, **fields) -> PersonaDossier:
    """Upisuje ili menja dosije. Svaka izmena podiže verziju i ide u audit."""
    now = now or timezone.now()
    allowed = {f.name for f in PersonaDossier._meta.get_fields()
               if f.name not in ("persona", "dossier_version", "updated_at")}
    unknown = set(fields) - allowed
    if unknown:
        raise OrgError("VALIDATION_ERROR", f"Nepoznata polja: {sorted(unknown)}")
    if birth_date is not None:
        if _age_on(birth_date, now.date()) < MIN_AGE:
            raise OrgError("VALIDATION_ERROR",
                           f"Agent je modelovan kao odrasla osoba (najmanje {MIN_AGE}).")
        Persona.objects.filter(pk=persona.pk).update(birth_date_model=birth_date)
    d, created = PersonaDossier.objects.get_or_create(persona=persona, defaults=fields)
    if not created:
        for k, v in fields.items():
            setattr(d, k, v)
        d.dossier_version += 1
        d.save()
    audit.record("persona.dossier.changed", persona=persona,
                 severity=E.AuditSeverity.INFO,
                 details={"actor": actor, "version": d.dossier_version,
                          "fields": sorted(fields)})
    return d


def dossier_of(persona: Persona) -> PersonaDossier | None:
    return PersonaDossier.objects.filter(persona=persona).first()


def prompt_section(persona: Persona, *, now: datetime | None = None) -> str:
    """Radno mesto i lična pozadina, za sistemski prompt.

    Kratko i bez nabrajanja mera: model treba da zna gde radi i ko je, a ne da
    to izgovara. Visina i težina ne idu u tekst — one služe slici.
    """
    now = now or timezone.now()
    lines: list[str] = []
    pos = position_of(persona)
    if pos is not None:
        dep = pos.department
        lines.append(f"Radiš u sektoru „{dep.name}”, na mestu „{pos.title}”"
                     + (f" ({pos.specialty})." if pos.specialty else "."))
        if pos.duties:
            lines.append("Tvoj posao: " + "; ".join(str(d) for d in pos.duties[:4]) + ".")
        boss = manager_of(persona)
        if boss is not None:
            lines.append(f"Odgovaraš: {boss.display_name}.")
    d = dossier_of(persona)
    if d is not None:
        bits = []
        if persona.birth_date_model:
            bits.append(f"{_age_on(persona.birth_date_model, now.date())} godina")
        if d.birth_place:
            bits.append(f"rođena/rođen u mestu {d.birth_place}")
        if d.residence:
            bits.append(f"živi u mestu {d.residence}")
        if d.hobbies:
            bits.append("van posla: " + ", ".join(str(h) for h in d.hobbies[:3]))
        if bits:
            lines.append("O tebi: " + "; ".join(bits) + ".")
    if not lines:
        return ""
    lines.append("Ovo je pozadina, ne tema — ne nabrajaj je i ne predstavljaj se "
                 "podacima osim ako te neko izričito pita.")
    return "## ko si i gde radiš\n" + "\n".join(lines)

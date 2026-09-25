"""Učinak programerskog agenta. ADR-0034 §6, ADR-0042.

ADR-0034 je obećao merenje po agentu i ostavio ga nenapravljenim. Posledica je
da svako „dok ne bude izmereno" u ostalim ADR-ovima znači „nikad": ljudska kapija
pred `main` (ADR-0038 §6), pravo šefa-agenta da deli poverenje (ADR-0037), izbor
modela za pisanje koda — sve to čeka brojeve kojih nema.

Dva pravila ovog modula:

  - **Meri se ono što postoji, i kaže se šta se ne meri.** Trošak po zadatku i
    kasnije vraćene greške nemaju izvor u bazi; umesto izmišljene nule stoji
    `None` i spisak `ne_meri_se`. Broj koji niko ne može da potkrepi gori je od
    nedostajućeg (ADR-0033).
  - **Odbijena zakrpa je podatak, ne smeće.** Agent koji stalno pokušava izvan
    svog dela koda vidi se samo ovde.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from apps.personas.models import Persona
from common import enums as E

from .models import CodeTask, GateResult, TaskPatch

__all__ = ["Ucinak", "za_agenta", "za_sve", "NE_MERI_SE"]

#: Ono što ADR-0034 §6 traži, a za šta izvor još ne postoji. Stoji ovde da se ne
#: bi zaboravilo da je izostavljeno namerno.
NE_MERI_SE: tuple[str, ...] = (
    "trošak po zadatku — LLM poziv po zadatku još ne postoji (ADR-0041, druga polovina)",
    "greške kasnije vraćene na njegov commit — nema praćenja vraćanja",
)


@dataclass
class Ucinak:
    """Brojevi za jednog agenta. `None` znači „nema izvora", ne nulu."""

    persona: str
    ime: str = ""
    zadataka: int = 0
    zavrsenih: int = 0
    zakrpa: int = 0
    prihvacenih: int = 0
    odbijenih: int = 0
    odbijenih_zbog_zone: int = 0
    kapija_mereno: int = 0
    kapija_iz_prvog: int = 0
    nalaza_na_rad: int = 0
    blokera_na_rad: int = 0
    trosak_centi: int | None = None
    ne_meri_se: tuple[str, ...] = field(default=NE_MERI_SE)

    @property
    def iz_prvog_puta(self) -> float | None:
        """Udeo kapija koje su prošle iz prvog pokušaja, ili `None` bez merenja."""
        if not self.kapija_mereno:
            return None
        return round(self.kapija_iz_prvog / self.kapija_mereno, 3)

    @property
    def zakrpa_prihvaceno(self) -> float | None:
        if not self.zakrpa:
            return None
        return round(self.prihvacenih / self.zakrpa, 3)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["iz_prvog_puta"] = self.iz_prvog_puta
        d["zakrpa_prihvaceno"] = self.zakrpa_prihvaceno
        d["ne_meri_se"] = list(self.ne_meri_se)
        return d


def _kapije_iz_prvog(zadaci) -> tuple[int, int]:
    """Koliko je (kapija, prošlih iz prvog puta) nad ovim zadacima.

    Mera je po (zadatak, zakrpa, kapija): gleda se **prvi** upisani ishod, jer
    posle popravke svako prođe iz drugog ili trećeg puta — a upravo razlika
    između prvog i trećeg je ono što se meri.
    """
    prvi: dict[tuple, bool] = {}
    for red in (GateResult.objects.filter(task__in=zadaci)
                .order_by("created_at")
                .values_list("task_id", "patch_id", "gate", "passed")):
        kljuc = red[:3]
        if kljuc not in prvi:
            prvi[kljuc] = red[3]
    return len(prvi), sum(1 for ok in prvi.values() if ok)


def za_agenta(persona: Persona) -> Ucinak:
    zadaci = list(CodeTask.objects.filter(assignee=persona))
    u = Ucinak(persona=persona.public_id, ime=persona.display_name)
    u.zadataka = len(zadaci)
    u.zavrsenih = sum(1 for z in zadaci if z.status == E.TaskStatus.DONE.value)

    zakrpe = TaskPatch.objects.filter(author=persona)
    u.zakrpa = zakrpe.count()
    u.prihvacenih = zakrpe.filter(status=E.PatchStatus.ACCEPTED.value).count()
    u.odbijenih = zakrpe.filter(status=E.PatchStatus.REJECTED.value).count()
    u.odbijenih_zbog_zone = zakrpe.filter(
        status=E.PatchStatus.REJECTED.value, reason__icontains="zaštićena zona").count()

    if zadaci:
        u.kapija_mereno, u.kapija_iz_prvog = _kapije_iz_prvog(zadaci)
        from .models import ReviewFinding
        nalazi = ReviewFinding.objects.filter(task__in=zadaci)
        u.nalaza_na_rad = nalazi.count()
        u.blokera_na_rad = nalazi.filter(
            severity=E.FindingSeverity.BLOCKER.value).count()
    return u


def za_sve(sektor: str = "") -> list[Ucinak]:
    """Učinak svih agenata koji imaju bar jedan zadatak ili zakrpu."""
    ljudi = Persona.objects.filter(
        pk__in=set(CodeTask.objects.exclude(assignee=None)
                   .values_list("assignee_id", flat=True))
        | set(TaskPatch.objects.exclude(author=None)
              .values_list("author_id", flat=True))
    )
    if sektor:
        ljudi = ljudi.filter(
            assignments__position__department__code=sektor.upper(),
            assignments__ended_at__isnull=True,
        ).distinct()
    return [za_agenta(p) for p in ljudi.order_by("public_id")]

"""Tri tačke za poslušnika. ADR-0039.

    GET  /api/v1/tasks/queued            → samo spisak `task_id`
    GET  /api/v1/tasks/{task_id}/work    → zakrpa koja je VEĆ prošla proveru
    POST /api/v1/tasks/{task_id}/gate    → ishod jedne kapije

Ovo su jedine tačke koje poslušnik vidi (`allow_runner`), i namerno su uske:

  - `queued` vraća **samo identifikatore**. Da vrati putanju ili komandu,
    poslušnik bi postao mesto gde agentov tekst utiče na to šta se izvršava.
  - `work` izdaje **samo `ACCEPTED`** zakrpu. Odbijena zakrpa je zapis o agentu,
    ne posao — i nikad ne izlazi iz sistema (ADR-0038 §3).
  - `gate` upisuje ishod i ništa više. Poslušnik ne zatvara zadatak, ne menja
    putanje i ne dodeljuje poverenje; „gotovo" ostaje odluka koju donosi
    `zadaci.finish` nad zelenim kapijama (ADR-0035 §3).
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import serializers

from api.base import PersonaOSView, ok
from api.errors import ApiError
from apps.orchestration import brif, zadaci
from apps.orchestration.models import CodeTask, TaskPatch
from common import enums as E
from common import ids as I

#: Koliko zadataka najviše stane u jedan odgovor. Poslušnik ionako uzima prvi —
#: na CX23 se vrti jedan po jedan (ADR-0038 §5).
MAX_U_REDU = 20


def _zadatak(task_id: str) -> CodeTask:
    try:
        I.validate_public_id(I.EntityKind.CODE_TASK, task_id)
    except ValueError:
        raise ApiError(E.ErrorCode.NOT_FOUND, "Zadatak ne postoji.") from None
    zad = CodeTask.objects.filter(public_id=task_id).first()
    if zad is None:
        raise ApiError(E.ErrorCode.NOT_FOUND, "Zadatak ne postoji.")
    return zad


def _poslednja_prihvacena(zad: CodeTask) -> TaskPatch | None:
    """Najnovija prihvaćena a još neizmerena zakrpa."""
    return (zad.patches.filter(status=E.PatchStatus.ACCEPTED.value, gates__isnull=True)
            .order_by("-created_at").first())


class GateIn(serializers.Serializer):
    gate = serializers.ChoiceField(choices=E.Gate.values())
    patch = serializers.UUIDField(required=False, allow_null=True, default=None)
    passed = serializers.BooleanField()
    detail = serializers.CharField(required=False, allow_blank=True, default="",
                                   max_length=8000)
    commit = serializers.CharField(required=False, allow_blank=True, default="",
                                   max_length=40)


class QueuedTasksView(PersonaOSView):
    """Zadaci sa prihvaćenom zakrpom koja **još nije merena**.

    Red drži NEMEREN posao, ne „nezatvoren". Poslušnik namerno ne zatvara
    zadatak (ADR-0039 §3), pa bi red po statusu zadatka vraćao isti posao
    zauvek — to se 25.09. i desilo, osam prolaza za pola sata. Zakrpa koja ima
    makar jedan ishod kapije je izmerena i izlazi iz reda; nova zakrpa ulazi.
    """

    allow_runner = True

    @extend_schema(operation_id="tasks_queued", responses={200: dict})
    def get(self, request):
        nemereno = TaskPatch.objects.filter(
            status=E.PatchStatus.ACCEPTED.value, gates__isnull=True)
        redovi = (
            CodeTask.objects
            .filter(patches__in=nemereno)
            .exclude(status__in=[E.TaskStatus.DONE.value, E.TaskStatus.CANCELLED.value])
            .order_by("created_at")
            .values_list("public_id", flat=True)
            .distinct()[:MAX_U_REDU]
        )
        return ok({"tasks": list(redovi)})


class TaskBriefView(PersonaOSView):
    """Građa za pisca zakrpe: zadatak, dozvoljene putanje i sadržaj tih fajlova.

    `work` daje zakrpu koja **postoji**; `brief` daje ono od čega se zakrpa tek
    pravi. Brif nosi `sha256` po fajlu umesto commita, jer slika aplikacije nema
    `.git` — obećanje koje ne može da se ispuni se ne daje (ADR-0041 §1).
    """

    allow_runner = True

    @extend_schema(operation_id="tasks_brief", responses={200: dict})
    def get(self, request, task_id: str):
        return ok(brif.build(_zadatak(task_id)))


class TaskWorkView(PersonaOSView):
    """Zakrpa za rad — samo ona koja je prošla proveru putanja."""

    allow_runner = True

    @extend_schema(operation_id="tasks_work", responses={200: dict})
    def get(self, request, task_id: str):
        zad = _zadatak(task_id)
        zakrpa = _poslednja_prihvacena(zad)
        if zakrpa is None:
            raise ApiError(E.ErrorCode.NOT_FOUND,
                           "Zadatak nema prihvaćenu zakrpu.")
        return ok({
            "task_id": zad.public_id,
            "patch_id": str(zakrpa.pk),
            "diff": zakrpa.diff,
            "base_sha": zakrpa.base_sha,
            "paths": zakrpa.paths,
            "required_gates": zad.required_gates,
        })


class TaskGateView(PersonaOSView):
    """Ishod jedne kapije. Svaki pokušaj se pamti (ADR-0035 §3)."""

    allow_runner = True

    @extend_schema(operation_id="tasks_gate", request=GateIn, responses={200: dict})
    def post(self, request, task_id: str):
        zad = _zadatak(task_id)
        ulaz = GateIn(data=request.data)
        ulaz.is_valid(raise_exception=True)
        v = ulaz.validated_data
        zakrpa = None
        if v.get("patch"):
            zakrpa = TaskPatch.objects.filter(pk=v["patch"], task=zad).first()
            if zakrpa is None:
                raise ApiError(E.ErrorCode.NOT_FOUND,
                               "Zakrpa ne pripada ovom zadatku.")
        try:
            red = zadaci.record_gate(zad, v["gate"], v["passed"], patch=zakrpa,
                                     detail=v["detail"], commit_sha=v["commit"])
        except zadaci.TaskError as e:
            raise ApiError(E.ErrorCode.VALIDATION_ERROR, str(e)) from e
        return ok({"task_id": zad.public_id, "gate": red.gate, "passed": red.passed,
                   "gates": zadaci.gate_report(zad)})

"""Tačke za poslušnika. ADR-0039, ADR-0043.

    GET  /api/v1/tasks/queued            → samo spisak `task_id`
    GET  /api/v1/tasks/{task_id}/work    → zakrpa koja je VEĆ prošla proveru
    POST /api/v1/tasks/{task_id}/gate    → ishod jedne kapije
    POST /api/v1/tasks/{task_id}/result  → grana i commit, kad su kapije zelene
    POST /api/v1/tasks/{task_id}/unapplied → zakrpa se nije primenila (ADR-0049)

Ovo su jedine tačke koje poslušnik vidi (`allow_runner`), i namerno su uske:

  - `queued` vraća **samo identifikatore**. Da vrati putanju ili komandu,
    poslušnik bi postao mesto gde agentov tekst utiče na to šta se izvršava.
  - `work` izdaje **samo `ACCEPTED`** zakrpu. Odbijena zakrpa je zapis o agentu,
    ne posao — i nikad ne izlazi iz sistema (ADR-0038 §3).
  - `gate` upisuje ishod i ništa više. Poslušnik ne zatvara zadatak, ne menja
    putanje i ne dodeljuje poverenje; „gotovo" ostaje odluka koju donosi
    `zadaci.finish` nad zelenim kapijama (ADR-0035 §3).
  - `result` beleži **granu**, ne `main`. Ni ovde poslušnik ne zatvara ništa:
    grana je ponuda na sto, a spajanje je ljudska ruka (ADR-0043).
"""

from __future__ import annotations

from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers

from api.base import PersonaOSView, ok
from api.errors import ApiError
from apps.orchestration import brif, rezultat, zadaci
from apps.orchestration import zakrpa as zakrpe
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


#: Zaglavlje kojim se poslušnik predstavlja. `X-Actor-ID` kaže ULOGU
#: (`service:runner`), a ne KOJI primerak — a zakup je o primerku (ADR-0058).
RUNNER_HEADER = "HTTP_X_RUNNER_ID"


def _poslusnik(request) -> str:
    return (request.META.get(RUNNER_HEADER) or "").strip()[:80]


def _mora_da_drzi(zad: CodeTask, request) -> str:
    """Ishod sme da upiše samo onaj ko drži zakup — ako je mašina. ADR-0058.

    Do 29.09. je svako ko zna `task_id` mogao da upiše kapiju. Dva poslušnika
    su upisala po četiri, jedan skup tačan a jedan prazan, i merilo je zavisilo
    od toga koji je red stigao poslednji. Ovo nije provera identiteta radi
    identiteta — ovo je jedini način da se zna čiji je ishod.

    **Čovek je izuzet.** Zakup rešava trku između mašina; operater koji upisuje
    ishod rukom ne trči ni sa kim, a njegov potez ionako nosi ime u zapisu
    (ADR-0045). Traženje zakupa od čoveka bi zatvorilo jedini put kojim se
    zaglavljen zadatak razrešava.
    """
    # Ko je pokretač čita se iz zaglavlja koje je `api.base` već proverio uz
    # prijavljenog korisnika — ne iz konteksta, koji u ovom trenutku još ume da
    # nosi podrazumevano `service:system`.
    if (request.META.get("HTTP_X_ACTOR_ID") or "").startswith("user:"):
        return ""
    runner = _poslusnik(request)
    if not runner:
        raise ApiError(E.ErrorCode.VALIDATION_ERROR,
                       "Nedostaje `X-Runner-ID` — bez njega se ne zna ko piše "
                       "ishod (ADR-0058).")
    if not zadaci.drzi_zakup(zad, runner):
        drzi = zad.claimed_by or "niko"
        raise ApiError(E.ErrorCode.VERSION_CONFLICT,
                       f"Zakup drži {drzi}, ne {runner}. Preuzmi zadatak pre "
                       f"nego što upišeš ishod (ADR-0058).")
    return runner


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


class UnappliedIn(serializers.Serializer):
    patch = serializers.UUIDField()
    reason = serializers.CharField(max_length=2000)


class ResultIn(serializers.Serializer):
    patch = serializers.UUIDField()
    branch = serializers.CharField(max_length=80)
    commit = serializers.CharField(max_length=40)


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
        # ADR-0058 — posao pod tuđim živim zakupom nije slobodan. Svoj zakup
        # ostaje u redu: poslušnik koji se podigao posle pada mora da može da
        # nastavi ono što je sam započeo.
        ja = _poslusnik(request)
        zauzeto = Q(claimed_until__gt=timezone.now()) & ~Q(claimed_by="")
        if ja:
            zauzeto &= ~Q(claimed_by=ja)
        redovi = (
            CodeTask.objects
            .filter(patches__in=nemereno)
            .exclude(zauzeto)
            .exclude(status__in=[E.TaskStatus.DONE.value, E.TaskStatus.CANCELLED.value])
            .order_by("created_at")
            .values_list("public_id", flat=True)
            .distinct()[:MAX_U_REDU]
        )
        return ok({"tasks": list(redovi)})


class TaskClaimView(PersonaOSView):
    """Preuzimanje zadatka na rok. ADR-0058.

    Red nudi posao; zakup ga dodeljuje. Bez ovog koraka `/tasks/queued` je isti
    spisak za svakoga ko pita, pa dva poslušnika rade isti posao — što se
    29.09. i desilo, sa osam upisanih kapija umesto četiri.
    """

    allow_runner = True

    @extend_schema(operation_id="tasks_claim", request=None, responses={200: dict})
    def post(self, request, task_id: str):
        zad = _zadatak(task_id)
        runner = _poslusnik(request)
        if not runner:
            raise ApiError(E.ErrorCode.VALIDATION_ERROR,
                           "Nedostaje `X-Runner-ID` (ADR-0058).")
        try:
            zad = zadaci.claim(zad, runner=runner)
        except zadaci.TaskError as e:
            # 409 je ono što poslušnik proverava. Ne širim `ErrorCode` novim
            # članom za ovo: `common/enums.py` je zaštićena zona (ADR-0034
            # §5.1), a Canon §8.5 je rečnik grešaka za sve klijente. Ako se
            # ikad bude trebalo razlikovati sudar zakupa od ostalih 409 — to je
            # svoj ADR, ne uzgredna izmena (ADR-0058).
            kod = (E.ErrorCode.VERSION_CONFLICT if e.code == "ALREADY_CLAIMED"
                   else E.ErrorCode.VALIDATION_ERROR)
            raise ApiError(kod, str(e)) from e
        return ok({"task_id": zad.public_id, "runner": zad.claimed_by,
                   "until": zad.claimed_until.isoformat()})


class TaskReleaseView(PersonaOSView):
    """Vraćanje zadatka u red pre isteka zakupa. ADR-0058."""

    allow_runner = True

    @extend_schema(operation_id="tasks_release", request=None, responses={200: dict})
    def post(self, request, task_id: str):
        zad = _zadatak(task_id)
        runner = _poslusnik(request)
        try:
            zad = zadaci.release(zad, runner=runner)
        except zadaci.TaskError as e:
            raise ApiError(E.ErrorCode.VERSION_CONFLICT, str(e)) from e
        return ok({"task_id": zad.public_id, "runner": runner})


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
        try:
            priprema = rezultat.priprema(zad, zakrpa)
        except zadaci.TaskError as e:
            raise ApiError(E.ErrorCode.VALIDATION_ERROR, str(e)) from e
        return ok({
            "task_id": zad.public_id,
            "patch_id": str(zakrpa.pk),
            "diff": zakrpa.diff,
            "base_sha": zakrpa.base_sha,
            "paths": zakrpa.paths,
            "required_gates": zad.required_gates,
            # ADR-0043 — ime grane i poruka commita stižu gotovi. Poslušnik ih ne
            # sastavlja, pa agentov naslov nikad ne postaje argument komande.
            **priprema,
        })


class TaskResultView(PersonaOSView):
    """Grana i commit kao rezultat jedne zakrpe. ADR-0043.

    Prima se tek kad su sve tražene kapije zelene **nad tom zakrpom**. Zadatak
    se ovde ne zatvara: `main` menja ljudska ruka (ADR-0038 §6).
    """

    allow_runner = True

    @extend_schema(operation_id="tasks_result", request=ResultIn, responses={200: dict})
    def post(self, request, task_id: str):
        zad = _zadatak(task_id)
        _mora_da_drzi(zad, request)
        ulaz = ResultIn(data=request.data)
        ulaz.is_valid(raise_exception=True)
        v = ulaz.validated_data
        zakrpa = TaskPatch.objects.filter(pk=v["patch"], task=zad).first()
        if zakrpa is None:
            raise ApiError(E.ErrorCode.NOT_FOUND, "Zakrpa ne pripada ovom zadatku.")
        try:
            zakrpa = rezultat.zabelezi(zad, zakrpa, branch=v["branch"],
                                       commit_sha=v["commit"])
        except zadaci.TaskError as e:
            raise ApiError(E.ErrorCode.VALIDATION_ERROR, str(e)) from e
        return ok({"task_id": zad.public_id, "patch_id": str(zakrpa.pk),
                   "branch": rezultat.ime_grane(zad), "commit": zakrpa.applied_sha,
                   "status": zakrpa.status})


class TaskGateView(PersonaOSView):
    """Ishod jedne kapije. Svaki pokušaj se pamti (ADR-0035 §3)."""

    allow_runner = True

    @extend_schema(operation_id="tasks_gate", request=GateIn, responses={200: dict})
    def post(self, request, task_id: str):
        zad = _zadatak(task_id)
        _mora_da_drzi(zad, request)
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


class TaskUnappliedView(PersonaOSView):
    """Zakrpa je prošla proveru putanja, ali se kod izvršioca nije primenila.

    Postoji da poslušnik ne bi izmišljao palu kapiju samo da posao izađe iz reda
    (ADR-0049). Test koji nije pokrenut se ne upisuje kao pao.
    """

    allow_runner = True

    @extend_schema(operation_id="tasks_unapplied", request=UnappliedIn,
                   responses={200: dict})
    def post(self, request, task_id: str):
        zad = _zadatak(task_id)
        _mora_da_drzi(zad, request)
        ulaz = UnappliedIn(data=request.data)
        ulaz.is_valid(raise_exception=True)
        v = ulaz.validated_data
        red = TaskPatch.objects.filter(pk=v["patch"], task=zad).first()
        if red is None:
            raise ApiError(E.ErrorCode.NOT_FOUND, "Zakrpa ne pripada ovom zadatku.")
        try:
            red = zakrpe.odbij_posle_provere(zad, red, v["reason"])
        except zadaci.TaskError as e:
            raise ApiError(E.ErrorCode.VALIDATION_ERROR, str(e)) from e
        return ok({"task_id": zad.public_id, "patch_id": str(red.pk),
                   "status": red.status, "reason": red.reason})

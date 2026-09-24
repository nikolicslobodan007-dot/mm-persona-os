"""Kontrolna tabla. ADR-0010.

Server renderuje HTML; JavaScript je samo pomoć (odbrojavanje, potvrda).
Svaki upis ide kroz isti servisni sloj kao API — konzola nema svoja pravila.
"""

from __future__ import annotations

import json
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.core.paginator import Paginator
from django.db.models import Count, Max, Q, Sum
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from api.base import principal_of, roles_of
from apps.behaviour.models import BehaviourState
from apps.content.models import ContentItem
from apps.memory.models import MemoryItem
from apps.observability.models import CostLedger
from apps.orchestration.models import Action, AgentRun
from apps.personas import lifecycle
from apps.personas.models import Department, Persona
from apps.policy import service as policy
from apps.policy.models import ApprovalRequest, KillSwitch, PolicyIncident
from apps.runtime.executor import runtime_overview
from common import enums as E
from console import totp
from console.auth import (
    SESSION_OTP,
    SESSION_PENDING,
    clear_failures,
    console_view,
    is_operator,
    locked,
    record_failure,
    secure,
)
from console.models import OperatorTOTP

LOCAL_TZ = "Europe/Belgrade"


def _safe_next(request, fallback="/console/") -> str:
    nxt = request.POST.get("next") or request.GET.get("next") or fallback
    ok = url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()},
                                         require_https=request.is_secure())
    return nxt if ok and nxt.startswith("/console") else fallback


# ---------------------------------------------------------------- prijava


@require_http_methods(["GET", "POST"])
def login_view(request):
    error = None
    if request.method == "POST":
        username = request.POST.get("username", "")[:150]
        if locked(request, username):
            error = "Previše neuspelih pokušaja. Pokušaj ponovo za 15 minuta."
        else:
            user = authenticate(request, username=username,
                                password=request.POST.get("password", ""))
            if user is None or not is_operator(user):
                record_failure(request, username)
                error = "Pogrešno korisničko ime ili lozinka."
            elif not OperatorTOTP.objects.filter(user=user).exists():
                error = ("Drugi faktor nije uključen za ovaj nalog. Na serveru pokreni: "
                         f"manage.py console_totp --user {user.get_username()}")
            else:
                request.session.cycle_key()
                request.session[SESSION_PENDING] = user.pk
                return redirect(f"/console/login/2fa?next={_safe_next(request)}")
    return secure(render(request, "console/login.html",
                         {"error": error, "next": _safe_next(request)}))


@require_http_methods(["GET", "POST"])
def totp_view(request):
    uid = request.session.get(SESSION_PENDING)
    if not uid:
        return redirect("/console/login")
    user = get_user_model().objects.filter(pk=uid, is_active=True).first()
    if user is None:
        request.session.flush()
        return redirect("/console/login")
    error = None
    if request.method == "POST":
        name = user.get_username()
        if locked(request, name):
            error = "Previše neuspelih pokušaja. Pokušaj ponovo za 15 minuta."
        elif totp.verify(user, request.POST.get("code", "")):
            clear_failures(request, name)
            nxt = _safe_next(request)
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            request.session[SESSION_OTP] = True
            request.session.pop(SESSION_PENDING, None)
            return redirect(nxt)
        else:
            record_failure(request, name)
            error = "Kod nije ispravan ili je već iskorišćen."
    return secure(render(request, "console/totp.html",
                         {"error": error, "next": _safe_next(request)}))


@require_POST
def logout_view(request):
    logout(request)
    return redirect("/console/login")


# ---------------------------------------------------------------- pregled


def _nav(request) -> dict:
    return {"pending_count": ApprovalRequest.objects.filter(
                status=E.ApprovalStatus.PENDING.value).count(),
            "active_ks": KillSwitch.objects.filter(is_active=True).exists(),
            "who": principal_of(request.user), "tz": LOCAL_TZ,
            "roles": sorted(r.value for r in roles_of(request.user))
            or (["superuser"] if request.user.is_superuser else [])}


@console_view
def overview(request):
    now = timezone.now()
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    ctx = _nav(request) | {
        "personas": Persona.objects.order_by("public_id"),
        "runtime": runtime_overview(now),
        "kill_switches": KillSwitch.objects.filter(is_active=True).order_by("-activated_at"),
        "incidents": PolicyIncident.objects.filter(status=E.IncidentStatus.OPEN.value)
        .order_by("-occurred_at")[:5],
        "content_today": dict(ContentItem.objects.filter(created_at__gte=now - timedelta(
            hours=24)).values_list("status").annotate(n=Count("id"))),
        "cost_month": CostLedger.objects.filter(occurred_at__gte=month).aggregate(
            s=Sum("amount_eur_cents"))["s"] or 0,
        "recent_actions": Action.objects.select_related("persona", "channel_account")
        .order_by("-created_at")[:10],
    }
    return render(request, "console/overview.html", ctx)


# ---------------------------------------------------------------- odobrenja


@console_view
def approvals(request):
    pending = (ApprovalRequest.objects.filter(status=E.ApprovalStatus.PENDING.value)
               .select_related("action", "action__persona", "action__channel_account",
                               "decision").order_by("expires_at"))
    recent = (ApprovalRequest.objects.exclude(status=E.ApprovalStatus.PENDING.value)
              .select_related("action", "action__persona").order_by("-updated_at")[:15])
    can_decide = request.user.has_perm("policy.decide_approval")
    return render(request, "console/approvals.html",
                  _nav(request) | {"pending": pending, "recent": recent,
                                   "can_decide": can_decide, "now": timezone.now()})


@console_view
@require_POST
def approval_decide(request, approval_id: str):
    if not request.user.has_perm("policy.decide_approval"):
        messages.error(request, "Nemaš dozvolu za odlučivanje o odobrenjima.")
        return redirect("/console/approvals")
    ap = ApprovalRequest.objects.select_related("action").filter(public_id=approval_id).first()
    if ap is None:
        raise Http404
    decision = request.POST.get("decision", "")
    reason = request.POST.get("reason", "").strip()[:2000]
    override = None
    if decision == E.ApprovalStatus.APPROVED_WITH_CHANGES.value:
        text = request.POST.get("text", "").replace("\r\n", "\n").strip()
        if not text:
            messages.error(request, "Izmenjen tekst je prazan.")
            return redirect("/console/approvals")
        override = {**(ap.action.input_json or {}), "text": text}
    if decision not in (E.ApprovalStatus.APPROVED.value,
                        E.ApprovalStatus.APPROVED_WITH_CHANGES.value,
                        E.ApprovalStatus.REJECTED.value):
        messages.error(request, "Nepoznata odluka.")
        return redirect("/console/approvals")
    if decision == E.ApprovalStatus.REJECTED.value and not reason:
        messages.error(request, "Za odbijanje upiši razlog — persona uči iz njega.")
        return redirect("/console/approvals")
    roles = roles_of(request.user) & E.APPROVAL_DECIDERS
    role = sorted(roles, key=lambda r: r.value)[0] if roles else None
    before = str((ap.action.input_json or {}).get("text", ""))
    try:
        policy.decide_approval(ap, E.ApprovalStatus(decision), actor=principal_of(request.user),
                               role=role, reason=reason, payload_override=override)
    except policy.PolicyError as e:
        messages.error(request, str(e))
        return redirect("/console/approvals")
    a = Action.objects.select_related("persona").get(pk=ap.action_id)
    _sync_content(a)
    if request.POST.get("learn") == "1":
        lesson = _learn(a, decision, reason, before, override, request)
        if lesson is not None:
            scope = "svi agenti" if lesson.persona_id is None else a.persona.display_name
            messages.info(request, f"Pouka zapamćena ({scope}): {lesson.text[:120]}")
    label = {"APPROVED": "Odobreno", "APPROVED_WITH_CHANGES": "Odobreno sa izmenom",
             "REJECTED": "Odbijeno"}[decision]
    messages.success(request, f"{label}: {a.public_id} → {a.status}")
    return redirect("/console/approvals")


def _learn(action, decision, reason, before, override, request):
    from apps.content import lessons

    kind = {"REJECTED": "rejected", "APPROVED_WITH_CHANGES": "edited"}.get(decision)
    if kind is None:
        return None
    from apps.personas.org import department_of

    dep = department_of(action.persona) if request.POST.get("sector") == "1" else None
    return lessons.learn(persona=action.persona, kind=kind, actor=principal_of(request.user),
                         reason=reason, before=before,
                         after=(override or {}).get("text", ""),
                         everyone=request.POST.get("everyone") == "1", department=dep,
                         source_action=action)


def _sync_content(action: Action) -> None:
    from apps.content.service import sync_from_action

    sync_from_action(action)


# ---------------------------------------------------------------- spisak agenata

#: Koliko agenata staje na jednu stranu. Firma ide do 10.000 — spisak se ne
#: učitava ceo ni slučajno.
PO_STRANI = 40


@console_view
def personas(request):
    """Spisak svih agenata sa pretragom (ADR-0025).

    Pretraga gleda ono po čemu čovek zaista traži: ime, broj agenta, adresu
    sandučića, radno mesto i sektor. Filteri su odvojeni, da se „svi u
    marketingu" ne mora kucati.
    """
    q = (request.GET.get("q") or "").strip()
    sektor = (request.GET.get("sektor") or "").strip()
    status = (request.GET.get("status") or "").strip()

    qs = Persona.objects.all().order_by("public_id")
    if q:
        qs = qs.filter(
            Q(display_name__icontains=q) | Q(public_id__icontains=q)
            | Q(slug__icontains=q)
            | Q(channel_accounts__persona_address__icontains=q)
            | Q(channel_accounts__handle__icontains=q)
            # Samo tekući raspored: ko je nekad bio urednik ne izlazi na „urednik".
            | Q(assignments__ended_at__isnull=True,
                assignments__position__title__icontains=q)
            | Q(assignments__ended_at__isnull=True,
                assignments__position__department__name__icontains=q)).distinct()
    if sektor:
        qs = qs.filter(assignments__ended_at__isnull=True,
                       assignments__position__department__code=sektor).distinct()
    if status:
        qs = qs.filter(status=status)

    strana = Paginator(qs, PO_STRANI).get_page(request.GET.get("s"))
    red = list(strana.object_list)
    ctx = _nav(request) | {
        "strana": strana, "agenti": _red_spiska(red), "q": q,
        "sektor": sektor, "status": status,
        "sektori": Department.objects.order_by("sort_order"),
        "statusi": [s.value for s in E.PersonaStatus],
        "ukupno": qs.count(), "svih": Persona.objects.count(),
        "upit": _upit(request),
        "akcije": [(k, v[0]) for k, v in MASOVNE_AKCIJE.items()],
        "sme_masovno": bool(_roles(request.user) & _DRAFTERS),
        "put": request.get_full_path(),
    }
    return render(request, "console/personas.html", ctx)


def _upit(request) -> str:
    """Postojeći filteri kao query string, da se ne izgube pri listanju."""
    delovi = [f"{k}={v}" for k in ("q", "sektor", "status")
              if (v := request.GET.get(k, "").strip())]
    return ("&" + "&".join(delovi)) if delovi else ""


def _red_spiska(personas: list) -> list[dict]:
    """Jedan upit po koloni, ne jedan po agentu — spisak mora da podnese 10.000."""
    from apps.personas.models import Assignment
    from apps.visuals.models import VisualProfile

    ids = [p.pk for p in personas]
    slike = {v.persona_id: v.reference_asset for v in VisualProfile.objects.filter(
        persona_id__in=ids, reference_asset__isnull=False).select_related(
        "reference_asset")}
    mesta = {a.persona_id: a for a in Assignment.objects.filter(
        persona_id__in=ids, ended_at__isnull=True, is_primary=True)
        .select_related("position", "position__department")}
    # Šef: ko drži radno mesto iznad. Opet u jednom upitu, za sva mesta odjednom.
    iznad = {a.position.reports_to_id for a in mesta.values() if a.position.reports_to_id}
    sefovi: dict = {}
    if iznad:
        for a in Assignment.objects.filter(position_id__in=iznad, ended_at__isnull=True
                                           ).select_related("persona"):
            sefovi.setdefault(a.position_id, a.persona)
    ceka = dict(ApprovalRequest.objects.filter(
        action__persona_id__in=ids, status=E.ApprovalStatus.PENDING.value)
        .values_list("action__persona_id").annotate(n=Count("id")))
    posao = dict(AgentRun.objects.filter(persona_id__in=ids)
                 .values_list("persona_id").annotate(kad=Max("started_at")))
    out = []
    for p in personas:
        a = mesta.get(p.pk)
        sef = sefovi.get(a.position.reports_to_id) if a and a.position.reports_to_id else None
        out.append({"p": p, "slika": slike.get(p.pk),
                    "mesto": a.position if a else None,
                    "sektor": a.position.department if a else None,
                    "sef": sef if sef and sef.pk != p.pk else None,
                    "ceka": ceka.get(p.pk, 0), "kad": posao.get(p.pk)})
    return out


#: Koliko agenata sme jedna masovna akcija. Brana od promašenog „označi sve".
MASOVNO_NAJVISE = 200

#: Šta se sme uraditi nad više agenata odjednom. Svaka stavka je običan prelaz
#: statusa — ide kroz `lifecycle.change_status`, sa razlogom i audit zapisom.
MASOVNE_AKCIJE = {
    "ACTIVE": ("Aktiviraj", E.PersonaStatus.ACTIVE),
    "PAUSED": ("Pauziraj", E.PersonaStatus.PAUSED),
}


@require_POST
@console_view
def personas_bulk(request):
    """Isti prelaz nad više agenata. Ko ne sme da pređe — preskače se, sa razlogom.

    Masovna akcija ne daje nijedno novo pravo: svaki agent prolazi kroz istu
    proveru prelaza i istu ulogu kao da si ga otvorio pojedinačno (ADR-0025).
    """
    izbor = request.POST.getlist("agenti")[:MASOVNO_NAJVISE]
    akcija = request.POST.get("akcija", "")
    razlog = (request.POST.get("razlog") or "").strip()
    nazad = _safe_next(request, "/console/personas")
    if akcija not in MASOVNE_AKCIJE:
        messages.error(request, "Nepoznata akcija.")
        return redirect(nazad)
    if not izbor:
        messages.error(request, "Nijedan agent nije označen.")
        return redirect(nazad)
    if not razlog:
        messages.error(request, "Masovna promena statusa traži razlog.")
        return redirect(nazad)

    _ime, cilj = MASOVNE_AKCIJE[akcija]
    uloge, actor = _roles(request.user), principal_of(request.user)
    uspelo, preskoceno = [], []
    for p in Persona.objects.filter(public_id__in=izbor).order_by("public_id"):
        try:
            lifecycle.change_status(p, cilj, actor=actor, roles=uloge, reason=razlog)
            uspelo.append(p.public_id)
        except lifecycle.LifecycleError as e:
            preskoceno.append(f"{p.public_id}: {e}")
    if uspelo:
        messages.success(request, f"{cilj.value}: {', '.join(uspelo)}.")
    for red in preskoceno[:8]:
        messages.warning(request, red)
    if len(preskoceno) > 8:
        messages.warning(request, f"…i još {len(preskoceno) - 8} preskočenih.")
    return redirect(nazad)


# ---------------------------------------------------------------- persona


@console_view
def persona(request, public_id: str):
    p = Persona.objects.filter(public_id=public_id).first()
    if p is None:
        raise Http404
    state = BehaviourState.objects.filter(persona=p).first()
    ctx = _nav(request) | {
        "p": p, "state": state,
        "state_rows": [(f, getattr(state, f), _state_max(state, f)) for f in (
            "energy", "stress", "focus", "curiosity_now", "social_appetite",
            "content_pressure", "attention_remaining")] if state else [],
        "next_wake": state.next_wake_at if state and state.next_wake_at
        and state.next_wake_at.year > 2000 else None,
        "targets": lifecycle.allowed_targets(p, _roles(request.user)),
        "wakeable": p.status in {s.value for s in E.WAKEABLE_BY_SCHEDULER},
        "trust": sorted(policy.trust_map(p).items()),
        "runs": AgentRun.objects.filter(persona=p).order_by("-started_at")[:25],
        "items": ContentItem.objects.filter(persona=p).order_by("-created_at")[:15],
        "actions": Action.objects.filter(persona=p).select_related("channel_account")
        .order_by("-created_at")[:20],
        "memories": dict(MemoryItem.objects.filter(persona=p).values_list("status")
                         .annotate(n=Count("id"))),
        "memory_scopes": _memory_scopes(p),
        "accounts": p.channel_accounts.all().order_by("channel_type"),
        "llm_keys": _llm_keys(p),
        "lessons": _lessons(p),
        "mail": _mail(p),
        "org": _org(p),
        "lik": _lik(p),
        "plans": _plans(p),
        "can_draft": bool(_roles(request.user) & _DRAFTERS)
        and p.status in {E.PersonaStatus.READY.value, E.PersonaStatus.ACTIVE.value},
        "manual_limit": _manual_limit(),
    }
    return render(request, "console/persona.html", ctx)


def _mail(p) -> dict:
    from apps.channels import mailbox
    from apps.channels.models import MailMessage

    acc = mailbox.mailbox_of(p)
    return {"account": acc, "planned": None if acc else mailbox.address_for(p),
            "enabled": mailbox.enabled(),
            "inbox": MailMessage.objects.filter(persona=p, direction="in")
            .order_by("-received_at")[:10] if acc else []}


def _plans(p) -> list[dict]:
    """Planovi agenta sa koracima (ADR-0021)."""
    from apps.orchestration import plans as engine

    out = []
    for pl in engine.active_for(p):
        parent = engine.parent_of(pl)
        out.append({"plan": pl, "steps": list(pl.steps.order_by("sequence")),
                    "from": parent.persona if parent else None})
    return out


def _memory_scopes(p) -> dict:
    """Koliko memorije agent vidi po opsegu (ADR-0020)."""
    from apps.memory import sealing

    return sealing.counts(p)


def _org(p) -> dict:
    """Radno mesto, šef i dosije — za karticu na strani persone (ADR-0017)."""
    from apps.personas import org
    from apps.personas.models import Position

    pos = org.position_of(p)
    return {"position": pos, "department": pos.department if pos else None,
            "boss": org.manager_of(p), "chain": org.chain_of_command(p),
            "escalation": org.escalation_target(p), "dossier": org.dossier_of(p),
            "choices": Position.objects.select_related("department")
            .order_by("department__sort_order", "code")}


def _lik(p) -> dict:
    """Profilna slika, galerija i stanje generatora (ADR-0018)."""
    from apps.visuals import generator

    _ref, source = generator.credential_ref(p)
    return {"enabled": generator.enabled(), "key": source,
            "portrait": generator.reference_of(p), "gallery": generator.gallery_of(p),
            "model": settings.IMAGE_MODEL}


def _lessons(p):
    from apps.content.lessons import visible

    return visible(p)[:30]


def _llm_keys(p) -> list[tuple[str, str, str]]:
    """(ruta, izvor, ime promenljive) za svaku uključenu spoljnu rutu — bez tajne."""
    from apps.llm_gateway import gateway
    from apps.llm_gateway.models import LLMRoute

    out = []
    for r in (LLMRoute.objects.filter(is_enabled=True).exclude(provider=gateway.LOCAL_PROVIDER)
              .order_by("priority")):
        _ref, source = gateway.credential_ref(r.provider, p)
        out.append((f"{r.provider}/{r.model_key}", source,
                    gateway.persona_env_name(r.provider, p) or ""))
    return out


def _manual_limit() -> int:
    from apps.content.service import MANUAL_DRAFTS_PER_DAY

    return MANUAL_DRAFTS_PER_DAY


def _state_max(state, field):
    if field == "attention_remaining":
        from apps.behaviour.service import DEFAULT_ATTENTION_DAILY

        return (state.state_ext or {}).get("attention_daily", str(DEFAULT_ATTENTION_DAILY))
    return 1


def _roles(user) -> set:
    roles = set(roles_of(user))
    if user.is_superuser:
        roles.add(E.Role.SYSTEM_ADMIN)
    return roles


@console_view
@require_POST
def persona_status(request, public_id: str):
    p = Persona.objects.filter(public_id=public_id).first()
    if p is None:
        raise Http404
    try:
        to = E.PersonaStatus(request.POST.get("to", ""))
        p = lifecycle.change_status(p, to, actor=principal_of(request.user),
                                    roles=_roles(request.user),
                                    reason=request.POST.get("reason", ""))
        messages.success(request, f"{p.public_id} je sada {p.status}.")
    except (lifecycle.LifecycleError, ValueError) as e:
        messages.error(request, str(e))
    return redirect(f"/console/personas/{public_id}")


_DRAFTERS = frozenset({E.Role.OPERATOR, E.Role.PERSONA_MANAGER, E.Role.SYSTEM_ADMIN})

@console_view
@require_POST
def persona_lesson_add(request, public_id: str):
    """Ručno pravilo pisanja — za ovu personu ili za sve (ADR-0014)."""
    from apps.content import lessons

    p = Persona.objects.filter(public_id=public_id).first()
    if p is None:
        raise Http404
    if not (_roles(request.user) & _DRAFTERS):
        messages.error(request, "Tvoja uloga ne menja pravila pisanja.")
    elif lessons.learn(persona=p, kind="manual", actor=principal_of(request.user),
                       reason=request.POST.get("text", "")[:500],
                       everyone=request.POST.get("everyone") == "1",
                       department=(org_module().department_of(p)
                                   if request.POST.get("sector") == "1" else None)) is None:
        messages.error(request, "Upiši pravilo.")
    else:
        messages.success(request, "Pravilo dodato.")
    return redirect(f"/console/personas/{public_id}")


def org_module():
    from apps.personas import org

    return org


@console_view
def org_chart(request):
    """Ko je kome šef i ko je na kom radnom mestu (ADR-0017)."""
    from apps.personas.models import Department

    deps = (Department.objects.filter(is_active=True)
            .prefetch_related("positions__assignments__persona", "positions__reports_to")
            .order_by("sort_order"))
    rows = []
    for d in deps:
        items = []
        for pos in sorted(d.positions.all(), key=lambda x: (x.level != "head", x.code)):
            items.append({"pos": pos,
                          "people": [a.persona for a in pos.assignments.all()
                                     if a.ended_at is None]})
        rows.append({"dep": d, "positions": items})
    total = sum(len(i["people"]) for r in rows for i in r["positions"])
    return render(request, "console/org.html",
                  _nav(request) | {"rows": rows, "total": total})


@console_view
@require_POST
def persona_assign(request, public_id: str):
    """Premešta agenta na drugo radno mesto (ADR-0017)."""
    from apps.personas import org
    from apps.personas.models import Position

    p = Persona.objects.filter(public_id=public_id).first()
    if p is None:
        raise Http404
    if not (_roles(request.user) & _DRAFTERS):
        messages.error(request, "Tvoja uloga ne menja raspored.")
        return redirect(f"/console/personas/{public_id}")
    pos = Position.objects.filter(code=request.POST.get("position", "")).first()
    if pos is None:
        messages.error(request, "Nepoznato radno mesto.")
    else:
        try:
            org.assign(p, pos, actor=principal_of(request.user),
                       note=request.POST.get("note", "")[:240])
            messages.success(request, f"{p.display_name}: {pos.title}.")
        except org.OrgError as e:
            messages.error(request, str(e))
    return redirect(f"/console/personas/{public_id}")


#: Polja dosijea koja se menjaju iz konzole. Brojevi se čiste, ostalo je tekst.
_DOSSIER_TEXT = ("birth_place", "residence", "build", "eye_color", "hair_color",
                 "hair_style", "marital_status", "appearance_prompt")
_DOSSIER_INT = ("height_cm", "weight_kg", "children")


@console_view
@require_POST
def persona_dossier(request, public_id: str):
    """Upis dosijea — modelovana biografija, bez državnog identiteta (Canon §17)."""
    from datetime import date

    from apps.personas import org

    p = Persona.objects.filter(public_id=public_id).first()
    if p is None:
        raise Http404
    if not (_roles(request.user) & _DRAFTERS):
        messages.error(request, "Tvoja uloga ne menja dosije.")
        return redirect(f"/console/personas/{public_id}")
    fields = {k: request.POST.get(k, "").strip()[:200] for k in _DOSSIER_TEXT}
    for k in _DOSSIER_INT:
        raw = request.POST.get(k, "").strip()
        if raw.isdigit():
            fields[k] = int(raw)
    hobbies = [h.strip() for h in request.POST.get("hobbies", "").split(",") if h.strip()]
    fields["hobbies"] = hobbies[:8]
    born = None
    raw_born = request.POST.get("birth_date", "").strip()
    if raw_born:
        try:
            born = date.fromisoformat(raw_born)
        except ValueError:
            messages.error(request, "Datum rođenja: format GGGG-MM-DD.")
            return redirect(f"/console/personas/{public_id}")
    try:
        org.set_dossier(p, actor=principal_of(request.user), birth_date=born, **fields)
        messages.success(request, "Dosije upisan.")
    except org.OrgError as e:
        messages.error(request, str(e))
    return redirect(f"/console/personas/{public_id}")


@console_view
@require_POST
def persona_portrait(request, public_id: str):
    """Pravi profilnu sliku ili dodaje sliku u galeriju (ADR-0018)."""
    from apps.visuals import generator

    p = Persona.objects.filter(public_id=public_id).first()
    if p is None:
        raise Http404
    if not (_roles(request.user) & _DRAFTERS):
        messages.error(request, "Tvoja uloga ne pravi slike.")
        return redirect(f"/console/personas/{public_id}")
    scene = request.POST.get("scene", "").strip()
    try:
        r = (generator.make_photo(p, scene, actor=principal_of(request.user)) if scene
             else generator.make_portrait(p, actor=principal_of(request.user)))
        messages.success(request, f"Slika {r.asset.public_id} napravljena "
                                  f"({r.cost_eur_cents} c).")
    except generator.ImageError as e:
        messages.error(request, f"{e.code}: {e.detail}")
    return redirect(f"/console/personas/{public_id}")


#: Koliko slika prima jedno otpremanje.
UPLOAD_BATCH = 20


@console_view
@require_POST
def persona_upload(request, public_id: str):
    """Otprema sliku koju je čovek napravio ručno (ADR-0018, dopuna)."""
    from apps.visuals import generator

    p = Persona.objects.filter(public_id=public_id).first()
    if p is None:
        raise Http404
    if not (_roles(request.user) & _DRAFTERS):
        messages.error(request, "Tvoja uloga ne menja slike.")
        return redirect(f"/console/personas/{public_id}")
    files = request.FILES.getlist("slike") or request.FILES.getlist("slika")
    if not files:
        messages.error(request, "Izaberi bar jedan fajl.")
        return redirect(f"/console/personas/{public_id}")
    if len(files) > UPLOAD_BATCH:
        messages.error(request, f"Najviše {UPLOAD_BATCH} slika odjednom.")
        return redirect(f"/console/personas/{public_id}")
    # „Kao profilna" važi samo za prvu sliku; ostale idu u galeriju.
    portrait_first = request.POST.get("kao_profilna") == "1"
    label = request.POST.get("opis", "")[:80]
    done, failed = [], []
    for i, f in enumerate(files):
        try:
            r = generator.import_image(
                p, f.read(), actor=principal_of(request.user),
                as_portrait=portrait_first and i == 0, label=label)
            done.append(r.asset.public_id)
        except generator.ImageError as e:
            failed.append(f"{f.name}: {e.code}")
    if done:
        messages.success(request, f"Otpremljeno {len(done)}: " + ", ".join(done))
    for why in failed:
        messages.error(request, why)
    return redirect(f"/console/personas/{public_id}")


@console_view
def asset(request, public_id: str):
    """Prikaz slike iz storage-a — samo prijavljenom operateru."""
    from django.http import HttpResponse

    from apps.visuals import storage
    from apps.visuals.models import MediaAsset

    a = MediaAsset.objects.filter(public_id=public_id).first()
    if a is None:
        raise Http404
    try:
        data = storage.get(a.storage_key)
    except storage.StorageError as e:
        raise Http404 from e
    r = HttpResponse(data, content_type=a.mime_type)
    r["Cache-Control"] = "private, max-age=3600"
    return r


@console_view
@require_POST
def persona_mailbox(request, public_id: str):
    """Otvara sandučić persone na Mailcow-u (ADR-0015)."""
    from apps.channels import mailbox

    p = Persona.objects.filter(public_id=public_id).first()
    if p is None:
        raise Http404
    if not (_roles(request.user) & _DRAFTERS):
        messages.error(request, "Tvoja uloga ne otvara sandučiće.")
    else:
        try:
            acc = mailbox.provision(p, actor=principal_of(request.user))
            messages.success(request, f"Sandučić otvoren: {acc.persona_address}")
        except mailbox.MailboxError as e:
            messages.error(request, f"Sandučić nije otvoren — {e.code}: {e.detail}")
    return redirect(f"/console/personas/{public_id}")


@console_view
@require_POST
def lesson_toggle(request, lesson_id: str):
    from api import audit
    from apps.content.models import EditorialLesson

    les = EditorialLesson.objects.filter(pk=lesson_id).select_related("persona").first()
    if les is None:
        raise Http404
    back = request.POST.get("back", "")
    back = back if back.startswith("/console/personas/") else "/console/"
    if not (_roles(request.user) & _DRAFTERS):
        messages.error(request, "Tvoja uloga ne menja pravila pisanja.")
        return redirect(back)
    les.is_active = not les.is_active
    les.save(update_fields=["is_active", "updated_at"])
    audit.record("content.lesson.toggled", persona=les.persona,
                 details={"lesson_id": str(les.id), "active": les.is_active})
    messages.success(request, "Pouka uključena." if les.is_active else "Pouka isključena.")
    return redirect(back)


@console_view
@require_POST
def persona_draft(request, public_id: str):
    """„Napiši nacrt sada” — isti put kao rutina, bez čekanja prozora (ADR-0012)."""
    from apps.content import service as content

    p = Persona.objects.filter(public_id=public_id).first()
    if p is None:
        raise Http404
    if not (_roles(request.user) & _DRAFTERS):
        messages.error(request, "Tvoja uloga ne pravi nacrte.")
        return redirect(f"/console/personas/{public_id}")
    try:
        item, sent = content.draft_now(p, topic=request.POST.get("topic", ""))
    except content.ContentError as e:
        messages.error(request, str(e))
        return redirect(f"/console/personas/{public_id}")
    if sent:
        messages.success(request, f"Nacrt „{item.title}” čeka odobrenje.")
        return redirect("/console/approvals")
    if item.status == E.ContentStatus.DRAFT.value:
        messages.success(request, f"Nacrt „{item.title}” je napravljen (nema dozvoljenog kanala).")
    else:
        messages.error(request, f"Nacrt „{item.title}” je odbijen: {item.status_reason}.")
    return redirect(f"/console/personas/{public_id}")


# ---------------------------------------------------------------- sadržaj i akcije


@console_view
def content(request):
    status = request.GET.get("status", "")
    qs = ContentItem.objects.select_related("persona").order_by("-created_at")
    if status in E.ContentStatus.values():
        qs = qs.filter(status=status)
    return render(request, "console/content.html",
                  _nav(request) | {"items": qs[:100], "status": status,
                                   "statuses": E.ContentStatus.values()})


@console_view
def action(request, action_id: str):
    a = (Action.objects.select_related("persona", "channel_account", "run", "policy_decision")
         .filter(public_id=action_id).first())
    if a is None:
        raise Http404
    attempts = [{"a": t, "requests": json.dumps((t.payload or {}).get("requests", []),
                                                 ensure_ascii=False, indent=2)}
                for t in a.attempts.order_by("attempt_number")]
    return render(request, "console/action.html", _nav(request) | {
        "a": a, "decisions": a.decisions.order_by("evaluated_at"),
        "approvals": a.approvals.order_by("created_at"), "attempts": attempts,
        "payload": json.dumps(a.input_json or {}, ensure_ascii=False, indent=2),
        "result": json.dumps(a.result_json or {}, ensure_ascii=False, indent=2)})


# ---------------------------------------------------------------- trošak i incidenti


@console_view
def costs(request):
    since = timezone.now() - timedelta(days=30)
    qs = CostLedger.objects.filter(occurred_at__gte=since)
    by_bucket = qs.values("cost_bucket").annotate(s=Sum("amount_eur_cents"),
                                                   n=Count("id")).order_by("-s")
    by_persona = qs.values("persona__public_id", "persona__display_name").annotate(
        s=Sum("amount_eur_cents")).order_by("-s")
    return render(request, "console/costs.html", _nav(request) | {
        "by_bucket": by_bucket, "by_persona": by_persona,
        "total": qs.aggregate(s=Sum("amount_eur_cents"))["s"] or 0})


@console_view
def incidents(request):
    return render(request, "console/incidents.html", _nav(request) | {
        "incidents": PolicyIncident.objects.select_related("persona", "action")
        .order_by("-occurred_at")[:100]})


# ---------------------------------------------------------------- kill-switch


@console_view
@require_POST
def kill_switch(request):
    op = request.POST.get("operation")
    reason = request.POST.get("reason", "").strip()
    actor = principal_of(request.user)
    roles = roles_of(request.user)
    try:
        if op == "activate":
            if not (request.user.is_superuser or roles & E.KILL_SWITCH_ACTIVATORS):
                raise policy.PolicyError("FORBIDDEN", "Nemaš ulogu za zaustavljanje.")
            raw_scope, _, target = request.POST.get("scope_target", "GLOBAL:").partition(":")
            scope = E.KillSwitchScope(raw_scope)
            ks = policy.activate_kill_switch(scope, target,
                                             reason=reason or "Zaustavljeno iz konzole",
                                             actor=actor)
            messages.warning(request, f"ZAUSTAVLJENO ({ks.scope} {ks.target_ref or ''}) — "
                                      f"{ks.stop_latency_ms} ms")
        elif op == "clear":
            if not (request.user.is_superuser or roles & E.KILL_SWITCH_RELEASERS):
                raise policy.PolicyError("FORBIDDEN", "Puštanje traži trust_safety, "
                                                      "runtime_admin ili system_admin.")
            ks = KillSwitch.objects.filter(id=request.POST.get("kill_switch_id")).first()
            if ks is None:
                raise Http404
            policy.release_kill_switch(ks, actor=actor, reason=reason)
            messages.success(request, "Pušteno. Blokirane akcije ostaju blokirane.")
        else:
            messages.error(request, "Nepoznata operacija.")
    except (policy.PolicyError, ValueError) as e:
        messages.error(request, str(e))
    return redirect("/console/")

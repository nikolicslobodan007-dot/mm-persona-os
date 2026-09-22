"""Kontrolna tabla. ADR-0010.

Server renderuje HTML; JavaScript je samo pomoć (odbrojavanje, potvrda).
Svaki upis ide kroz isti servisni sloj kao API — konzola nema svoja pravila.
"""

from __future__ import annotations

import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.db.models import Count, Sum
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
from apps.personas.models import Persona
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
    try:
        policy.decide_approval(ap, E.ApprovalStatus(decision), actor=principal_of(request.user),
                               role=role, reason=reason, payload_override=override)
    except policy.PolicyError as e:
        messages.error(request, str(e))
        return redirect("/console/approvals")
    a = Action.objects.get(pk=ap.action_id)
    _sync_content(a)
    label = {"APPROVED": "Odobreno", "APPROVED_WITH_CHANGES": "Odobreno sa izmenom",
             "REJECTED": "Odbijeno"}[decision]
    messages.success(request, f"{label}: {a.public_id} → {a.status}")
    return redirect("/console/approvals")


def _sync_content(action: Action) -> None:
    from apps.content.service import sync_from_action

    sync_from_action(action)


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
        "accounts": p.channel_accounts.all().order_by("channel_type"),
        "can_draft": bool(_roles(request.user) & _DRAFTERS)
        and p.status in {E.PersonaStatus.READY.value, E.PersonaStatus.ACTIVE.value},
        "manual_limit": _manual_limit(),
    }
    return render(request, "console/persona.html", ctx)


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

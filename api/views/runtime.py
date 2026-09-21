"""Runtime, kanali i odjava. Canon §8.2 · ADR-0008.

    GET  /api/v1/channels/accounts                      nalozi persona
    GET  /api/v1/channels/accounts/{id}/capabilities    šta nalog STVARNO može
    GET  /api/v1/ops/overview                           stanje reda, sesija, breaker-a
    POST /api/v1/mail/suppressions                      ručna odjava (adresa ili domen)
    GET|POST /api/v1/mail/unsubscribe                   javna odjava, RFC 8058 (ADR-0008)

`/mail/unsubscribe` je jedina ruta bez prijave: primalac mora moći da se
odjavi jednim klikom. Link nosi potpisan hash adrese, ne adresu.
"""

from __future__ import annotations

import html

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers

from api.base import AUDIT_READERS, PersonaOSView, ok
from api.context import bind, current
from api.errors import ApiError
from api.idempotency import idempotent
from apps.channels import suppression
from apps.channels.models import ChannelAccount, SuppressionEntry
from apps.personas.models import Persona
from apps.policy import config as policy_config
from apps.runtime import config as rconfig
from apps.runtime.executor import runtime_overview
from common import enums as E

SUPPRESSORS = frozenset(set(E.Role) - {E.Role.VIEWER})


def _account_out(a: ChannelAccount) -> dict:
    return {
        "id": str(a.id), "persona_id": a.persona.public_id, "channel_type": a.channel_type,
        "identity_vehicle": a.identity_vehicle, "handle": a.handle, "status": a.status,
        "disclosure_label_status": a.disclosure_label_status,
        "named_human_admin": a.named_human_admin or None,
        "has_credential_ref": bool(a.credential_ref),
        "sending_domain": a.sending_domain or None,
    }


class ChannelAccountListView(PersonaOSView):
    @extend_schema(operation_id="channel_accounts_list",
                   parameters=[OpenApiParameter("persona_id", str),
                               OpenApiParameter("channel_type", str,
                                                enum=E.ChannelType.values())],
                   responses={200: dict})
    def get(self, request):
        qs = ChannelAccount.objects.select_related("persona").order_by("persona__public_id",
                                                                         "channel_type")
        if request.query_params.get("persona_id"):
            qs = qs.filter(persona__public_id=request.query_params["persona_id"])
        if request.query_params.get("channel_type"):
            qs = qs.filter(channel_type=request.query_params["channel_type"])
        return ok([_account_out(a) for a in qs[:500]])


class ChannelAccountCapabilitiesView(PersonaOSView):
    """Presek tri izvora: platforma (platforms.yaml), nalog (ChannelCapability), policy."""

    @extend_schema(operation_id="channel_account_capabilities", responses={200: dict})
    def get(self, request, account_id: str):
        acc = ChannelAccount.objects.select_related("persona").filter(id=account_id).first() \
            if _is_uuid(account_id) else None
        if acc is None:
            raise ApiError(E.ErrorCode.NOT_FOUND, "Nalog ne postoji.")
        enabled = set(acc.capabilities.filter(is_enabled=True).values_list("capability",
                                                                            flat=True))
        rows = []
        for row in rconfig.matrix():
            if row["channel_type"] != acc.channel_type:
                continue
            caps = policy_config.action_types().get(row["action_type"], [])
            rows.append(row | {"capabilities": caps,
                               "enabled_on_account": all(c in enabled for c in caps)})
        return ok({"account": _account_out(acc), "verified_on":
                   rconfig.platforms().get("verified_on"),
                   "reverify_by": rconfig.platforms().get("reverify_by"), "actions": rows})


def _is_uuid(v: str) -> bool:
    import uuid

    try:
        uuid.UUID(v)
    except ValueError:
        return False
    return True


class OpsOverviewView(PersonaOSView):
    required_roles = {"GET": AUDIT_READERS}

    @extend_schema(operation_id="ops_overview", responses={200: dict})
    def get(self, request):
        from django.db.models import Count

        personas = dict(Persona.objects.values_list("status").annotate(n=Count("id"))
                        .values_list("status", "n"))
        return ok({"personas": personas, "runtime": runtime_overview(),
                   "suppressions": SuppressionEntry.objects.count()})


class SuppressionIn(serializers.Serializer):
    address = serializers.EmailField(required=False)
    domain = serializers.CharField(required=False, max_length=253)
    reason = serializers.ChoiceField(choices=E.SuppressionReason.values(),
                                     default=E.SuppressionReason.MANUAL.value)


class SuppressionView(PersonaOSView):
    required_roles = {"POST": SUPPRESSORS}

    @extend_schema(operation_id="mail_suppressions_create", request=SuppressionIn,
                   responses={201: dict})
    @idempotent
    def post(self, request):
        data = SuppressionIn(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        if bool(v.get("address")) == bool(v.get("domain")):
            raise ApiError(E.ErrorCode.VALIDATION_ERROR, "Tačno jedno: address ili domain.")
        actor = current().principal
        if v.get("address"):
            entry, created = suppression.suppress(v["address"],
                                                  E.SuppressionReason(v["reason"]),
                                                  source="manual", actor=actor)
        else:
            entry, created = suppression.suppress_domain(v["domain"], source="manual",
                                                         actor=actor)
        return ok({"id": str(entry.id), "created": created, "reason": entry.reason},
                  status=201 if created else 200)


_PAGE = """<!doctype html><html lang="sr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>Odjava</title>
<style>body{{font-family:system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem;
color:#1b1b1b;background:#fafafa}}button{{font-size:1rem;padding:.6rem 1.2rem}}</style>
</head><body><h1>Odjava</h1><p>{msg}</p>{form}</body></html>"""


@csrf_exempt
@require_http_methods(["GET", "POST"])
def unsubscribe(request):
    """GET prikazuje dugme (skeneri linkova ne smeju da odjave); POST odjavljuje.

    RFC 8058: klijent šalje POST sa telom `List-Unsubscribe=One-Click` na isti URL.
    """
    token = request.GET.get("t") or request.POST.get("t") or ""
    ahash = suppression.hash_from_token(token)
    if ahash is None:
        return HttpResponse(_PAGE.format(msg="Link za odjavu nije ispravan.", form=""),
                            status=400)
    if request.method == "GET":
        form = (f'<form method="post"><input type="hidden" name="t" '
                f'value="{html.escape(token)}"><button type="submit">Odjavi me</button></form>')
        return HttpResponse(_PAGE.format(
            msg="Potvrdite da ne želite više da primate naše poruke.", form=form))
    with bind(actor_id="service:unsubscribe"):
        suppression.suppress_hash(ahash, E.SuppressionReason.UNSUBSCRIBE,
                                  source="one_click" if "List-Unsubscribe" in
                                  request.POST else "link")
    return HttpResponse(_PAGE.format(
        msg="Odjavljeni ste. Više vam nećemo pisati ni sa jedne naše adrese.", form=""))

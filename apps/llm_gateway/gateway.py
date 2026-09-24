"""LLM Gateway — jedini put do modela. Canon §13, §17 · ADR-0009.

    generate(purpose, system, prompt, persona=, run=, context_pack=) → Generation

Rute (`LLMRoute`) se biraju po svrsi i prioritetu; pad jedne vodi na sledeću.
Na kraju lanca je uvek `local` — deterministički sastavljač iz šablona, bez
mreže i bez troška. Zato sistem radi i bez ijednog API ključa, a simulacija
daje isti tekst za isti ulaz.

Spoljni model se poziva samo ako su ispunjena sva tri uslova:
  - `LLM_EXTERNAL_ENABLED=true` (podrazumevano false);
  - ruta ima `data_training_allowed=True`, tj. provajder izričito NE trenira
    na našim podacima (prompt nosi memoriju persone);
  - tajna postoji (`LLM_CREDENTIALS[provider]` → `env:` ili `file:`).

U bazi ostaju samo hash-ovi prompta i odgovora (`PromptRecord`), tokeni i
trošak (`LLMUsage`, `CostLedger`) — ne i tekst prompta.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_CEILING, Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.llm_gateway import local
from apps.llm_gateway.models import AgentRoute, LLMRoute, LLMUsage, PromptRecord
from common import enums as E

LOCAL_PROVIDER = "local"
LOCAL_MODEL = "template-v1"


class LLMError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


@dataclass
class Generation:
    text: str
    provider: str
    model: str
    record: PromptRecord
    input_tokens: int
    output_tokens: int
    amount_eur_cents: int
    fallbacks: list[str]


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _tokens(s: str) -> int:
    return max(1, (len(s) + 3) // 4)


def local_route(purpose: E.LLMPurpose) -> LLMRoute:
    route, _ = LLMRoute.objects.get_or_create(
        purpose=purpose.value, provider=LOCAL_PROVIDER, model_key=LOCAL_MODEL,
        defaults={"name": "Lokalni šablon (bez mreže)", "priority": 1000,
                  "temperature": 0, "data_training_allowed": True,
                  "is_openai_compatible": False,
                  "notes": "Deterministički; uvek poslednji u lancu (ADR-0009)."})
    return route


def routes(purpose: E.LLMPurpose, persona=None) -> list[LLMRoute]:
    """Rute za jednu svrhu: **prvo agentove, pa firmine, pa lokalni šablon**.

    Agentova ruta nije nova vrsta rute nego pokazivač na postojeću (ADR-0026):
    tako cena, `data_training_allowed` i ostali uslovi ostaju na jednom mestu,
    a agent bira samo redosled.
    """
    # Agentova ruta ne traži da je ruta uključena za celu firmu: tako jedan
    # agent sme da koristi model koji ostali nemaju, a da ga niko ne nasledi
    # kroz rezervu (ADR-0026).
    moje: list[LLMRoute] = []
    if persona is not None:
        moje = [ar.route for ar in AgentRoute.objects.filter(
            persona=persona, purpose=purpose.value, is_enabled=True,
        ).select_related("route").order_by("priority")]
    uzeti = {r.pk for r in moje}
    firmine = [r for r in LLMRoute.objects.filter(
        purpose=purpose.value, is_enabled=True).exclude(
        provider=LOCAL_PROVIDER).order_by("priority", "name") if r.pk not in uzeti]
    return moje + firmine + [local_route(purpose)]


def _external_allowed(route: LLMRoute, persona=None) -> str | None:
    if not getattr(settings, "LLM_EXTERNAL_ENABLED", False):
        return "LLM_EXTERNAL_DISABLED"
    if not route.data_training_allowed:
        return "PROVIDER_MAY_TRAIN"
    # Ključ sme da dođe iz tri mesta: agentov ključ iz konzole (ADR-0026),
    # promenljiva okruženja po agentu, ili zajednička. Nijedno od to troje —
    # ruta ne postoji za ovog agenta, ma koliko bila jeftina.
    ref, _izvor = credential_ref(route.provider, persona)
    if ref:
        return None
    return "NO_PERSONA_KEY" if persona is not None else "NO_CREDENTIAL_REF"


# ---------------------------------------------------------------- provajderi


def _post_json(url: str, headers: dict, body: dict, timeout: int) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise LLMError(f"HTTP_{e.code}", e.read().decode(errors="replace")[:300]) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LLMError("NETWORK", str(e)[:300]) from e


def persona_env_name(provider: str, persona) -> str | None:
    """Ime promenljive za ključ jedne persone: `ANTHROPIC_API_KEY` → `ANTHROPIC_API_KEY_P00001`.

    Samo za `env:` reference. U bazi nema ni ključa ni imena — pravilo je u kodu
    (ADR-0013), a ključ je samo u `.env.prod`.
    """
    base = getattr(settings, "LLM_CREDENTIALS", {}).get(provider, "")
    if persona is None or not base.startswith("env:"):
        return None
    return f"{base[4:]}_{persona.public_id.replace('-', '')}"


def credential_ref(provider: str, persona=None) -> tuple[str | None, str]:
    """(referenca, izvor) — izvor je `persona`, `shared` ili `none`.

    Persona sa svojim ključem koristi njega. Bez njega koristi zajednički, osim
    ako je `LLM_REQUIRE_PERSONA_KEY=true` — tada ide na lokalni šablon.
    """
    if persona is not None:
        from apps.llm_gateway import secrets as agent_secrets

        if (ref := agent_secrets.ref_for(persona, provider)):
            return ref, "persona"
    name = persona_env_name(provider, persona)
    if name and os.environ.get(name, "").strip():
        return f"env:{name}", "persona"
    if persona is not None and getattr(settings, "LLM_REQUIRE_PERSONA_KEY", False):
        return None, "none"
    base = getattr(settings, "LLM_CREDENTIALS", {}).get(provider)
    return (base, "shared") if base else (None, "none")


def _call_external(route: LLMRoute, system: str, prompt: str,
                   persona=None) -> tuple[str, int, int, str]:
    from apps.runtime.transport import CredentialMissing, resolve_secret

    ref, source = credential_ref(route.provider, persona)
    if ref is None:
        raise LLMError("NO_PERSONA_KEY", persona.public_id if persona else "")
    try:
        key = resolve_secret(ref).strip()
    except CredentialMissing as e:
        raise LLMError("CREDENTIAL_MISSING", str(e)) from e
    if source == "persona" and persona is not None and ref.startswith("file:"):
        from apps.llm_gateway import secrets as agent_secrets

        agent_secrets.touch(persona, route.provider)
    max_out = route.max_output_tokens or 800
    if route.provider == "anthropic":
        base = route.base_url or getattr(settings, "LLM_BASE_URLS", {}).get(
            "anthropic", "https://api.anthropic.com")
        # Claude 5 generacija: `temperature`/`top_p` → 400, a razmišljanje je
        # uključeno ako se ne isključi. Za kratke objave ga isključujemo (brže,
        # jeftinije); ruta može da ga uključi sa quota_json {"thinking": "adaptive"}.
        body = {"model": route.model_key, "max_tokens": max_out, "system": system,
                "messages": [{"role": "user", "content": prompt}]}
        thinking = (route.quota_json or {}).get("thinking", "disabled")
        if thinking in ("disabled", "adaptive"):
            body["thinking"] = {"type": thinking}
        data = _post_json(f"{base}/v1/messages",
                          {"x-api-key": key, "anthropic-version": "2023-06-01"},
                          body, route.timeout_seconds)
        text = "".join(b.get("text", "") for b in data.get("content", [])
                       if b.get("type") == "text")
        u = data.get("usage") or {}
        return (text, int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0)),
                str(data.get("stop_reason", "")))
    if route.is_openai_compatible:
        base = route.base_url or getattr(settings, "LLM_BASE_URLS", {}).get(
            route.provider)
        if not base:
            raise LLMError("NO_BASE_URL", route.provider)
        data = _post_json(f"{base.rstrip('/')}/chat/completions",
                          {"Authorization": f"Bearer {key}"},
                          {"model": route.model_key, "max_tokens": max_out,
                           "temperature": float(route.temperature),
                           "messages": [{"role": "system", "content": system},
                                        {"role": "user", "content": prompt}]},
                          route.timeout_seconds)
        choice = (data.get("choices") or [{}])[0]
        u = data.get("usage") or {}
        return ((choice.get("message") or {}).get("content", ""),
                int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0)),
                str(choice.get("finish_reason", "")))
    raise LLMError("UNSUPPORTED_PROVIDER", route.provider)


def _cost_cents(route: LLMRoute, tin: int, tout: int) -> int:
    micro = (Decimal(route.input_price_micro_eur_per_1k) * tin
             + Decimal(route.output_price_micro_eur_per_1k) * tout) / 1000
    # mikroevri → centi: 1 cent = 10 000 mikroevra
    return int((micro / 10_000).to_integral_value(rounding=ROUND_CEILING))


# ---------------------------------------------------------------- generate


def generate(purpose: E.LLMPurpose, system: str, prompt: str, *, persona=None, run=None,
             context_pack=None, brief: dict | None = None,
             now: datetime | None = None, only: LLMRoute | None = None) -> Generation:
    """`brief` je strukturisan ulaz za lokalni šablon (tema, ugao, jezik…).

    `only` — samo ta ruta, bez prelaska na sledeću (za merenje, ADR-0011).
    """
    now = now or timezone.now()
    fallbacks: list[str] = []
    for route in ([only] if only is not None else routes(purpose, persona)):
        t0 = time.monotonic()
        external = route.provider != LOCAL_PROVIDER
        if external:
            why = _external_allowed(route, persona)
            if why:
                fallbacks.append(f"{route.provider}/{route.model_key}:{why}")
                continue
        try:
            if external:
                text, tin, tout, finish = _call_external(route, system, prompt, persona)
            else:
                text = local.compose(purpose, brief or {}, prompt)
                tin, tout, finish = _tokens(system + prompt), _tokens(text), "template"
            if not text.strip():
                raise LLMError("EMPTY_RESPONSE")
        except LLMError as e:
            fallbacks.append(f"{route.provider}/{route.model_key}:{e.code}")
            _record(route, purpose, system, prompt, "", persona, run, context_pack, now,
                    t0, error=e.code)
            continue
        cents = _cost_cents(route, tin, tout) if external else 0
        rec = _record(route, purpose, system, prompt, text, persona, run, context_pack, now,
                      t0, finish=finish, tin=tin, tout=tout, cents=cents, external=external)
        return Generation(text.strip(), route.provider, route.model_key, rec, tin, tout, cents,
                          fallbacks)
    raise LLMError("NO_ROUTE", "; ".join(fallbacks))


def _record(route, purpose, system, prompt, text, persona, run, pack, now, t0, *,
            finish: str = "", error: str = "", tin: int = 0, tout: int = 0, cents: int = 0,
            external: bool = False) -> PromptRecord:
    from apps.observability import bus
    from apps.observability.models import CostLedger

    with transaction.atomic():
        rec = PromptRecord.objects.create(
            persona=persona, run=run, context_pack=pack, route=route, purpose=purpose.value,
            system_hash=_sha(system), prompt_hash=_sha(prompt),
            response_hash=_sha(text) if text else "", started_at=now,
            finished_at=now, latency_ms=int((time.monotonic() - t0) * 1000),
            finish_reason=finish[:40], error_code=error[:80],
            trace_id=run.trace_id if run is not None else None)
        cost = None
        if cents > 0:
            cost = CostLedger.objects.create(
                persona=persona, run=run, cost_bucket=E.CostBucket.LLM.value,
                provider=route.provider, quantity=Decimal(tin + tout), unit="tokens",
                amount_eur_cents=cents, source_currency="EUR", source_amount_minor=cents,
                fx_rate=1, fx_date=now.date(), occurred_at=now, provider_ref=str(rec.id))
            bus.emit("cost.recorded", {"bucket": E.CostBucket.LLM.value,
                                       "amount_eur_cents": cents, "source_currency": "EUR"},
                     persona_id=persona.public_id if persona else None,
                     run_id=run.public_id if run is not None else None)
        if text:
            LLMUsage.objects.create(
                prompt_record=rec, route=route, cost_bucket=E.CostBucket.LLM.value,
                input_tokens=tin, output_tokens=tout, amount_eur_cents=cents,
                is_estimated=not external, cost_entry=cost, recorded_at=now)
    return rec

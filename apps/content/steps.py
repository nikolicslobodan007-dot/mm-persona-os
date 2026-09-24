"""Koraci plana koji se tiču sadržaja. ADR-0024.

Do sada je plan umeo samo poštu. Šef koji nekome zada posao morao je da mu
zada — ništa; delegiranje je postojalo, ali izvršilac nije imao šta da radi.

Ovde su dva koraka od kojih posao počinje:

  - `content.draft` — napiši nacrt na zadatu temu. Nema spoljašnjeg efekta,
    pa ne traži odobrenje; tekst iz modela prolazi iste tvrde zabrane kao i
    objava (ADR-0009).
  - `content.submit` — pošalji nacrt na odobrenje za objavu. Ovo **jeste**
    spoljašnji efekat, pa korak čeka čoveka kao i svaki drugi (Canon §15.2).

Korak ne bira nalog umesto čoveka: ako persona nema nalog sa pravom objave,
korak staje sa razlogom, ne traži prečicu.
"""

from __future__ import annotations

from apps.content import service as content
from apps.orchestration import plans
from common import enums as E


@plans.handler("content.draft")
def _draft(step: plans.PlanStep, state: dict) -> plans.Outcome:
    """Nacrt na temu iz koraka — ili na temu koju je nalogodavac zadao kao cilj."""
    tema = (step.input_json or {}).get("tema", "") or state.get("goal", "")
    if not tema.strip():
        return plans.Failed("Korak nema temu.")
    try:
        item = content.draft(step.plan.persona, topic=tema, run=step.plan.run)
    except content.ContentError as e:
        return plans.Failed(str(e)[:300])
    return plans.Done({"item": str(item.id), "hash": item.content_hash[:16],
                       "tema": tema, "tekst": (item.body or "")[:400]})


@plans.handler("content.submit")
def _submit(step: plans.PlanStep, state: dict) -> plans.Outcome:
    """Šalje poslednji nacrt na odobrenje. Bez odobrenja ništa ne izlazi."""
    from apps.content.models import ContentItem

    nacrti = state.get("by_handler", {}).get("content.draft") or []
    if not nacrti:
        return plans.Failed("Nema nacrta — korak `content.draft` nije prošao.")
    item = ContentItem.objects.filter(pk=nacrti[-1].get("item", "")).first()
    if item is None:
        return plans.Failed("Nacrt više ne postoji.")
    account = step.plan.persona.channel_accounts.filter(
        status=E.AccountStatus.ACTIVE.value,
        capabilities__capability="content.publish_approved",
        capabilities__is_enabled=True).first()
    if account is None:
        return plans.Failed(f"{step.plan.persona.public_id} nema nalog sa pravom "
                            "objave — objavu ne može ni da predloži.")
    try:
        pr = content.submit(item, account)
    except content.ContentError as e:
        return plans.Failed(str(e)[:300])
    if pr.action.status == E.ActionStatus.APPROVAL_PENDING:
        return plans.Waiting(pr.action, note=f"Objava na {account.handle} čeka odobrenje.")
    return plans.Done({"action": pr.action.public_id, "status": pr.action.status})

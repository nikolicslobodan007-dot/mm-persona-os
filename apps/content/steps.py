"""Koraci plana koji se tiču sadržaja. ADR-0024.

Do sada je plan umeo samo poštu. Šef koji nekome zada posao morao je da mu
zada — ništa; delegiranje je postojalo, ali izvršilac nije imao šta da radi.

Ovde su dva koraka od kojih posao počinje:

  - `content.draft` — napiši nacrt na zadatu temu. Nema spoljašnjeg efekta,
    pa ne traži odobrenje; tekst iz modela prolazi iste tvrde zabrane kao i
    objava (ADR-0009).
  - `content.document` — od nacrta napravi stvaran fajl (ADR-0103). Fajl
    ostaje kod nas, u našem skladištu; ništa ne izlazi napolje, pa ni ovaj
    korak ne traži odobrenje.
  - `content.review` — šef pregleda nacrt pre nego što ga vrati nalogodavcu
    (ADR-0108). Nema spoljašnjeg efekta; vraćen nacrt obara korak, pa se u
    nit vraća razlog, a ne tiho prihvaćen tekst.
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
    if item.status != E.ContentStatus.DRAFT.value:
        # Odbijen nacrt (ponavljanje, tvrda zabrana) nije obavljen posao.
        return plans.Failed(f"Nacrt odbijen: {item.status_reason or item.status}")
    return plans.Done({"item": str(item.id), "hash": item.content_hash[:16],
                       "tema": tema, "tekst": (item.body or "")[:400],
                       "model": _ko_je_pisao(item)})


def _ko_je_pisao(item) -> str:
    """`anthropic/claude-sonnet-5` ili `local/template-v1` — mora da se vidi.

    Lokalni šablon je ispravna rezerva (ADR-0009), ali nacrt koji je napisao
    šablon ne sme da izgleda kao nacrt koji je napisao model. Agent bez ključa
    tiho piše šablonom; ovo je mesto gde se to primeti.
    """
    from apps.llm_gateway.models import PromptRecord

    pr = (PromptRecord.objects.filter(run=item.run).select_related("route")
          .order_by("-started_at").first())
    return f"{pr.route.provider}/{pr.route.model_key}" if pr else "—"


@plans.handler("content.document")
def _dokument(step: plans.PlanStep, state: dict) -> plans.Outcome:
    """Pretvara poslednji nacrt u fajl. ADR-0103.

    Format se zadaje u koraku (`oblik`); podrazumevan je `odt`, jedini koji
    sigurno radi i bez LibreOffice-a u slici.
    """
    from apps.content import dokument
    from apps.content.models import ContentItem

    nacrti = state.get("by_handler", {}).get("content.draft") or []
    if not nacrti:
        return plans.Failed("Nema nacrta — korak `content.draft` nije prošao.")
    item = ContentItem.objects.filter(pk=nacrti[-1].get("item", "")).first()
    if item is None:
        return plans.Failed("Nacrt više ne postoji.")
    oblik = (step.input_json or {}).get("oblik", "odt")
    try:
        asset = dokument.napravi(item, oblik=oblik,
                                 actor=f"agent:{step.plan.persona.public_id}")
    except dokument.DokumentError as e:
        return plans.Failed(str(e)[:300])
    return plans.Done({"asset": asset.public_id, "oblik": oblik,
                       "kljuc": asset.storage_key, "sadrzaj": str(item.id)})


@plans.handler("content.review")
def _pregled(step: plans.PlanStep, state: dict) -> plans.Outcome:
    """Šef čita nacrt koji mu je izvršilac vratio. ADR-0108.

    Nacrt se traži i u planovima ispod, jer ga je pisao izvršilac u svom
    planu, a ne šef u ovom. Čita se **cela** `ContentItem`, ne skraćeni
    izlaz koraka: pregled polovine teksta nije pregled.
    """
    from apps.content import pregled
    from apps.content.models import ContentItem

    nacrt = (state.get("by_handler", {}).get("content.draft") or [{}])[-1]
    if not nacrt.get("item"):
        nacrt = plans.output_in_chain(step.plan, "content.draft") or {}
    kljuc = nacrt.get("item") or ""
    item = ContentItem.objects.filter(pk=kljuc).first() if kljuc else None
    if item is None:
        return plans.Failed("Nema nacrta za pregled.")

    nalog = (step.input_json or {}).get("nalog") or state.get("goal", "")
    ishod = pregled.oceni(step.plan.persona, nalog, item.body or "",
                          run=step.plan.run)
    if ishod.prihvacen:
        return plans.Done({"prihvacen": True, "primedba": ishod.primedba,
                           "presudio": ishod.presudio, "item": str(item.id),
                           "pregledao": step.plan.persona.public_id})
    return plans.Failed(plans.shorten(
        f"{step.plan.persona.display_name} vraća nacrt: {ishod.primedba}", 700))


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

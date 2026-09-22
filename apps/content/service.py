"""Sadržaj: ideja → nacrt → odobrenje → objava. Canon §15.3, §16.3 · ADR-0009.

    create_idea(persona, topic)              ideja (dedupe po normalizovanoj temi)
    draft(persona, topic=… | body=…)         nacrt kroz memoriju i LLM Gateway
    submit(item, account)                    predlog objave → policy → odobrenje
    sync_from_action(action)                 stanje sadržaja prati stanje akcije
    plan_post_for_run(run)                   buđenje sa aktivnošću „post” → nacrt

Nacrt je UNUTRAŠNJI: ne ide kroz policy i nema spoljni efekat. Objava je
spoljna akcija i ide kroz propose → policy (A2 za svaku javnu objavu) →
odobrenje → kapija → adapter. Sadržaj nikad ne menja status sam — prati akciju.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from api import audit
from api.context import current
from apps.channels.models import ChannelAccount
from apps.content.models import ContentIdea, ContentItem, Publication
from apps.llm_gateway import gateway
from apps.memory import context as memory_context
from apps.orchestration.models import Action, AgentRun
from apps.personas.models import Persona, PersonaTagLink
from apps.policy import config as policy_config
from apps.policy import guards
from apps.policy import service as policy
from apps.runtime.adapters.social import similarity
from common import enums as E
from common import ids as I

CS = E.ContentStatus
PS = E.PublicationStatus
REPETITION_THRESHOLD = 0.8          # Canon §16.3 — ponavljanje je kapija pilota
REPETITION_WINDOW_DAYS = 30
PUBLISH_CAPABILITY = "content.publish_approved"
_SANDBOX_ONLY = {E.RuntimeEnvironment.SIMULATION.value, E.RuntimeEnvironment.SHADOW.value}


class ContentError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def topic_key(topic: str) -> str:
    t = unicodedata.normalize("NFKD", topic.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return "-".join(re.findall(r"[a-z0-9]+", t))[:200]


def disclosure_line(persona: Persona) -> str:
    name = re.sub(r"\s*\(AI\)\s*$", "", persona.display_name).strip()
    return f"— {name} · AI persona"


# ---------------------------------------------------------------- ideje


def create_idea(persona: Persona, topic: str, *, angle: str = "", priority: int = 0,
                source_event=None, source_memory=None) -> tuple[ContentIdea, bool]:
    key = topic_key(topic)
    if not key:
        raise ContentError("VALIDATION_ERROR", "Tema je prazna.")
    existing = ContentIdea.objects.filter(persona=persona, dedupe_key=key).first()
    if existing:
        return existing, False
    try:
        with transaction.atomic():
            return ContentIdea.objects.create(
                persona=persona, topic=topic.strip()[:220], angle=angle, priority=priority,
                source_event=source_event, source_memory=source_memory, dedupe_key=key,
                status=E.IdeaStatus.OPEN), True
    except IntegrityError:
        return ContentIdea.objects.get(persona=persona, dedupe_key=key), False


# ---------------------------------------------------------------- nacrt


def operator_run(persona: Persona, now: datetime) -> AgentRun:
    """Nacrt koji je tražio operator i dalje pripada buđenju persone (Canon §7.1)."""
    trace = current().trace_id
    import uuid

    return AgentRun.objects.create(
        public_id=I.ulid_public_id(I.EntityKind.AGENT_RUN, now), persona=persona,
        wake_priority=E.WakePriority.OPERATOR_TASK.value, status=E.RunStatus.COMPLETED,
        started_at=now, ended_at=now, decisions_count=1, trace_id=uuid.UUID(hex=trace),
        decision=E.WakeDecision.ACT.value, reason_code=E.DecisionReason.OPERATOR_TASK.value,
        summary_json={"task": "content_draft"},
    )


def _system_prompt(persona: Persona) -> str:
    lang = ("srpski, latinica, pravilna gramatika i padeži"
            if persona.primary_locale.lower().startswith("sr") else persona.primary_locale)
    return "\n".join([
        f"Pišeš kao {persona.display_name}, AI persona. Ne tvrdi da si čovek.",
        "Piši kratko, konkretno, bez preuveličavanja. Brojke samo sa izvorom.",
        "Ne pominji stvarne osobe imenom. Ne traži lične podatke od čitalaca.",
        "Vrati samo tekst objave: bez naslova, bez svog imena i potpisa, bez "
        "markdown-a (bez **, #, listi), bez hashtag-ova. Potpis i AI oznaku sistem dodaje sam.",
        "Tri do pet kratkih rečenica: jedan problem, jedan konkretan primer, jedan zaključak.",
        "Kontekst iz memorije koristi kao znanje, ne prepisuj ga doslovno.",
        f"Jezik: {lang}.",
    ])


_MD = re.compile(r"(\*\*|__|^#+\s*|^[-*]\s+)", re.M)


def clean_generated(text: str, persona: Persona) -> str:
    """Model ponekad doda naslov sa imenom ili markdown — objava ga ne prikazuje."""
    lines = text.strip().splitlines()
    name = persona.display_name.split("(")[0].strip().lower()
    while lines and (not lines[0].strip() or name in lines[0].lower()
                     and len(lines[0]) <= len(persona.display_name) + 6):
        lines.pop(0)
    out = _MD.sub("", "\n".join(lines))
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def _repetition(persona: Persona, text: str, now: datetime,
                exclude_pk=None) -> ContentItem | None:
    since = now - timedelta(days=REPETITION_WINDOW_DAYS)
    qs = (ContentItem.objects.filter(persona=persona, created_at__gte=since)
          .exclude(status__in=[CS.REJECTED.value, CS.ARCHIVED.value]))
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    for other in qs.only("id", "body"):
        if similarity(text, other.body) >= REPETITION_THRESHOLD:
            return other
    return None


#: Samo znanje sme doslovno u javni tekst i kao izvor. Procedure („pre svake
#: objave…”), epizode („nacrt u prozoru…”) i odnosi ostaju unutrašnji kontekst
#: modelu — nisu činjenice za čitaoca (ADR-0011 §5).
QUOTABLE_MEMORY = frozenset({E.MemoryType.SEMANTIC.value, E.MemoryType.CONTENT.value})


def draft(persona: Persona, *, topic: str = "", idea: ContentIdea | None = None,
          angle: str = "", body: str | None = None,
          fmt: E.ContentFormat = E.ContentFormat.POST, run: AgentRun | None = None,
          now: datetime | None = None) -> ContentItem:
    """Pravi nacrt. Tekst iz modela prolazi iste tvrde zabrane kao i objava."""
    now = now or timezone.now()
    if idea is not None:
        topic, angle = idea.topic, angle or idea.angle
    if body is None and not topic.strip():
        raise ContentError("VALIDATION_ERROR", "Potrebna je tema ili tekst.")
    with transaction.atomic():
        run = run or operator_run(persona, now)
        provenance, gen, pack, quotable = E.Provenance.USER_PROVIDED, None, None, []
        if body is None:
            pack = memory_context.build(persona, run, E.RetrievalProfile.CONTENT_CREATION,
                                        query=topic, now=now)
            quotable = [sc for sc in pack.items
                        if sc.memory.memory_type in QUOTABLE_MEMORY][:2]
            facts = [sc.memory.content if len(sc.memory.content) < 200 else sc.memory.title
                     for sc in quotable]
            gen = gateway.generate(
                E.LLMPurpose.CONTENT_DRAFT, _system_prompt(persona),
                f"{pack.text}\n\n## zadatak\nNapiši kratku objavu na temu: {topic}."
                + (f" Ugao: {angle}." if angle else ""),
                persona=persona, run=run, context_pack=pack.record, now=now,
                brief={"topic": topic, "angle": angle, "facts": facts,
                       "language": persona.primary_locale})
            body, provenance = gen.text, E.Provenance.GENERATED
            if gen.provider != gateway.LOCAL_PROVIDER:
                body = clean_generated(body, persona)
        body = body.strip()
        disclose = persona.disclosure_mode == E.DisclosureMode.ALWAYS_VISIBLE.value
        if disclose and disclosure_line(persona) not in body:
            body = f"{body}\n\n{disclosure_line(persona)}"
        status, reason = CS.DRAFT, ""
        hits = guards.prohibitions("channel.post.create", {"text": body}, "")
        if hits:
            status, reason = CS.REJECTED, f"HARD_PROHIBITION:{hits[0]}"
        elif (dup := _repetition(persona, body, now)) is not None:
            status, reason = CS.REJECTED, "REPETITION"
            audit.record("content.item.repetition", persona=persona,
                         details={"similar_to": str(dup.id)})
        item = ContentItem.objects.create(
            persona=persona, idea=idea, format=fmt.value, title=topic[:220], body=body,
            language=persona.primary_locale, status=status.value, content_hash=_hash(body),
            provenance=provenance.value, disclosure_included=disclose, run=run,
            status_reason=reason,
            citations=[{"memory_id": str(sc.memory.id), "title": sc.memory.title}
                       for sc in (quotable if pack else [])],
        )
        if idea is not None and status == CS.DRAFT:
            ContentIdea.objects.filter(pk=idea.pk).update(status=E.IdeaStatus.USED.value)
        audit.record("content.item.drafted", persona=persona,
                     details={"content_id": str(item.id), "status": item.status,
                              "reason": reason, "provider": gen.provider if gen else "user",
                              "fallbacks": gen.fallbacks if gen else []})
    return item


# ---------------------------------------------------------------- objava


def publish_channel(persona: Persona) -> ChannelAccount | None:
    """Nalog na koji persona sme da predloži objavu, ili None.

    SIMULATION i SHADOW → samo SANDBOX. Traži uključen capability na nalogu i
    poverenje ≥ minimuma — inače bi predlog bio odbijen i samo bi pravio šum.
    """
    minimum = (policy_config.capability(PUBLISH_CAPABILITY) or {}).get("min_trust_level",
                                                                        "L1")
    level = policy.trust_map(persona).get(PUBLISH_CAPABILITY, E.TrustLevel.L0)
    if not policy_config.trust_at_least(level, minimum):
        return None
    qs = ChannelAccount.objects.filter(
        persona=persona, status=E.AccountStatus.ACTIVE.value,
        capabilities__capability=PUBLISH_CAPABILITY, capabilities__is_enabled=True)
    if persona.runtime_environment in _SANDBOX_ONLY:
        qs = qs.filter(channel_type=E.ChannelType.SANDBOX.value)
    accounts = sorted(qs.distinct(), key=lambda a: (a.channel_type == "SANDBOX", a.handle))
    return accounts[0] if accounts else None


def submit(item: ContentItem, account: ChannelAccount, *, scheduled_for: datetime | None = None,
           now: datetime | None = None) -> policy.Proposal:
    now = now or timezone.now()
    if item.status != CS.DRAFT.value:
        raise ContentError("VERSION_CONFLICT", f"Sadržaj je {item.status}, ne DRAFT.")
    if account.persona_id != item.persona_id:
        raise ContentError("VALIDATION_ERROR", "Nalog ne pripada personi.")
    ttl = timedelta(minutes=E.APPROVAL_TTL_MINUTES[E.ApprovalClass.A2])
    if scheduled_for and not (now <= scheduled_for <= now + ttl):
        raise ContentError(
            "VALIDATION_ERROR",
            f"scheduled_for mora biti u narednih {int(ttl.total_seconds() // 60)} min — "
            "odobrenje važi toliko (Canon §15.2). Duži kalendar dolazi uz ponovno odobrenje.")
    payload = {"text": item.body, "content_id": str(item.id)}
    pr = policy.propose(item.persona, "channel.post.create", payload,
                        intent=f"Objava sadržaja {item.id}", channel=account, run=item.run,
                        now=now)
    with transaction.atomic():
        if scheduled_for:
            Action.objects.filter(pk=pr.action.pk).update(scheduled_for=scheduled_for)
            from apps.runtime.models import WorkerJob

            WorkerJob.objects.filter(action=pr.action, status=E.JobStatus.PENDING.value
                                     ).update(run_after=scheduled_for)
        Publication.objects.get_or_create(
            content=item, channel_account=account, action=pr.action,
            defaults={"status": PS.SCHEDULED.value, "scheduled_for": scheduled_for})
    sync_from_action(Action.objects.get(pk=pr.action.pk))
    return pr


_OPEN = {S.value for S in (E.ActionStatus.PROPOSED, E.ActionStatus.POLICY_CHECK,
                           E.ActionStatus.APPROVAL_PENDING)}
_GO = {S.value for S in (E.ActionStatus.QUEUED, E.ActionStatus.RUNNING,
                         E.ActionStatus.RETRY_WAIT)}
_END = {S.value for S in (E.ActionStatus.BLOCKED, E.ActionStatus.FAILED,
                          E.ActionStatus.CANCELLED, E.ActionStatus.EXPIRED)}


def sync_from_action(action: Action) -> int:
    """Idempotentno. Poziva ga potrošač eventa i `submit`."""
    n = 0
    with transaction.atomic():
        for pub in (Publication.objects.select_for_update(of=("self",))
                    .filter(action=action).select_related("content")):
            item = ContentItem.objects.select_for_update().get(pk=pub.content_id)
            text = str((action.input_json or {}).get("text") or "")
            if text and text != item.body:  # APPROVED_WITH_CHANGES
                item.body, item.content_hash = text, _hash(text)
                item.version += 1
            st = action.status
            if st in _OPEN:
                item.status = CS.IN_REVIEW.value
            elif st in _GO:
                pub.status = PS.SCHEDULED.value
                if action.scheduled_for:
                    item.status, item.scheduled_for = CS.SCHEDULED.value, action.scheduled_for
                else:
                    item.status = CS.APPROVED.value
            elif st == E.ActionStatus.SUCCEEDED.value:
                res = action.result_json or {}
                pub.status, pub.published_at = PS.PUBLISHED.value, action.completed_at
                pub.provider_post_id = res.get("external_ref")
                pub.provider_payload = {"dry_run": bool(res.get("dry_run", True)),
                                        "reason_code": res.get("reason_code")}
                item.status = CS.PUBLISHED.value
            elif st in _END:
                pub.status, pub.error_code = PS.FAILED.value, action.error_code[:80]
                rejected = action.approvals.filter(
                    status=E.ApprovalStatus.REJECTED.value).exists()
                item.status = CS.REJECTED.value if rejected else CS.FAILED.value
                item.status_reason = ("APPROVAL_REJECTED" if rejected
                                      else action.error_code)[:80]
            pub.save()
            item.save()
            n += 1
    return n


# ---------------------------------------------------------------- planer


def choose_topic(persona: Persona, run: AgentRun) -> str:
    ev = run.trigger_event
    topics = [str(t) for t in ((ev.payload or {}).get("topics", []) if ev else [])]
    if topics:
        return topics[0]
    tags = list(PersonaTagLink.objects.filter(persona=persona).select_related("tag")
                .order_by("-weight", "tag__slug").values_list("tag__name", flat=True))
    if not tags:
        return ""
    day = run.started_at.date().toordinal()
    return tags[day % len(tags)]


def plan_post_for_run(run: AgentRun) -> ContentItem | None:
    """Prozor „post” u buđenju → nacrt → (ako postoji dozvoljen kanal) predlog objave."""
    persona = run.persona
    if persona.status not in (E.PersonaStatus.READY.value, E.PersonaStatus.ACTIVE.value):
        return None
    existing = ContentItem.objects.filter(run=run).first()
    if existing:
        return existing
    topic = choose_topic(persona, run)
    if not topic:
        return None
    item = draft(persona, topic=topic, run=run, now=run.started_at)
    if item.status != CS.DRAFT.value:
        return item
    account = publish_channel(persona)
    if account is not None:
        submit(item, account, now=run.started_at)
        item.refresh_from_db()
    return item


# ---------------------------------------------------------------- ručni nacrt (konzola)

#: Koliko ručnih nacrata dnevno po personi — štiti trošak modela od greške ili
#: zaglavljenog dugmeta. Rutina persone se ne računa ovde.
MANUAL_DRAFTS_PER_DAY = 10
MANUAL_STATUSES = frozenset({E.PersonaStatus.READY.value, E.PersonaStatus.ACTIVE.value})


def manual_topic(persona: Persona) -> str:
    """Bez teme od operatora: niše persone redom, da uzastopni nacrti ne budu isti."""
    tags = list(PersonaTagLink.objects.filter(persona=persona).select_related("tag")
                .order_by("-weight", "tag__slug").values_list("tag__name", flat=True))
    if not tags:
        return ""
    return tags[ContentItem.objects.filter(persona=persona).count() % len(tags)]


def draft_now(persona: Persona, *, topic: str = "", now: datetime | None = None
              ) -> tuple[ContentItem, bool]:
    """Nacrt na zahtev operatora (ADR-0012). Vraća (nacrt, poslat_na_odobrenje).

    Isti put kao rutina: memorija → model → provere → predlog → odobrenje.
    Ništa ne ide napolje bez odobrenja, a u SIMULATION samo na sandbox.
    """
    now = now or timezone.now()
    if persona.status not in MANUAL_STATUSES:
        raise ContentError("VALIDATION_ERROR",
                           f"Persona je {persona.status} — nacrt se pravi samo za READY/ACTIVE.")
    since = now - timedelta(days=1)
    manual = ContentItem.objects.filter(
        persona=persona, created_at__gte=since,
        run__reason_code=E.DecisionReason.OPERATOR_TASK.value).count()
    if manual >= MANUAL_DRAFTS_PER_DAY:
        raise ContentError("RATE_LIMITED",
                           f"Već {manual} ručnih nacrta u 24 h (najviše {MANUAL_DRAFTS_PER_DAY}).")
    topic = (topic or "").strip()[:200] or manual_topic(persona)
    if not topic:
        raise ContentError("VALIDATION_ERROR", "Upiši temu — persona nema niše.")
    item = draft(persona, topic=topic, now=now)
    if item.status != CS.DRAFT.value:
        return item, False
    account = publish_channel(persona)
    if account is None:
        return item, False
    submit(item, account, now=now)
    item.refresh_from_db()
    return item, True


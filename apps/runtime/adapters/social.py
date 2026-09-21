"""Adapteri društvenih mreža — isključivo zvanični API (Canon §12.1). ADR-0008.

Nijedan adapter ovde ne otvara pregledač. Lajk tuđe objave, follow, prvi DM
i komentar na tuđem sadržaju nemaju ActionType, jer nemaju sankcionisan put
(Aneks A §1 t.3). Šta tačno postoji po kanalu: `channels/platforms.yaml`.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import timedelta
from decimal import Decimal

from apps.orchestration.models import Action
from apps.runtime import config
from apps.runtime.adapters.base import (
    Adapter,
    CostItem,
    Exec,
    Outcome,
    has_link,
    text_of,
)
from apps.runtime.transport import Request
from common import enums as E
from common import ids as I

OC = E.ExecutionOutcome
R = E.RuntimeReason
POST, COMMENT, MODERATE, READ = ("channel.post.create", "channel.comment.create",
                                 "channel.comment.moderate", "channel.read.public")


def _need_account_id(x: Exec) -> Outcome | None:
    if not (x.account and x.account.provider_account_id):
        return Outcome(OC.NEEDS_HUMAN, R.TARGET_REQUIRED.value,
                       detail="Nalog nema provider_account_id (Page/IG/organizacija).")
    return None


def _need_target(x: Exec) -> Outcome | None:
    if x.action.action_type in (COMMENT, MODERATE) and not x.action.target_ref:
        return Outcome(OC.PERMANENT_ERROR, R.TARGET_REQUIRED.value,
                       detail="Odgovor i moderacija traže target_ref (ID komentara/objave).")
    return None


def _ok(x: Exec, ref: str | None, **result) -> Outcome:
    return Outcome(OC.SUCCEEDED, R.DRY_RUN.value if x.dry else "OK",
                   external_ref=None if x.dry else ref, result=result)


# ---------------------------------------------------------------- sandbox


class SandboxAdapter(Adapter):
    """Interna test platforma (pilot faza SIMULATION). Nema spoljnog sistema."""

    key = "sandbox"

    def perform(self, x: Exec) -> Outcome:
        x.token.check()
        ref = f"sandbox:{I.new_ulid()}"
        return Outcome(OC.SUCCEEDED, R.SANDBOX.value, external_ref=ref,
                       result={"sandbox": True, "text": text_of(x.payload)[:500]})

    def verify(self, x: Exec) -> E.ReconcileStatus:
        return E.ReconcileStatus.RESOLVED_NO_EFFECT


# ---------------------------------------------------------------- Meta


class _Meta(Adapter):
    host = "https://graph.facebook.com"

    def base(self) -> str:
        return f"{self.host}/{config.api_version('meta_graph')}"

    def preflight(self, x: Exec) -> Outcome | None:
        return _need_account_id(x) or _need_target(x)


class FacebookAdapter(_Meta):
    """Samo Page (Aneks A §2.2). Lični profil ne postoji kao vozilo."""

    key = "meta_facebook"

    def perform(self, x: Exec) -> Outcome:
        at, p, acc = x.action.action_type, x.payload, x.account
        if at == POST:
            form = {"message": text_of(p)}
            if p.get("link"):
                form["link"] = p["link"]
            r = x.send(Request("POST", f"{self.base()}/{acc.provider_account_id}/feed",
                               form=form, auth="bearer"))
            return _ok(x, (r.json or {}).get("id"))
        if at == COMMENT:
            r = x.send(Request("POST", f"{self.base()}/{x.action.target_ref}/comments",
                               form={"message": text_of(p)}, auth="bearer"))
            return _ok(x, (r.json or {}).get("id"))
        hide = bool(p.get("hide", True))
        x.send(Request("POST", f"{self.base()}/{x.action.target_ref}",
                       form={"is_hidden": "true" if hide else "false"}, auth="bearer"))
        return _ok(x, x.action.target_ref, hidden=hide)

    def verify(self, x: Exec) -> E.ReconcileStatus:
        if x.action.action_type != POST:
            return E.ReconcileStatus.UNRESOLVED
        r = x.send(Request("GET", f"{self.base()}/{x.account.provider_account_id}/feed"
                           "?fields=id,message&limit=25", auth="bearer", write=False))
        return _match((r.json or {}).get("data") or [], "message", text_of(x.payload), x)


class InstagramAdapter(_Meta):
    """Professional nalog, sa profilnom oznakom „AI generated profile" (Aneks A §2.1)."""

    key = "meta_instagram"
    host = "https://graph.instagram.com"

    def preflight(self, x: Exec) -> Outcome | None:
        pre = super().preflight(x)
        if pre:
            return pre
        p = x.payload
        if x.action.action_type == POST and not (p.get("image_url") or p.get("video_url")):
            return Outcome(OC.PERMANENT_ERROR, R.MEDIA_REQUIRED.value,
                           detail="Instagram nema objavu samo sa tekstom.")
        return None

    def perform(self, x: Exec) -> Outcome:
        at, p, ig = x.action.action_type, x.payload, x.account.provider_account_id
        if at == POST:
            media = {"caption": text_of(p)}
            if p.get("video_url"):
                media.update(media_type="REELS", video_url=p["video_url"])
            else:
                media["image_url"] = p["image_url"]
            c = x.send(Request("POST", f"{self.base()}/{ig}/media", form=media,
                               auth="bearer"))
            creation = (c.json or {}).get("id")
            r = x.send(Request("POST", f"{self.base()}/{ig}/media_publish",
                               form={"creation_id": creation}, auth="bearer"))
            return _ok(x, (r.json or {}).get("id"))
        if at == COMMENT:
            r = x.send(Request("POST", f"{self.base()}/{x.action.target_ref}/replies",
                               form={"message": text_of(p)}, auth="bearer"))
            return _ok(x, (r.json or {}).get("id"))
        hide = bool(p.get("hide", True))
        x.send(Request("POST", f"{self.base()}/{x.action.target_ref}",
                       form={"hide": "true" if hide else "false"}, auth="bearer"))
        return _ok(x, x.action.target_ref, hidden=hide)

    def verify(self, x: Exec) -> E.ReconcileStatus:
        if x.action.action_type != POST:
            return E.ReconcileStatus.UNRESOLVED
        r = x.send(Request("GET", f"{self.base()}/{x.account.provider_account_id}/media"
                           "?fields=id,caption&limit=25", auth="bearer", write=False))
        return _match((r.json or {}).get("data") or [], "caption", text_of(x.payload), x)


# ---------------------------------------------------------------- LinkedIn


class LinkedInAdapter(Adapter):
    """Samo Page sa imenovanim super-adminom (Canon §17.1, Aneks A §3.1)."""

    key = "linkedin"
    host = "https://api.linkedin.com/rest"

    def headers(self) -> dict[str, str]:
        return {"LinkedIn-Version": config.api_version("linkedin"),
                "X-Restli-Protocol-Version": "2.0.0"}

    def org(self, x: Exec) -> str:
        return f"urn:li:organization:{x.account.provider_account_id}"

    def preflight(self, x: Exec) -> Outcome | None:
        if not (x.account and x.account.named_human_admin.strip()):
            return Outcome(OC.NEEDS_HUMAN, R.NAMED_ADMIN_MISSING.value,
                           detail="LinkedIn Page traži imenovanog super-admina.")
        pre = _need_account_id(x) or _need_target(x)
        if pre:
            return pre
        if x.action.action_type == COMMENT:
            spec = config.action_spec("LINKEDIN", COMMENT) or {}
            gap = int(spec.get("min_interval_s", 60))
            recent = Action.objects.filter(
                channel_account=x.account, action_type=COMMENT,
                status__in=[E.ActionStatus.SUCCEEDED.value, E.ActionStatus.RUNNING.value],
                started_at__gte=x.now - timedelta(seconds=gap),
            ).exclude(pk=x.action.pk).exists()
            if recent:
                return Outcome(OC.RETRYABLE_ERROR, R.MIN_INTERVAL.value, retry_after_s=gap,
                               detail="LinkedIn: najviše 1 komentar u minuti po članu.")
        return None

    def perform(self, x: Exec) -> Outcome:
        at, p = x.action.action_type, x.payload
        if at == POST:
            body = {
                "author": self.org(x), "commentary": text_of(p), "visibility": "PUBLIC",
                "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [],
                                 "thirdPartyDistributionChannels": []},
                "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False,
            }
            r = x.send(Request("POST", f"{self.host}/posts", headers=self.headers(),
                               json=body, auth="bearer"))
            return _ok(x, r.headers.get("x-restli-id"))
        urn = x.action.target_ref
        enc = urn.replace(":", "%3A")
        if at == COMMENT:
            body = {"actor": self.org(x), "object": urn, "message": {"text": text_of(p)}}
            if p.get("parent_comment"):
                body["parentComment"] = p["parent_comment"]
            r = x.send(Request("POST", f"{self.host}/socialActions/{enc}/comments",
                               headers=self.headers(), json=body, auth="bearer"))
            return _ok(x, r.headers.get("x-restli-id") or (r.json or {}).get("id"))
        comment_id = p.get("comment_id")
        if not comment_id:
            return Outcome(OC.PERMANENT_ERROR, R.TARGET_REQUIRED.value,
                           detail="Brisanje komentara traži comment_id (skrivanje ne postoji).")
        actor = self.org(x).replace(":", "%3A")
        x.send(Request("DELETE", f"{self.host}/socialActions/{enc}/comments/{comment_id}"
                       f"?actor={actor}", headers=self.headers(), auth="bearer"))
        return _ok(x, str(comment_id), deleted=True)

    def verify(self, x: Exec) -> E.ReconcileStatus:
        if x.action.action_type != POST:
            return E.ReconcileStatus.UNRESOLVED
        author = self.org(x).replace(":", "%3A")
        r = x.send(Request("GET", f"{self.host}/posts?author={author}&q=author&count=20",
                           headers=self.headers(), auth="bearer", write=False))
        return _match((r.json or {}).get("elements") or [], "commentary",
                      text_of(x.payload), x)


# ---------------------------------------------------------------- X


class XAdapter(Adapter):
    """Pay-per-use API (Aneks A §2.4). Repetition guard je uslov pristupa."""

    key = "x"
    host = "https://api.x.com/2"

    def preflight(self, x: Exec) -> Outcome | None:
        pre = _need_target(x)
        if pre:
            return pre
        if x.action.action_type in (POST, COMMENT):
            hit = repetition_hit(x.action, x.now)
            if hit:
                return Outcome(OC.DENIED_BY_POLICY, R.REPETITION_GUARD.value,
                               detail=f"Previše slično akciji {hit} (X developer policy).")
        return None

    def _cost(self, x: Exec, at: str) -> list[CostItem]:
        spec = config.action_spec("X", at) or {}
        usd = Decimal(spec.get("cost_usd_with_link" if has_link(x.payload) else "cost_usd",
                               "0"))
        return [CostItem(E.CostBucket.X_API_CREDITS, "x", usd, unit="posts")]

    def perform(self, x: Exec) -> Outcome:
        at, p = x.action.action_type, x.payload
        if at == READ:
            q = str(p.get("query") or "")[:512]
            n = max(10, min(int(p.get("max_results", 10)), 100))
            from urllib.parse import quote

            r = x.send(Request("GET", f"{self.host}/tweets/search/recent?query={quote(q)}"
                               f"&max_results={n}", auth="bearer", write=False))
            data = (r.json or {}).get("data") or []
            per = Decimal((config.action_spec("X", READ) or {}).get("cost_usd_per_post", "0"))
            out = _ok(x, None, count=len(data), items=data[:n])
            out.costs = [CostItem(E.CostBucket.X_API_CREDITS, "x",
                                  per * Decimal(len(data) if not x.dry else n),
                                  Decimal(len(data) if not x.dry else n), "posts")]
            return out
        body = {"text": text_of(p)}
        if at == COMMENT:
            body["reply"] = {"in_reply_to_tweet_id": x.action.target_ref}
        r = x.send(Request("POST", f"{self.host}/tweets", json=body, auth="bearer"))
        out = _ok(x, ((r.json or {}).get("data") or {}).get("id"))
        out.costs = self._cost(x, at)
        return out

    def verify(self, x: Exec) -> E.ReconcileStatus:
        if not x.account or not x.account.provider_account_id:
            return E.ReconcileStatus.UNRESOLVED
        r = x.send(Request("GET", f"{self.host}/users/{x.account.provider_account_id}"
                           "/tweets?max_results=20", auth="bearer", write=False))
        return _match((r.json or {}).get("data") or [], "text", text_of(x.payload), x)


# ---------------------------------------------------------------- pomoćno


def _norm(text: str) -> list[str]:
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"https?://\S+", " ", t)
    return re.findall(r"[a-z0-9]+", t)


def _shingles(words: list[str], k: int = 3) -> set[tuple[str, ...]]:
    if len(words) < k:
        return {tuple(words)} if words else set()
    return {tuple(words[i:i + k]) for i in range(len(words) - k + 1)}


def similarity(a: str, b: str) -> float:
    sa, sb = _shingles(_norm(a)), _shingles(_norm(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def repetition_hit(action: Action, now) -> str | None:
    """Da li je ista ili bitno slična objava već otišla (ili ide) sa bilo kog X naloga."""
    guard = config.channel("X").get("repetition_guard") or {}
    threshold = float(guard.get("similarity_threshold", 0.8))
    since = now - timedelta(days=int(guard.get("window_days", 30)))
    text = text_of(action.input_json or {})
    others = Action.objects.filter(
        channel_account__channel_type=E.ChannelType.X.value,
        action_type__in=[POST, COMMENT], created_at__gte=since,
        status__in=[E.ActionStatus.SUCCEEDED.value, E.ActionStatus.RUNNING.value,
                    E.ActionStatus.QUEUED.value, E.ActionStatus.RETRY_WAIT.value],
    ).exclude(pk=action.pk).only("public_id", "input_json")
    for o in others:
        if similarity(text, text_of(o.input_json or {})) >= threshold:
            return o.public_id
    return None


def _match(items: list[dict], field: str, text: str, x: Exec) -> E.ReconcileStatus:
    if x.dry:
        return E.ReconcileStatus.RESOLVED_NO_EFFECT
    for it in items:
        if similarity(str(it.get(field) or ""), text) >= 0.95:
            return E.ReconcileStatus.RESOLVED_EFFECT_PRESENT
    return E.ReconcileStatus.RESOLVED_NO_EFFECT

"""Javni web i sopstveni sistemi. Canon §6.4, §12.6 · Aneks A §5 · ADR-0008.

`browser.page.read` — čitanje javne stranice, pošteno:
  - istinit User-Agent sa kontaktom (nikad lažni Chrome);
  - `robots.txt` se poštuje (keš 24 h), uključujući `Crawl-delay`;
  - najviše 1 zahtev u sekundi po hostu (za sve worker-e, preko keša);
  - uslovni GET (`If-None-Match` / `If-Modified-Since`);
  - 429/503 sa `Retry-After` → odustaje tačno koliko piše;
  - nikada prijava, nalog ni klik na „prihvatam" (Aneks A §5.1).

`browser.form.submit` — SAMO na domenima iz `BrowserProfile.allowed_domains`
(sopstveni ili odobreni sistemi). CAPTCHA ili izazov → NEEDS_HUMAN; sistem ga
ne rešava (Canon §9.4 t.4). Lozinke i tajne u polju forme se odbijaju.
"""

from __future__ import annotations

import re
import urllib.robotparser
from urllib.parse import urlsplit

from django.core.cache import cache

from apps.policy import config as policy_config
from apps.runtime.adapters.base import Adapter, Exec, HttpStatus, Outcome
from apps.runtime.transport import Request
from common import enums as E

OC = E.ExecutionOutcome
R = E.RuntimeReason
_SECRET_FIELD = re.compile(r"pass(word)?|lozinka|secret|token|api[_-]?key|otp|pin", re.I)
ROBOTS_TTL = 24 * 3600


def user_agent() -> str:
    spec = policy_config.capability("web.read_public") or {}
    return spec["required_constraints"]["user_agent_declared"]


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _domain_match(host: str, domains: list[str]) -> bool:
    return any(host == d.lower() or host.endswith("." + d.lower()) for d in domains)


class WebAdapter(Adapter):
    key = "web"

    def profile(self, x: Exec):
        return x.account.browser_profile if x.account else None

    def preflight(self, x: Exec) -> Outcome | None:
        url = str(x.payload.get("url") or "")
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return Outcome(OC.PERMANENT_ERROR, R.TARGET_REQUIRED.value, detail="Neispravan URL.")
        host, prof = parts.hostname.lower(), self.profile(x)
        if prof and _domain_match(host, prof.blocked_domains or []):
            return Outcome(OC.DENIED_BY_POLICY, R.DOMAIN_BLOCKED.value, detail=host)
        if x.action.action_type == "browser.form.submit":
            allowed = (prof.allowed_domains if prof else []) or []
            if not _domain_match(host, allowed):
                return Outcome(OC.DENIED_BY_POLICY, R.DOMAIN_NOT_ALLOWED.value,
                               detail="Forme samo na domenima iz allowed_domains profila.")
            for name in (x.payload.get("fields") or {}):
                if _SECRET_FIELD.search(str(name)):
                    return Outcome(OC.DENIED_BY_POLICY, "SECRET_IN_PAYLOAD",
                                   detail=f"Polje {name!r} ne sme nositi tajnu u payload-u.")
        elif prof and prof.allowed_domains and not _domain_match(host, prof.allowed_domains):
            return Outcome(OC.DENIED_BY_POLICY, R.DOMAIN_NOT_ALLOWED.value, detail=host)
        return None

    # ------------------------------------------------------------ host tempo
    def _pace(self, x: Exec, host: str, delay: float) -> Outcome | None:
        if x.dry:
            return None
        if not cache.add(f"web:pace:{host}", 1, timeout=max(1, int(delay + 0.999))):
            return Outcome(OC.RETRYABLE_ERROR, R.HOST_RATE.value,
                           retry_after_s=max(1, int(delay + 0.999)))
        return None

    def _robots(self, x: Exec, url: str) -> urllib.robotparser.RobotFileParser | None:
        parts = urlsplit(url)
        root = f"{parts.scheme}://{parts.netloc}"
        key = f"web:robots:{parts.netloc.lower()}"
        text = cache.get(key)
        if text is None:
            try:
                r = x.send(Request("GET", f"{root}/robots.txt", write=False,
                                   headers={"User-Agent": user_agent()}))
                text = "" if r.dry else r.text
            except HttpStatus as h:
                if h.resp.status in (401, 403):
                    text = "User-agent: *\nDisallow: /"   # RFC 9309 §2.3.1.3
                elif h.resp.status >= 500:
                    raise
                else:
                    text = ""                            # 4xx: nema pravila
            if not x.dry:
                cache.set(key, text, ROBOTS_TTL)
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(text.splitlines())
        return rp

    def perform(self, x: Exec) -> Outcome:
        url = str(x.payload["url"])
        host = _host(url)
        ua = user_agent()
        rp = self._robots(x, url)
        if not x.dry and not rp.can_fetch(ua, url):
            return Outcome(OC.BLOCKED_BY_PLATFORM, R.ROBOTS_DISALLOWED.value, detail=url)
        delay = max(1.0, float(rp.crawl_delay(ua) or 0))
        paced = self._pace(x, host, delay)
        if paced:
            return paced
        headers = {"User-Agent": ua, "Accept-Language": "sr-RS,sr;q=0.9,en;q=0.7"}
        if x.action.action_type == "browser.form.submit":
            r = x.send(Request("SUBMIT", url, headers=headers, kind="browser",
                               form=dict(x.payload.get("fields") or {}),
                               options={"submit_selector": x.payload.get("submit_selector",
                                                                          "[type=submit]")}))
            return Outcome(OC.SUCCEEDED, R.DRY_RUN.value if x.dry else "OK",
                           external_ref=None if x.dry else url,
                           evidence_level=E.EvidenceLevel.SCREENSHOT_AND_DOM,
                           result={"final_url": (r.json or {}).get("final_url")})
        meta = cache.get(f"web:etag:{url}") or {}
        if meta.get("etag"):
            headers["If-None-Match"] = meta["etag"]
        if meta.get("last_modified"):
            headers["If-Modified-Since"] = meta["last_modified"]
        kind = "browser" if x.payload.get("render") else "http"
        r = x.send(Request("GET", url, headers=headers, kind=kind, write=False))
        if x.dry:
            return Outcome(OC.SUCCEEDED, R.DRY_RUN.value, result={"url": url})
        if r.status == 304:
            return Outcome(OC.SUCCEEDED, "NOT_MODIFIED", result={"url": url, "status": 304})
        new_meta = {k: r.headers[h] for k, h in (("etag", "etag"),
                                                  ("last_modified", "last-modified"))
                    if r.headers.get(h)}
        if new_meta:
            cache.set(f"web:etag:{url}", new_meta, 7 * 24 * 3600)
        text = r.text or ""
        title = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
        return Outcome(OC.SUCCEEDED, "OK", external_ref=url,
                       result={"url": url, "status": r.status,
                               "title": title.group(1).strip()[:300] if title else None,
                               "bytes": len(text), "excerpt": text[:20_000]})

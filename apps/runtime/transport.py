"""Transport — jedino mesto gde bajt može da ode van sistema. ADR-0008.

Adapter nikad ne otvara mrežu sam. On sastavi `Request` i preda ga
transportu. Postoje dve vrste transporta:

  - `DryRunTransport` — beleži šta BI bilo poslato i ne šalje ništa.
    Koristi se kad god izvršni ugovor ima `dry_run=True`, a do GO odluke
    to je svaki ugovor.
  - `LiveTransport` — šalje. Proverava prekidač DRUGI PUT, nezavisno od
    gateway-a: ako je `GLOBAL_EXTERNAL_ACTIONS_ENABLED=false`, odbija da
    pošalje i kada bi mu neko greškom predao ugovor bez `dry_run`.

Tajna se čita tek u `LiveTransport.send()`, iz `credential_ref`
(`env:IME` ili `file:/putanja`). U `Request`-u, u bazi i u evidenciji
stoji samo referenca — nikada vrednost (Canon §2, §17).
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from django.conf import settings

REDACTED = "‹credential_ref›"


class TransportError(Exception):
    """Mreža nije odgovorila — ne znamo da li je zahtev stigao."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}")
        self.reason, self.detail = reason, detail


class ExternalActionsDisabled(RuntimeError):
    """Druga brava: globalni prekidač je isključen."""


class CredentialMissing(RuntimeError):
    pass


@dataclass
class Request:
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    json: Any = None
    form: dict[str, Any] | None = None
    body: str | None = None
    kind: str = "http"          # http | smtp | browser
    write: bool = True          # da li zahtev menja stanje na drugoj strani
    auth: str | None = None     # "bearer" → tajna se ubacuje u LiveTransport-u
    options: dict[str, Any] = field(default_factory=dict)

    def redacted(self) -> dict[str, Any]:
        """Oblik za evidenciju i za prikaz operatoru. Bez tajni."""
        headers = dict(self.headers)
        if self.auth:
            headers["Authorization"] = f"Bearer {REDACTED}"
        out: dict[str, Any] = {"kind": self.kind, "method": self.method, "url": self.url,
                               "headers": headers, "write": self.write}
        for k in ("json", "form"):
            if getattr(self, k) is not None:
                out[k] = getattr(self, k)
        if self.body is not None:
            out["body"] = self.body if len(self.body) <= 20_000 else self.body[:20_000] + "…"
        if self.options:
            out["options"] = self.options
        return out


@dataclass
class Response:
    status: int
    json: Any = None
    text: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    dry: bool = False


class Transport(Protocol):
    live: bool

    def send(self, req: Request, *, credential_ref: str = "") -> Response: ...


class DryRunTransport:
    """Ne šalje ništa. Vraća odgovor koji adapteru dozvoljava da nastavi tok."""

    live = False

    def __init__(self) -> None:
        self.sent: list[Request] = []

    def send(self, req: Request, *, credential_ref: str = "") -> Response:
        self.sent.append(req)
        return Response(status=200, json={"id": "dry-run", "dry_run": True},
                        headers={"x-restli-id": "dry-run"}, dry=True)


def resolve_secret(credential_ref: str) -> str:
    """`env:IME` ili `file:/putanja`. Sve ostalo (npr. `vault:`) nije podržano u F6."""
    scheme, _, ref = credential_ref.partition(":")
    if scheme == "env" and ref:
        value = os.environ.get(ref, "")
    elif scheme == "file" and ref:
        try:
            with open(ref, encoding="utf-8") as fh:
                value = fh.read().strip()
        except OSError:
            value = ""
    else:
        value = ""
    if not value:
        raise CredentialMissing(f"tajna za {scheme}:… nije dostupna")
    return value


def _guard() -> None:
    if not getattr(settings, "GLOBAL_EXTERNAL_ACTIONS_ENABLED", False):
        raise ExternalActionsDisabled("GLOBAL_EXTERNAL_ACTIONS_ENABLED=false")


class LiveTransport:
    live = True

    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout
        self.sent: list[Request] = []

    def send(self, req: Request, *, credential_ref: str = "") -> Response:
        _guard()
        self.sent.append(req)
        if req.kind == "smtp":
            return self._smtp(req, credential_ref)
        if req.kind == "browser":
            return self._browser(req)
        return self._http(req, credential_ref)

    # ------------------------------------------------------------ http
    def _http(self, req: Request, credential_ref: str) -> Response:
        headers = dict(req.headers)
        data = None
        if req.auth == "bearer":
            headers["Authorization"] = f"Bearer {resolve_secret(credential_ref)}"
        if req.json is not None:
            data = json.dumps(req.json).encode()
            headers.setdefault("Content-Type", "application/json")
        elif req.form is not None:
            data = urllib.parse.urlencode(req.form).encode()
            headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        r = urllib.request.Request(req.url, data=data, method=req.method, headers=headers)
        try:
            with urllib.request.urlopen(r, timeout=self.timeout) as resp:  # noqa: S310
                return _response(resp.status, resp.read(), dict(resp.headers))
        except urllib.error.HTTPError as e:
            return _response(e.code, e.read() or b"", dict(e.headers or {}))
        except TimeoutError as e:
            raise TransportError("TIMEOUT", str(e)) from e
        except (urllib.error.URLError, OSError) as e:
            raise TransportError("NETWORK", str(e)) from e

    # ------------------------------------------------------------ smtp
    def _smtp(self, req: Request, credential_ref: str) -> Response:
        """credential_ref pokazuje na JSON: {host, port, username, password}."""
        cfg = json.loads(resolve_secret(credential_ref))
        try:
            with smtplib.SMTP(cfg["host"], int(cfg.get("port", 587)),
                              timeout=self.timeout) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(cfg["username"], cfg["password"])
                refused = s.sendmail(req.headers["From"], [req.headers["To"]],
                                     (req.body or "").encode())
        except smtplib.SMTPAuthenticationError as e:
            return Response(status=401, text=str(e))
        except smtplib.SMTPRecipientsRefused as e:
            return Response(status=550, text=str(e))
        except (smtplib.SMTPServerDisconnected, TimeoutError, OSError) as e:
            raise TransportError("NETWORK", str(e)) from e
        return Response(status=250 if not refused else 550, json={"refused": list(refused)})

    # ------------------------------------------------------------ browser
    def _browser(self, req: Request) -> Response:  # pragma: no cover — traži Chromium
        """Playwright + Chromium, bez stealth-a (Canon §12.1).

        Istinit User-Agent, `Accept-Language`, bez prikrivanja
        `navigator.webdriver`. CAPTCHA ili izazov → NEEDS_HUMAN, nikad rešavanje.
        """
        from playwright.sync_api import sync_playwright

        opts = req.options
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(user_agent=req.headers.get("User-Agent"),
                                          locale=opts.get("locale", "sr-RS"),
                                          extra_http_headers={
                                              k: v for k, v in req.headers.items()
                                              if k != "User-Agent"})
                page = ctx.new_page()
                resp = page.goto(req.url, timeout=self.timeout * 1000,
                                 wait_until="domcontentloaded")
                if _challenge(page):
                    return Response(status=403, text="CHALLENGE", json={"challenge": True})
                if req.method == "SUBMIT":
                    for name, value in (req.form or {}).items():
                        page.fill(f"[name='{name}']", str(value))
                    page.click(opts.get("submit_selector", "[type=submit]"))
                    page.wait_for_load_state("domcontentloaded")
                    if _challenge(page):
                        return Response(status=403, text="CHALLENGE", json={"challenge": True})
                return Response(status=resp.status if resp else 0, text=page.content(),
                                json={"title": page.title(), "final_url": page.url})
            finally:
                browser.close()


def _challenge(page) -> bool:  # pragma: no cover
    """Prepoznaje CAPTCHA/izazov. Sistem ga NIKAD ne rešava (Canon §9.4 t.4)."""
    return bool(page.query_selector(
        "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], iframe[src*='turnstile'], "
        "#challenge-form, .cf-challenge, [data-sitekey]"))


def _response(status: int, raw: bytes, headers: dict[str, str]) -> Response:
    text = raw.decode("utf-8", errors="replace")
    try:
        body = json.loads(text) if text else None
    except ValueError:
        body = None
    return Response(status=status, json=body, text=text,
                    headers={k.lower(): v for k, v in headers.items()})


def for_contract(contract: dict[str, Any]) -> Transport:
    return DryRunTransport() if contract.get("dry_run", True) else LiveTransport()

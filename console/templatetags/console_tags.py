from django import template

register = template.Library()


@register.filter
def eur(cents) -> str:
    c = int(cents or 0)
    return f"{c // 100:,}".replace(",", ".") + f",{c % 100:02d} €"


@register.filter
def iso(dt) -> str:
    return dt.isoformat() if dt else ""


@register.filter
def get(d, key):
    return (d or {}).get(key, 0)


@register.filter
def status_tone(value) -> str:
    v = str(value or "").upper()
    if v in {"SUCCEEDED", "PUBLISHED", "APPROVED", "APPROVED_WITH_CHANGES", "ACT", "ALLOW",
             "ACTIVE", "READY", "RESOLVED"}:
        return "ok"
    if v in {"BLOCKED", "FAILED", "REJECTED", "DENY", "SUSPENDED", "SEV1", "SEV2", "EXPIRED"}:
        return "bad"
    if v in {"APPROVAL_PENDING", "PENDING", "IN_REVIEW", "RUNNING", "RETRY_WAIT", "QUEUED",
             "REQUIRE_APPROVAL", "THROTTLE", "SEV3", "DEFER", "OPEN", "DRAFT", "SCHEDULED"}:
        return "warn"
    return "muted"

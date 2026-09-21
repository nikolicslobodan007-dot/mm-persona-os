"""Kanonski katalog enum-a — MM Persona OS Canon v1.1, §3.

JEDINO mesto na kome se enum sme definisati. Vrednost koja ne postoji ovde
ne postoji u sistemu (Canon §3, §20 tačka 3).

Modul je namerno bez Django zavisnosti: uvozi se iz testova, iz workera i iz
lint alata jednako. Django modeli koriste `.choices()`.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "CanonEnum",
    "PersonaStatus",
    "RuntimeEnvironment",
    "PersonaType",
    "DisclosureMode",
    "PolicyEffect",
    "RiskClass",
    "Zone",
    "ActionStatus",
    "ExecutionOutcome",
    "ApprovalStatus",
    "ApprovalClass",
    "TrustLevel",
    "MemoryType",
    "MemoryStatus",
    "Provenance",
    "IdentityVehicle",
    "ChannelType",
    "DisclosureLabelStatus",
    "JobStatus",
    "AuditSeverity",
    "IncidentSeverity",
    "WakePriority",
    "BreakerState",
    "AuthState",
    "EvidenceLevel",
    "CostBucket",
    "Role",
    "KillSwitchScope",
    "ErrorCode",
    "QueueName",
    "OUTCOME_TO_STATUS",
    "EFFECT_TO_ZONE",
    "RISK_BANDS",
    "risk_class_for",
]


class CanonEnum(StrEnum):
    """Zajednička baza. `.choices()` daje Django `choices` bez uvoza Django-a."""

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        return [(m.value, m.value) for m in cls]

    @classmethod
    def values(cls) -> list[str]:
        return [m.value for m in cls]


# ---------------------------------------------------------------- §3.1–3.4


class PersonaStatus(CanonEnum):
    """Canon §3.1. Ukinuto: pilotski status → RuntimeEnvironment, `retired` → ARCHIVED."""

    DRAFT = "DRAFT"
    READY = "READY"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"          # operator; automatika na 120% budžeta (§13.3)
    DEGRADED = "DEGRADED"      # automatika, posle incidenta
    SUSPENDED = "SUSPENDED"    # Trust & Safety; automatika kod §9.4
    ARCHIVED = "ARCHIVED"


class RuntimeEnvironment(CanonEnum):
    """Canon §3.2. Ortogonalno statusu — persona može biti ACTIVE u SIMULATION."""

    SIMULATION = "SIMULATION"
    SHADOW = "SHADOW"
    CONTROLLED_LIVE = "CONTROLLED_LIVE"
    LIVE = "LIVE"


class PersonaType(CanonEnum):
    """Canon §3.3."""

    AI_CREATOR = "AI_CREATOR"
    AI_EXPERT = "AI_EXPERT"
    BRAND_AGENT = "BRAND_AGENT"
    ASSISTANT = "ASSISTANT"
    SIMULATION_ONLY = "SIMULATION_ONLY"


class DisclosureMode(CanonEnum):
    """Canon §3.4. Ne postoji vrednost koja skriva AI prirodu (§9.4)."""

    ALWAYS_VISIBLE = "ALWAYS_VISIBLE"
    PROFILE_ONLY = "PROFILE_ONLY"
    ON_REQUEST = "ON_REQUEST"


#: Tipovi persone kojima je `disclosure_required` uvek True (Canon §3.4).
DISCLOSURE_ALWAYS_REQUIRED: frozenset[PersonaType] = frozenset(
    {PersonaType.AI_CREATOR, PersonaType.AI_EXPERT, PersonaType.BRAND_AGENT}
)


# ---------------------------------------------------------------- §3.5–3.7


class PolicyEffect(CanonEnum):
    """Canon §3.5. Ukinuto: `RATE_LIMIT` (→ THROTTLE)."""  # canon-lint: allow

    ALLOW = "ALLOW"
    THROTTLE = "THROTTLE"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    DENY = "DENY"


class RiskClass(CanonEnum):
    """Canon §3.6. Svojstvo ZAHTEVA, ne odluke."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Zone(CanonEnum):
    """Canon §3.7. IZVEDENA oznaka — nikada se ne upisuje u bazu."""

    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


#: Canon §3.6 — `risk_score` je ceo broj 0–100, nikada decimala 0–1.
RISK_BANDS: tuple[tuple[int, int, RiskClass], ...] = (
    (0, 24, RiskClass.LOW),
    (25, 49, RiskClass.MEDIUM),
    (50, 74, RiskClass.HIGH),
    (75, 100, RiskClass.CRITICAL),
)


def risk_class_for(risk_score: int) -> RiskClass:
    """Canon §3.6. Prihvata samo ceo broj u opsegu 0–100."""
    if not isinstance(risk_score, int) or isinstance(risk_score, bool):
        raise TypeError(f"risk_score mora biti int, dobijeno {type(risk_score).__name__}")
    if not 0 <= risk_score <= 100:
        raise ValueError(f"risk_score van opsega 0-100: {risk_score}")
    for low, high, klass in RISK_BANDS:
        if low <= risk_score <= high:
            return klass
    raise AssertionError("nedostižno — opsezi pokrivaju 0-100")


#: Canon §3.7 — zona se izvodi iz ODLUKE, ne iz skora.
EFFECT_TO_ZONE: dict[PolicyEffect, Zone] = {
    PolicyEffect.ALLOW: Zone.GREEN,
    PolicyEffect.THROTTLE: Zone.GREEN,
    PolicyEffect.REQUIRE_APPROVAL: Zone.YELLOW,
    PolicyEffect.DENY: Zone.RED,
}


# ---------------------------------------------------------------- §3.8–3.9


class ActionStatus(CanonEnum):
    """Canon §3.8 — lifecycle akcije. Odvojeno od ishoda pokušaja (§3.9)."""

    PROPOSED = "PROPOSED"
    POLICY_CHECK = "POLICY_CHECK"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


#: Terminalna stanja — iz njih nema prelaza.
TERMINAL_ACTION_STATUSES: frozenset[ActionStatus] = frozenset(
    {
        ActionStatus.SUCCEEDED,
        ActionStatus.FAILED,
        ActionStatus.BLOCKED,
        ActionStatus.CANCELLED,
        ActionStatus.EXPIRED,
    }
)


class ExecutionOutcome(CanonEnum):
    """Canon §3.9 — ishod JEDNOG pokušaja. Živi na `ActionAttempt`."""

    SUCCEEDED = "SUCCEEDED"
    RETRYABLE_ERROR = "RETRYABLE_ERROR"
    PERMANENT_ERROR = "PERMANENT_ERROR"
    DENIED_BY_POLICY = "DENIED_BY_POLICY"
    BLOCKED_BY_PLATFORM = "BLOCKED_BY_PLATFORM"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    PLATFORM_POLICY_REQUIRES_HUMAN = "PLATFORM_POLICY_REQUIRES_HUMAN"  # v1.1, A-04
    DISCLOSURE_MISSING = "DISCLOSURE_MISSING"                          # v1.1, A-04
    NEEDS_AUTH = "NEEDS_AUTH"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    ABORTED_SAFE = "ABORTED_SAFE"
    UNKNOWN_EFFECT = "UNKNOWN_EFFECT"


#: Canon §3.9 — mapa prelaza. `None` znači "ostaje RUNNING, ide u reconcile".
#: UNKNOWN_EFFECT NIKADA ne vodi direktno u retry (§12.3).
OUTCOME_TO_STATUS: dict[ExecutionOutcome, ActionStatus | None] = {
    ExecutionOutcome.SUCCEEDED: ActionStatus.SUCCEEDED,
    ExecutionOutcome.RETRYABLE_ERROR: ActionStatus.RETRY_WAIT,
    ExecutionOutcome.PERMANENT_ERROR: ActionStatus.FAILED,
    ExecutionOutcome.DENIED_BY_POLICY: ActionStatus.BLOCKED,
    ExecutionOutcome.BLOCKED_BY_PLATFORM: ActionStatus.BLOCKED,
    ExecutionOutcome.CAPABILITY_UNAVAILABLE: ActionStatus.CANCELLED,
    ExecutionOutcome.PLATFORM_POLICY_REQUIRES_HUMAN: ActionStatus.CANCELLED,
    ExecutionOutcome.DISCLOSURE_MISSING: ActionStatus.BLOCKED,
    ExecutionOutcome.NEEDS_AUTH: ActionStatus.BLOCKED,
    ExecutionOutcome.NEEDS_HUMAN: ActionStatus.BLOCKED,
    ExecutionOutcome.ABORTED_SAFE: ActionStatus.RETRY_WAIT,
    ExecutionOutcome.UNKNOWN_EFFECT: None,
}

#: Razlozi koji prate ishod u `reason_code` (Canon §3.9).
OUTCOME_REASON_CODE: dict[ExecutionOutcome, str] = {
    ExecutionOutcome.CAPABILITY_UNAVAILABLE: "UNSUPPORTED",
    ExecutionOutcome.PLATFORM_POLICY_REQUIRES_HUMAN: "HUMAN_CONSENT_REQUIRED",
    ExecutionOutcome.DISCLOSURE_MISSING: "AI_LABEL_NOT_SET",
}


# ---------------------------------------------------------------- §3.10–3.11


class ApprovalStatus(CanonEnum):
    """Canon §3.10."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    APPROVED_WITH_CHANGES = "APPROVED_WITH_CHANGES"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    REVOKED = "REVOKED"


class ApprovalClass(CanonEnum):
    """Canon §15.2. TTL i efekat isteka u `APPROVAL_TTL_MINUTES`."""

    A1 = "A1"  # prvi odlazni email po adresatu
    A2 = "A2"  # javna objava
    A3 = "A3"  # izmena identiteta, capability, kampanja
    A4 = "A4"  # akcije vezane za incident


APPROVAL_TTL_MINUTES: dict[ApprovalClass, int] = {
    ApprovalClass.A1: 240,
    ApprovalClass.A2: 120,
    ApprovalClass.A3: 1440,
    ApprovalClass.A4: 30,
}

APPROVAL_EXPIRY_EFFECT: dict[ApprovalClass, str] = {
    ApprovalClass.A1: "DRAFT_KEPT_ACTION_CANCELLED",
    ApprovalClass.A2: "NO_ACTION",
    ApprovalClass.A3: "DENY",
    ApprovalClass.A4: "DENY_AND_ESCALATE",
}


class TrustLevel(CanonEnum):
    """Canon §3.11. L3 i L4 su REZERVISANI — vidi `ASSIGNABLE_TRUST_LEVELS`."""

    L0 = "L0"  # Simulation
    L1 = "L1"  # Controlled Publish
    L2 = "L2"  # Limited Interaction
    L3 = "L3"  # Outbound with Approval — rezervisan
    L4 = "L4"  # Mature Autonomy — rezervisan


#: Canon §3.11 (v1.1, A-08). L3/L4 nemaju kanal na kom se izvršavaju —
#: Aneks A je utvrdio da odlazni prvi kontakt ne postoji kao sankcionisan put.
#: Dodela se otključava tek ADR-om koji imenuje taj kanal.
ASSIGNABLE_TRUST_LEVELS: frozenset[TrustLevel] = frozenset(
    {TrustLevel.L0, TrustLevel.L1, TrustLevel.L2}
)

#: Isti skup, ali UREĐEN. Django `makemigrations` upisuje sadržaj liste u
#: migraciju; frozenset ima nedeterministički redosled, pa bi svaki `check`
#: prijavljivao lažnu izmenu ograničenja. Ograničenja koriste ovu torku.
ASSIGNABLE_TRUST_LEVEL_VALUES: tuple[str, ...] = tuple(
    sorted(t.value for t in ASSIGNABLE_TRUST_LEVELS)
)


# ---------------------------------------------------------------- §3.12–3.13


class MemoryType(CanonEnum):
    """Canon §3.12. Mala slova — koriste se kao ključevi decay konfiguracije."""

    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    SOCIAL = "social"      # bivši RELATIONSHIP
    CONTENT = "content"


class MemoryStatus(CanonEnum):
    """Canon §3.13."""

    PINNED = "PINNED"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    SUPERSEDED = "SUPERSEDED"
    DELETED = "DELETED"


class Provenance(CanonEnum):
    """Canon §10.4 — anti-konfabulacija. `INFERRED` nikada ne ide u javni izlaz."""

    OBSERVED = "observed"
    USER_PROVIDED = "user_provided"
    GENERATED = "generated"
    INFERRED = "inferred"


#: Canon §10.3 — poluživot u danima po tipu memorije. PINNED ne podleže decay-u.
MEMORY_HALF_LIFE_DAYS: dict[MemoryType, float | None] = {
    MemoryType.WORKING: 0.5,
    MemoryType.EPISODIC: 30.0,
    MemoryType.SOCIAL: 90.0,
    MemoryType.CONTENT: 180.0,
    MemoryType.SEMANTIC: 365.0,
    MemoryType.PROCEDURAL: None,  # bez decay-a
}

#: Canon §10.4 — confidence po izvoru.
SOURCE_CONFIDENCE: dict[str, tuple[float, float]] = {
    "system_observation": (0.95, 0.95),
    "first_party_user_input": (0.90, 0.90),
    "public_web_source": (0.60, 0.85),
    "llm_inference": (0.25, 0.55),
    "synthetic_world_event": (1.00, 1.00),
}


# ---------------------------------------------------------------- §3.14–3.16


class IdentityVehicle(CanonEnum):
    """Canon §3.14 (v1.1, A-01).

    U kom obliku persona postoji na kanalu. Nije stilsko pitanje nego uslov
    pristupa: LinkedIn i Facebook dozvoljavaju samo PAGE.
    Dozvoljeni parovi su u `channels/identity_vehicles.yaml`.
    """

    OWNED_SITE = "OWNED_SITE"
    NEWSLETTER = "NEWSLETTER"
    PAGE = "PAGE"
    PROFILE = "PROFILE"
    CHANNEL = "CHANNEL"
    SANDBOX = "SANDBOX"


class ChannelType(CanonEnum):
    """Canon §3.15. Email je ChannelType.EMAIL — zaseban model za email ne postoji."""

    WEBSITE = "WEBSITE"
    NEWSLETTER = "NEWSLETTER"
    EMAIL = "EMAIL"
    LINKEDIN = "LINKEDIN"
    INSTAGRAM = "INSTAGRAM"
    FACEBOOK = "FACEBOOK"
    X = "X"
    TIKTOK = "TIKTOK"
    YOUTUBE = "YOUTUBE"
    SANDBOX = "SANDBOX"


#: Canon §16.2 (v1.1, A-10) — kanali van opsega pilota i van F6.
#: Adapteri se ne pišu: TikTok zabranjuje bulk naloge, YouTube traži
#: izričit ljudski pristanak po radnji.
OUT_OF_SCOPE_CHANNELS: frozenset[ChannelType] = frozenset(
    {ChannelType.TIKTOK, ChannelType.YOUTUBE}
)

#: Uređena varijanta za DB ograničenja — vidi ASSIGNABLE_TRUST_LEVEL_VALUES.
OUT_OF_SCOPE_CHANNEL_VALUES: tuple[str, ...] = tuple(
    sorted(c.value for c in OUT_OF_SCOPE_CHANNELS)
)


class DisclosureLabelStatus(CanonEnum):
    """Canon §3.16 (v1.1, A-02).

    Kanal čiji status nije SET ili NOT_REQUIRED ne može u CONTROLLED_LIVE
    niti izvršiti ijednu `channel.*` akciju.
    """

    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED_NOT_SET = "REQUIRED_NOT_SET"
    SET = "SET"
    SET_UNVERIFIED = "SET_UNVERIFIED"
    REVOKED = "REVOKED"


#: Statusi oznake koji dozvoljavaju izvršenje (Canon §3.16).
DISCLOSURE_OK: frozenset[DisclosureLabelStatus] = frozenset(
    {DisclosureLabelStatus.SET, DisclosureLabelStatus.NOT_REQUIRED}
)


# ---------------------------------------------------------------- §3.17–3.19


class JobStatus(CanonEnum):
    """Canon §3.17."""

    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    RETRY = "RETRY"
    FAILED = "FAILED"
    DEAD = "DEAD"


class AuditSeverity(CanonEnum):
    """Canon §3.18."""

    INFO = "INFO"
    NOTICE = "NOTICE"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class IncidentSeverity(CanonEnum):
    """Canon §3.19."""

    SEV1 = "SEV1"
    SEV2 = "SEV2"
    SEV3 = "SEV3"
    SEV4 = "SEV4"


# ---------------------------------------- pomoćni enum-i (Canon §3, uvod v1.1)


class WakePriority(CanonEnum):
    """Canon §11.2. Brojčane vrednosti u `WAKE_PRIORITY_VALUE`."""

    OPERATOR_TASK = "OPERATOR_TASK"
    APPROVAL_DECISION = "APPROVAL_DECISION"
    INBOUND_HIGH = "INBOUND_HIGH"
    GOAL_DEADLINE = "GOAL_DEADLINE"
    WORLD_EVENT_HIGH = "WORLD_EVENT_HIGH"
    ROUTINE_WINDOW = "ROUTINE_WINDOW"
    MAINTENANCE = "MAINTENANCE"


WAKE_PRIORITY_VALUE: dict[WakePriority, int] = {
    WakePriority.OPERATOR_TASK: 100,
    WakePriority.APPROVAL_DECISION: 90,
    WakePriority.INBOUND_HIGH: 80,
    WakePriority.GOAL_DEADLINE: 75,
    WakePriority.WORLD_EVENT_HIGH: 60,
    WakePriority.ROUTINE_WINDOW: 40,
    WakePriority.MAINTENANCE: 20,
}


class BreakerState(CanonEnum):
    """Canon §12.5."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class AuthState(CanonEnum):
    """Canon §12.7."""

    UNKNOWN = "UNKNOWN"
    VALID = "VALID"
    EXPIRED = "EXPIRED"
    LOCKED = "LOCKED"
    NEEDS_HUMAN = "NEEDS_HUMAN"


class EvidenceLevel(CanonEnum):
    """Canon §12.6."""

    NONE = "NONE"
    RESPONSE_ONLY = "RESPONSE_ONLY"
    SCREENSHOT = "SCREENSHOT"
    SCREENSHOT_AND_DOM = "SCREENSHOT_AND_DOM"


class CostBucket(CanonEnum):
    """Canon §13.2. `x_api_credits` dodat u v1.1 (A-07) — X naplaćuje po objavi."""

    LLM = "llm"
    EMBEDDINGS = "embeddings"
    MEDIA_GENERATION = "media_generation"
    BROWSER_MINUTES = "browser_minutes"
    STORAGE = "storage"
    EGRESS = "egress"
    X_API_CREDITS = "x_api_credits"
    THIRD_PARTY_API = "third_party_api"


class Role(CanonEnum):
    """Canon §15.1. `reviewer` nije uloga nego dozvola `approvals.decide`."""

    VIEWER = "viewer"
    OPERATOR = "operator"
    PERSONA_MANAGER = "persona_manager"
    TRUST_SAFETY = "trust_safety"
    RUNTIME_ADMIN = "runtime_admin"
    SYSTEM_ADMIN = "system_admin"


#: Canon §15.1 — ko sme da odlučuje o odobrenjima.
APPROVAL_DECIDERS: frozenset[Role] = frozenset(
    {Role.OPERATOR, Role.PERSONA_MANAGER, Role.TRUST_SAFETY}
)


class KillSwitchScope(CanonEnum):
    """Canon §9.6. Globalni stop mora zaustaviti sve za < 30 s."""

    GLOBAL = "GLOBAL"
    CHANNEL = "CHANNEL"
    PERSONA = "PERSONA"
    CAPABILITY = "CAPABILITY"
    ACCOUNT = "ACCOUNT"


class ErrorCode(CanonEnum):
    """Canon §8.5. `RATE_LIMITED` je HTTP odgovor, ne policy efekat `THROTTLE`."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    RATE_LIMITED = "RATE_LIMITED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


ERROR_HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: 400,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.VERSION_CONFLICT: 409,
    ErrorCode.IDEMPOTENCY_CONFLICT: 409,
    ErrorCode.POLICY_BLOCKED: 422,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.PROVIDER_UNAVAILABLE: 502,
    ErrorCode.INTERNAL_ERROR: 500,
}


class QueueName(CanonEnum):
    """Canon §11.3 — deset queue-ova i ni jedan više. `dead_letter` se ne broji."""

    CONTROL = "control"
    APPROVAL = "approval"
    PERSONA_INTERACTIVE = "persona.interactive"
    PERSONA_SCHEDULED = "persona.scheduled"
    BROWSER = "browser"
    MAIL = "mail"
    CHANNEL = "channel"
    MEMORY = "memory"
    MEDIA = "media"
    MAINTENANCE = "maintenance"
    DEAD_LETTER = "dead_letter"


# ============================================================================
# Radni enum-i (F1) — NISU iz Canon §3
# ============================================================================
#
# Canon §3 normira 24 enum-a; sve iznad ove linije je taj katalog. Ispod su
# vrednosti koje Canon ne pominje, a šema ih traži kao `CharField` sa
# nabrajanjem u koloni „Pravilo / relacija" (npr. `open/selected/rejected/used`).
#
# Žive ovde, a ne u modelima, iz jednog razloga: Canon §20 tačka 3 kaže da
# enum van `common/enums.py` ne postoji, i `tools/canon_lint.py` to sprovodi.
# Alternativa — `TextChoices` u svakom app-u — vratila bi tačno onu raspršenost
# imena koju Canon uklanja.
#
# Pravilo za buduće izmene: vrednost odavde koja uđe u ugovor, u event payload
# ili u policy DSL prestaje da bude radna i seli se gore, kroz ADR.


class ScopeKind(CanonEnum):
    """Domet pravila ili događaja (šema §15, §14)."""

    GLOBAL = "global"
    CHANNEL = "channel"
    PERSONA = "persona"
    ACTION = "action"
    COHORT = "cohort"
    CAPABILITY = "capability"
    ACCOUNT = "account"


class AssetKind(CanonEnum):
    """Vrsta medijskog fajla (šema §8).

    `FACE_REFERENCE` postoji da bi Canon §9.4 tačka 7 imala šta da čuva:
    referentno lice je SINTETIČKO i nikada ne sme poticati od stvarne osobe.
    """

    AVATAR = "AVATAR"
    FACE_REFERENCE = "FACE_REFERENCE"
    PHOTO = "PHOTO"
    VIDEO = "VIDEO"
    AUDIO = "AUDIO"
    DOCUMENT = "DOCUMENT"
    THUMBNAIL = "THUMBNAIL"


class AssetRole(CanonEnum):
    """Uloga asset-a unutar jednog komada sadržaja (šema §12)."""

    COVER = "cover"
    INLINE = "inline"
    GALLERY = "gallery"
    VIDEO = "video"
    AUDIO = "audio"


class ActorKind(CanonEnum):
    """Vrsta učesnika u društvenom grafu (šema §11)."""

    PERSONA = "PERSONA"
    REAL_CONTACT = "REAL_CONTACT"
    ORGANIZATION = "ORGANIZATION"
    PUBLIC_ENTITY = "PUBLIC_ENTITY"


class RelationshipType(CanonEnum):
    """Vrsta odnosa. `FOLLOW` kao akcija ne postoji (Canon §9.3)."""

    FOLLOWS = "FOLLOWS"
    KNOWS = "KNOWS"
    COLLABORATES = "COLLABORATES"
    CUSTOMER = "CUSTOMER"
    PROSPECT = "PROSPECT"
    COLLEAGUE = "COLLEAGUE"
    FRIENDLY = "FRIENDLY"
    BLOCKED = "BLOCKED"


class RelationshipStatus(CanonEnum):
    ACTIVE = "active"
    MUTED = "muted"
    BLOCKED = "blocked"
    ENDED = "ended"


class MemoryVisibility(CanonEnum):
    """Canon §10.2 traži persona-scoped pretragu; ovo je dodatni filter."""

    PRIVATE = "PRIVATE"
    PERSONA_SHARED = "PERSONA_SHARED"
    TEAM_SHARED = "TEAM_SHARED"
    SYSTEM = "SYSTEM"


class MemoryRelation(CanonEnum):
    """Vrsta veze između dve memorije (Canon §10.4)."""

    RELATED = "related"
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    DERIVED = "derived"
    SUPERSEDES = "supersedes"


class ContentStatus(CanonEnum):
    """Životni ciklus komada sadržaja (šema §12)."""

    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"
    FAILED = "FAILED"


class ContentFormat(CanonEnum):
    """Oblik sadržaja, nezavisan od kanala (šema §12)."""

    POST = "post"
    ARTICLE = "article"
    NEWSLETTER = "newsletter"
    COMMENT = "comment"
    REPLY = "reply"
    VIDEO_SCRIPT = "video_script"
    THREAD = "thread"


class IdeaStatus(CanonEnum):
    OPEN = "open"
    SELECTED = "selected"
    REJECTED = "rejected"
    USED = "used"


class PublicationStatus(CanonEnum):
    """Podskup ContentStatus-a koji ima smisla po kanalu (šema §12)."""

    SCHEDULED = "SCHEDULED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    RETRACTED = "RETRACTED"


class MailDirection(CanonEnum):
    INBOUND = "in"
    OUTBOUND = "out"


class RunStatus(CanonEnum):
    """Stanje jednog buđenja persone (Canon §6.1)."""

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    FAILED = "FAILED"


class PlanStatus(CanonEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"
    ABANDONED = "ABANDONED"
    EXPIRED = "EXPIRED"


class StepType(CanonEnum):
    THINK = "think"
    RETRIEVE = "retrieve"
    CREATE = "create"
    ACTION = "action"
    WAIT = "wait"
    REVIEW = "review"


class StepStatus(CanonEnum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    DONE = "DONE"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class AccountStatus(CanonEnum):
    """Stanje `ChannelAccount`-a i `BrowserProfile`-a."""

    PENDING = "pending"
    ACTIVE = "active"
    PAUSED = "paused"
    QUARANTINED = "quarantined"
    REVOKED = "revoked"


class SessionType(CanonEnum):
    """Vrsta runtime sesije (šema §16). Nije `AgentRun` — vidi Canon §1."""

    BROWSER = "browser"
    MAIL = "mail"
    LLM = "llm"
    TOOL = "tool"


class SessionStatus(CanonEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"
    ABORTED = "ABORTED"


class ReconcileStatus(CanonEnum):
    """Canon §12.3 — `UNKNOWN_EFFECT` ide ovde, nikada u retry."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED_EFFECT_PRESENT = "RESOLVED_EFFECT_PRESENT"
    RESOLVED_NO_EFFECT = "RESOLVED_NO_EFFECT"
    UNRESOLVED = "UNRESOLVED"


class IncidentStatus(CanonEnum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    MITIGATED = "MITIGATED"
    CLOSED = "CLOSED"


class SourceKind(CanonEnum):
    """Poreklo memorije ili znanja (Canon §10.4 — ključevi `SOURCE_CONFIDENCE`)."""

    SYSTEM_OBSERVATION = "system_observation"
    FIRST_PARTY_USER_INPUT = "first_party_user_input"
    PUBLIC_WEB_SOURCE = "public_web_source"
    LLM_INFERENCE = "llm_inference"
    SYNTHETIC_WORLD_EVENT = "synthetic_world_event"


class LLMPurpose(CanonEnum):
    """Zašto je model pozvan — osnova za rutiranje i za budžet (Canon §13.2)."""

    PLANNING = "planning"
    CONTENT_DRAFT = "content_draft"
    REPLY = "reply"
    SUMMARISE = "summarise"
    CLASSIFY = "classify"
    EMBED = "embed"
    EVALUATE = "evaluate"


class OutboxStatus(CanonEnum):
    """Stanje reda u event outbox-u (ADR-0004).

    Event se upisuje u istoj transakciji kao i promena stanja, a objavljuje ga
    zaseban korak. PENDING ostaje dok svi potrošači ne potvrde prijem; DEAD
    znači da je pređen broj pokušaja i traži se ljudska intervencija.
    """

    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    DEAD = "DEAD"


__all__ += [
    "OutboxStatus",
    "ScopeKind",
    "AssetKind",
    "AssetRole",
    "ActorKind",
    "RelationshipType",
    "RelationshipStatus",
    "MemoryVisibility",
    "MemoryRelation",
    "ContentStatus",
    "ContentFormat",
    "IdeaStatus",
    "PublicationStatus",
    "MailDirection",
    "RunStatus",
    "PlanStatus",
    "StepType",
    "StepStatus",
    "AccountStatus",
    "SessionType",
    "SessionStatus",
    "ReconcileStatus",
    "IncidentStatus",
    "SourceKind",
    "LLMPurpose",
    "DISCLOSURE_ALWAYS_REQUIRED",
    "TERMINAL_ACTION_STATUSES",
    "ASSIGNABLE_TRUST_LEVELS",
    "ASSIGNABLE_TRUST_LEVEL_VALUES",
    "OUT_OF_SCOPE_CHANNELS",
    "OUT_OF_SCOPE_CHANNEL_VALUES",
    "DISCLOSURE_OK",
    "MEMORY_HALF_LIFE_DAYS",
    "MEMORY_LAMBDA",
    "SOURCE_CONFIDENCE",
    "APPROVAL_TTL_MINUTES",
    "APPROVAL_EXPIRY_EFFECT",
    "APPROVAL_DECIDERS",
    "WAKE_PRIORITY_VALUE",
    "ERROR_HTTP_STATUS",
    "OUTCOME_REASON_CODE",
    "PILOT_DAILY_LIMITS",
    "COST_GOVERNOR_THRESHOLDS",
    "MAX_ATTEMPTS_BY_KIND",
]


# Canon §10.3 — λ = ln2 / half_life_days. Izračunato, ne prepisano, da
# tabela i formula ne mogu da se raziđu.
import math as _math  # noqa: E402

MEMORY_LAMBDA: dict[MemoryType, float] = {
    k: (0.0 if v is None else _math.log(2) / v)
    for k, v in MEMORY_HALF_LIFE_DAYS.items()
}

#: Canon §9.3 — pilot limiti. Ukupno je TVRDI plafon i primenjuje se prvi.
PILOT_DAILY_LIMITS: dict[str, int] = {
    "public_posts": 3,
    "comment_replies": 12,
    "inbound_replies": 20,
    "outbound_email": 5,
    "web_reads": 60,
    "browser_writes": 6,
    "x_posts": 2,
    "total_actions": 40,
}

#: Canon §13.3 — prag dnevnog budžeta → reakcija.
COST_GOVERNOR_THRESHOLDS: tuple[tuple[int, str], ...] = (
    (70, "WARN"),
    (85, "STOP_NONESSENTIAL_MEDIA"),
    (100, "ECONOMY_MODE"),
    (120, "PAUSE_PERSONA_AND_SEV2"),
)

#: Canon §12.4 — retry po vrsti akcije. Policy evaluacija se ne ponavlja.
MAX_ATTEMPTS_BY_KIND: dict[str, int] = {
    "read": 3,
    "write": 2,
    "policy": 1,
}


# ---------------------------------------------------------------- F3 (ADR-0005)
# Behaviour engine: ishod buđenja, razlozi i troškovi aktivnosti.
# Izvor: Behaviour + World + Scheduler Engine v0.1 §8, §25, §27.


class WakeDecision(CanonEnum):
    """Ishod jednog buđenja. SKIP i DEFER su jednako važni kao ACT (§25)."""

    ACT = "ACT"        # aktivnost izabrana i (u F3) interno odrađena
    SKIP = "SKIP"      # svesno ništa — prozor potrošen
    DEFER = "DEFER"    # ne sada — prozor ostaje, buđenje se pomera


class DecisionReason(CanonEnum):
    """`reason_code` iz Behaviour Engine v0.1 §27. Beleži se na svakom run-u."""

    ROUTINE_WINDOW_DUE = "ROUTINE_WINDOW_DUE"
    OPERATOR_TASK = "OPERATOR_TASK"
    WORLD_EVENT_RELEVANT = "WORLD_EVENT_RELEVANT"
    EVENT_DEFERRED = "EVENT_DEFERRED"
    NO_WINDOW = "NO_WINDOW"
    REST_WINDOW = "REST_WINDOW"
    ROUTINE_NOT_SELECTED = "ROUTINE_NOT_SELECTED"
    WINDOW_LIMIT_REACHED = "WINDOW_LIMIT_REACHED"
    LOW_ENERGY_OR_BUDGET = "LOW_ENERGY_OR_BUDGET"
    OVERLOADED = "OVERLOADED"
    COOLDOWN_ACTIVE = "COOLDOWN_ACTIVE"
    PERSONA_PAUSED = "PERSONA_PAUSED"


class ActivityKind(CanonEnum):
    """Vrste aktivnosti iz rutinskih prozora (`RoutineWindow.activity_type`).

    `post` je u F3 isključivo NACRT. Objava je spoljna akcija i ide kroz
    Policy/Approval (F5) i adapter (F6) — Behaviour je ne može izvršiti.
    `rest` je prozor bez aktivnosti: uvek SKIP, bez troška pažnje.
    """

    READ = "read"
    RESEARCH = "research"
    WORK = "work"
    POST = "post"
    SOCIAL = "social"
    INBOX = "inbox"
    REST = "rest"


#: Behaviour v0.1 §8 — trošak pažnje po aktivnosti (jedinice, ne minuti).
ACTIVITY_ATTENTION_COST: dict[ActivityKind, str] = {
    ActivityKind.READ: "0.70",
    ActivityKind.RESEARCH: "1.20",
    ActivityKind.WORK: "2.00",
    ActivityKind.POST: "1.00",
    ActivityKind.SOCIAL: "0.50",
    ActivityKind.INBOX: "0.50",
    ActivityKind.REST: "0.00",
}

#: Behaviour v0.1 §8 — semantički cooldown: dve iste aktivnosti ne zaredom.
ACTIVITY_COOLDOWN_MINUTES: dict[ActivityKind, int] = {
    ActivityKind.READ: 45,
    ActivityKind.RESEARCH: 120,
    ActivityKind.WORK: 30,
    ActivityKind.POST: 180,
    ActivityKind.SOCIAL: 60,
    ActivityKind.INBOX: 60,
    ActivityKind.REST: 0,
}

#: Behaviour v0.1 §12 — pragovi relevantnosti svetskog događaja.
WORLD_RELEVANCE_IGNORE_BELOW = 0.28
WORLD_RELEVANCE_WAKE_FROM = 0.52

#: Canon §11.2/§11.3 — koji razlog buđenja ide u koji queue.
WAKE_QUEUE: dict[WakePriority, QueueName] = {
    WakePriority.OPERATOR_TASK: QueueName.PERSONA_INTERACTIVE,
    WakePriority.APPROVAL_DECISION: QueueName.PERSONA_INTERACTIVE,
    WakePriority.INBOUND_HIGH: QueueName.PERSONA_INTERACTIVE,
    WakePriority.GOAL_DEADLINE: QueueName.PERSONA_SCHEDULED,
    WakePriority.WORLD_EVENT_HIGH: QueueName.PERSONA_SCHEDULED,
    WakePriority.ROUTINE_WINDOW: QueueName.PERSONA_SCHEDULED,
    WakePriority.MAINTENANCE: QueueName.MAINTENANCE,
}

#: Statusi u kojima scheduler budi personu. READY se budi samo ručno (wake/tick).
WAKEABLE_BY_SCHEDULER: frozenset[PersonaStatus] = frozenset({PersonaStatus.ACTIVE})
WAKEABLE_BY_OPERATOR: frozenset[PersonaStatus] = frozenset(
    {PersonaStatus.READY, PersonaStatus.ACTIVE}
)

__all__ += [
    "WakeDecision",
    "DecisionReason",
    "ActivityKind",
    "ACTIVITY_ATTENTION_COST",
    "ACTIVITY_COOLDOWN_MINUTES",
    "WORLD_RELEVANCE_IGNORE_BELOW",
    "WORLD_RELEVANCE_WAKE_FROM",
    "WAKE_QUEUE",
    "WAKEABLE_BY_SCHEDULER",
    "WAKEABLE_BY_OPERATOR",
]


# ---------------------------------------------------------------- F4 (ADR-0006)
# Memory engine: profili pretrage, pragovi upisa, budžet konteksta.
# Izvor: Memory & Knowledge Engine v0.1 §5.2, §7.1–7.2, §12.1.


class RetrievalProfile(CanonEnum):
    """Memory v0.1 §7.2 — isti retriever, različite težine i top-k."""

    REPLY_CONTEXT = "reply_context"
    DAILY_PLANNER = "daily_planner"
    CONTENT_CREATION = "content_creation"
    RESEARCH = "research"
    REFLECTION = "reflection"


#: Profil → svrha LLM poziva (za `MemoryContextPack.purpose`).
PROFILE_PURPOSE: dict[RetrievalProfile, LLMPurpose] = {
    RetrievalProfile.REPLY_CONTEXT: LLMPurpose.REPLY,
    RetrievalProfile.DAILY_PLANNER: LLMPurpose.PLANNING,
    RetrievalProfile.CONTENT_CREATION: LLMPurpose.CONTENT_DRAFT,
    RetrievalProfile.RESEARCH: LLMPurpose.SUMMARISE,
    RetrievalProfile.REFLECTION: LLMPurpose.SUMMARISE,
}

#: Memory v0.1 §7.2 — podrazumevani top-k po profilu (gornja granica opsega).
PROFILE_TOP_K: dict[RetrievalProfile, int] = {
    RetrievalProfile.REPLY_CONTEXT: 14,
    RetrievalProfile.DAILY_PLANNER: 20,
    RetrievalProfile.CONTENT_CREATION: 30,
    RetrievalProfile.RESEARCH: 40,
    RetrievalProfile.REFLECTION: 50,
}

#: Memory v0.1 §12.1 — ciljni broj tokena memorije po profilu (gornja granica).
PROFILE_MEMORY_TOKENS: dict[RetrievalProfile, int] = {
    RetrievalProfile.REPLY_CONTEXT: 1800,
    RetrievalProfile.DAILY_PLANNER: 4000,
    RetrievalProfile.CONTENT_CREATION: 3000,
    RetrievalProfile.RESEARCH: 8000,
    RetrievalProfile.REFLECTION: 4000,
}

#: Memory v0.1 §5.2 — minimalni eligibility M za trajni upis, po tipu.
#: Working je privremen i ide uvek; ostali moraju da zasluže mesto.
MEMORY_ELIGIBILITY_MIN: dict[MemoryType, float] = {
    MemoryType.WORKING: 0.0,
    MemoryType.EPISODIC: 0.25,
    MemoryType.SEMANTIC: 0.30,
    MemoryType.PROCEDURAL: 0.30,
    MemoryType.SOCIAL: 0.25,
    MemoryType.CONTENT: 0.20,
}

#: Memorija sa `sensitivity` iznad ovoga ulazi samo u svrhe sa liste ispod.
SENSITIVE_FROM = 0.70
SENSITIVE_ALLOWED_PURPOSES: frozenset[LLMPurpose] = frozenset({LLMPurpose.SUMMARISE})

#: Memory v0.1 §8 — ispod ove efektivne važnosti memorija se arhivira.
ARCHIVE_BELOW_EFFECTIVE_SALIENCE = 0.05

__all__ += [
    "RetrievalProfile",
    "PROFILE_PURPOSE",
    "PROFILE_TOP_K",
    "PROFILE_MEMORY_TOKENS",
    "MEMORY_ELIGIBILITY_MIN",
    "SENSITIVE_FROM",
    "SENSITIVE_ALLOWED_PURPOSES",
    "ARCHIVE_BELOW_EFFECTIVE_SALIENCE",
]


# ---------------------------------------------------------------- F5 (ADR-0007)
# Policy engine: razlozi odluka, dimenzije limita, obaveze.
# Izvor: Canon §9, §15; Policy / Approval / Trust Engine v0.1.


class PolicyReason(CanonEnum):
    """`reason_code` odluke. Prvi razlog u listi je odlučujući."""

    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    UNKNOWN_ACTION_TYPE = "UNKNOWN_ACTION_TYPE"
    HARD_PROHIBITION = "HARD_PROHIBITION"
    PERSONA_NOT_OPERATIONAL = "PERSONA_NOT_OPERATIONAL"
    CAPABILITY_NOT_GRANTED = "CAPABILITY_NOT_GRANTED"
    TRUST_TOO_LOW = "TRUST_TOO_LOW"
    CHANNEL_REQUIRED = "CHANNEL_REQUIRED"
    CHANNEL_NOT_ACTIVE = "CHANNEL_NOT_ACTIVE"
    CHANNEL_CAPABILITY_DISABLED = "CHANNEL_CAPABILITY_DISABLED"
    DISCLOSURE_MISSING = "DISCLOSURE_MISSING"
    READ_CONSTRAINTS_MISSING = "READ_CONSTRAINTS_MISSING"
    DAILY_CAP_REACHED = "DAILY_CAP_REACHED"
    DIMENSION_CAP_REACHED = "DIMENSION_CAP_REACHED"
    RISK_CRITICAL = "RISK_CRITICAL"
    RISK_HIGH = "RISK_HIGH"
    RISK_MEDIUM_LOW_TRUST = "RISK_MEDIUM_LOW_TRUST"
    RULE_DENY = "RULE_DENY"
    RULE_REQUIRES_APPROVAL = "RULE_REQUIRES_APPROVAL"
    CAPABILITY_REQUIRES_APPROVAL = "CAPABILITY_REQUIRES_APPROVAL"
    APPROVED = "APPROVED"
    WITHIN_POLICY = "WITHIN_POLICY"
    POLICY_ERROR = "POLICY_ERROR"


class Obligation(CanonEnum):
    """Policy v0.1 §3.1, §9 — šta gateway mora da proveri pre izvršenja."""

    CHECK_RATE_LIMIT = "CHECK_RATE_LIMIT"
    ENSURE_AI_DISCLOSURE = "ENSURE_AI_DISCLOSURE"
    CHECK_SUPPRESSION_LIST = "CHECK_SUPPRESSION_LIST"
    LOG_PAYLOAD_HASH = "LOG_PAYLOAD_HASH"
    RESPECT_ROBOTS = "RESPECT_ROBOTS"


#: Canon §9.3 — koja dimenzija dnevnog limita važi za koji ActionType.
ACTION_RATE_DIMENSION: dict[str, str] = {
    "channel.post.create": "public_posts",
    "channel.comment.create": "comment_replies",
    "channel.comment.moderate": "comment_replies",
    "mail.reply": "inbound_replies",
    "mail.send": "outbound_email",
    "browser.page.read": "web_reads",
    "channel.read.public": "web_reads",
    "browser.form.submit": "browser_writes",
}

#: ActionType koji nema spoljni efekat — ne troši dnevni plafon i ne ide
#: kroz gateway kao spoljna akcija.
INTERNAL_ACTION_TYPES: frozenset[str] = frozenset({"content.draft", "memory.consolidate"})

#: Koliko dugo važi odluka ALLOW/THROTTLE/DENY (za REQUIRE_APPROVAL važi TTL klase).
POLICY_DECISION_TTL_MINUTES = 15

#: Statusi akcije koji troše dnevni plafon (Canon §9.3).
COUNTED_ACTION_STATUSES: frozenset[ActionStatus] = frozenset({
    ActionStatus.APPROVAL_PENDING, ActionStatus.QUEUED, ActionStatus.RUNNING,
    ActionStatus.RETRY_WAIT, ActionStatus.SUCCEEDED,
})

#: Ko sme da zaustavi (kill-switch) i ko sme da pusti nazad.
KILL_SWITCH_ACTIVATORS: frozenset[Role] = frozenset(set(Role) - {Role.VIEWER})
KILL_SWITCH_RELEASERS: frozenset[Role] = frozenset(
    {Role.TRUST_SAFETY, Role.RUNTIME_ADMIN, Role.SYSTEM_ADMIN}
)
#: Canon §15.1 — ko menja poverenje.
TRUST_CHANGERS: frozenset[Role] = frozenset({Role.TRUST_SAFETY, Role.SYSTEM_ADMIN})

__all__ += [
    "PolicyReason",
    "Obligation",
    "ACTION_RATE_DIMENSION",
    "INTERNAL_ACTION_TYPES",
    "POLICY_DECISION_TTL_MINUTES",
    "COUNTED_ACTION_STATUSES",
    "KILL_SWITCH_ACTIVATORS",
    "KILL_SWITCH_RELEASERS",
    "TRUST_CHANGERS",
]

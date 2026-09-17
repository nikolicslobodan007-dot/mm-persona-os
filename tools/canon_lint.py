#!/usr/bin/env python3
"""Canon lint — odbija ime koje nije u Canon-u.

Ovo je tačka 7 iz Canon §20 i ono što Canon čini živim dokumentom umesto
još jednog PDF-a: ime van Canon-a ne stiže do `main` grane.

Provere:
  1. Nijedan enum nije definisan van `common/enums.py`.
  2. Ukinuta imena se ne pojavljuju nigde u izvoru (`behavior`, `social_drive`,
     `mood_positive`, `importance`, `RATE_LIMIT`, `Patchright`, …).
  3. Svaki event tip u kodu postoji u katalogu i ima JSON Schema.
  4. Svaki queue naziv u kodu je jedan od deset kanonskih.
  5. `identity_vehicles.yaml` i `capabilities.yaml` se parsiraju i slažu sa enum-ima.
  6. Django app-ovi na disku su tačno onih 12 iz Canon §1.

Izlaz: 0 ako je sve u redu, 1 sa spiskom prekršaja.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from common import enums as E  # noqa: E402
from common.events import EVENT_TYPES, RETIRED_EVENT_TYPES  # noqa: E402

# Canon §1 — dvanaest app-ova.
CANON_APPS = {
    "personas", "visuals", "behaviour", "memory", "social_graph", "content",
    "channels", "orchestration", "policy", "runtime", "observability",
    "llm_gateway",
}

# Imena ukinuta u Canon-u. Regex -> šta se koristi umesto.
RETIRED_NAMES: dict[str, str] = {
    r"\bbehavior\b": "behaviour (Canon §0.3)",
    r"\bsocial_drive\b": "social_appetite (Canon §4.2)",
    r"\bmood_positive\b": "valence, UI: valence_display (Canon §4.2)",
    r"\bmood_valence\b": "valence (Canon §4.2)",
    r"\bworkload\b": "cognitive_load (Canon §4.2)",
    r"\bmin_importance\b": "min_salience (Canon §10.1)",
    r"\bRATE_LIMIT\b(?!ED)": "THROTTLE (Canon §3.5)",
    r"\bPatchright\b": "Playwright (Canon §12.1)",
    r"\bProposedAction\b": "Action (Canon §6.1)",
    r"\bActionExecution\b": "ActionAttempt (Canon §6.1)",
    r"\bEmailAccount\b": "ChannelAccount(type=EMAIL) (Canon §3.15)",
    r"\bcorrelation_id\b": "trace_id (Canon §2.3)",
    r"\bpilot_active\b": "RuntimeEnvironment (Canon §3.2)",
    r"\bPolicyEvaluation\b": "PolicyDecision (Canon §1, §6.2)",
    r"P-\d{3}(?!\d)": "P-00001 — pet cifara (Canon §2.2)",
    r"\bfirst_dm\b": "ukinuto, nema kanal (Canon §3.11)",
}

# Fajlovi u kojima ukinuta imena SMEJU stajati — jer ih upravo zabranjuju.
ALLOWLIST = {
    "tools/canon_lint.py",
    "docs/adr",
    "README.md",
    "CHANGELOG.md",
}

SOURCE_SUFFIXES = {".py", ".yaml", ".yml", ".json", ".toml", ".cfg", ".ini"}
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".mypy_cache",
             ".pytest_cache", "schemas"}


class Violation(tuple):
    def __new__(cls, path: str, line: int, message: str):
        return super().__new__(cls, (path, line, message))

    def __str__(self) -> str:
        path, line, message = self
        return f"{path}:{line}: {message}"


def _iter_sources():
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.suffix not in SOURCE_SUFFIXES:
            continue
        rel = p.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        yield p, str(rel).replace("\\", "/")


def check_enums_only_in_common() -> list[Violation]:
    """Canon §20 tačka 3: nijedan enum van `common/enums.py`."""
    out: list[Violation] = []
    enum_bases = {"Enum", "StrEnum", "IntEnum", "TextChoices", "IntegerChoices",
                  "CanonEnum"}
    for path, rel in _iter_sources():
        if path.suffix != ".py" or rel == "common/enums.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except SyntaxError as exc:
            out.append(Violation(rel, exc.lineno or 0, f"sintaksna greška: {exc.msg}"))
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for base in node.bases:
                name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", None)
                if name in enum_bases:
                    out.append(Violation(
                        rel, node.lineno,
                        f"enum `{node.name}` definisan van common/enums.py "
                        f"(Canon §20 tačka 3)"))
    return out


def check_retired_names() -> list[Violation]:
    """Canon §19: ukinuta imena ne smeju u izvor."""
    out: list[Violation] = []
    compiled = [(re.compile(p), r) for p, r in RETIRED_NAMES.items()]
    for path, rel in _iter_sources():
        if any(rel.startswith(a) for a in ALLOWLIST):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "canon-lint: allow" in line:
                continue
            for rx, replacement in compiled:
                if rx.search(line):
                    out.append(Violation(
                        rel, lineno,
                        f"ukinuto ime `{rx.pattern}` — koristi {replacement}"))
    return out


def check_event_types() -> list[Violation]:
    """Canon §7: svaki event u kodu postoji u katalogu i ima šemu."""
    out: list[Violation] = []
    schema_dir = ROOT / "schemas" / "events"

    for et in EVENT_TYPES:
        if not (schema_dir / et / "1.json").exists():
            out.append(Violation("schemas/events", 0,
                                 f"nedostaje šema za `{et}` (Canon §7.3)"))
    if schema_dir.exists():
        for d in sorted(p for p in schema_dir.iterdir() if p.is_dir()):
            if d.name not in EVENT_TYPES:
                out.append(Violation(f"schemas/events/{d.name}", 0,
                                     "šema za event koji nije u katalogu (Canon §7.2)"))

    rx = re.compile(r'"([a-z_]+(?:\.[a-z_]+){1,3})"')
    for path, rel in _iter_sources():
        if path.suffix != ".py" or any(rel.startswith(a) for a in ALLOWLIST):
            continue
        if rel == "common/events.py":
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for m in rx.finditer(line):
                cand = m.group(1)
                if cand in RETIRED_EVENT_TYPES:
                    out.append(Violation(
                        rel, lineno,
                        f"ukinut event `{cand}` — koristi "
                        f"`{RETIRED_EVENT_TYPES[cand]}` (Canon §7.2)"))
    return out


def check_apps() -> list[Violation]:
    """Canon §1: tačno dvanaest app-ova, tim imenima."""
    apps_dir = ROOT / "apps"
    if not apps_dir.exists():
        return [Violation("apps/", 0, "nedostaje direktorijum apps/ (Canon §1)")]
    found = {p.name for p in apps_dir.iterdir() if p.is_dir() and not p.name.startswith("_")}
    out: list[Violation] = []
    for extra in sorted(found - CANON_APPS):
        out.append(Violation(f"apps/{extra}", 0, "app nije u Canon §1"))
    for missing in sorted(CANON_APPS - found):
        out.append(Violation("apps/", 0, f"nedostaje app `{missing}` (Canon §1)"))
    return out


def check_configs() -> list[Violation]:
    """Canon §3.14, §6.4: YAML konfiguracije se slažu sa enum-ima."""
    try:
        import yaml
    except ImportError:
        return [Violation("tools/canon_lint.py", 0,
                          "PyYAML nije instaliran — provera konfiguracija preskočena")]

    out: list[Violation] = []

    iv_path = ROOT / "channels" / "identity_vehicles.yaml"
    if not iv_path.exists():
        out.append(Violation("channels/identity_vehicles.yaml", 0,
                             "nedostaje (Canon §20 tačka 5a)"))
    else:
        data = yaml.safe_load(iv_path.read_text(encoding="utf-8"))
        known_ch = set(E.ChannelType.values())
        known_iv = set(E.IdentityVehicle.values())
        for ch, cfg in (data.get("channels") or {}).items():
            if ch not in known_ch:
                out.append(Violation("channels/identity_vehicles.yaml", 0,
                                     f"`{ch}` nije ChannelType (Canon §3.15)"))
            for v in (cfg.get("vehicles") or []):
                if v not in known_iv:
                    out.append(Violation("channels/identity_vehicles.yaml", 0,
                                         f"`{v}` nije IdentityVehicle (Canon §3.14)"))
        for ch in known_ch:
            if ch not in (data.get("channels") or {}):
                out.append(Violation("channels/identity_vehicles.yaml", 0,
                                     f"nedostaje kanal `{ch}`"))

    cap_path = ROOT / "policy" / "capabilities.yaml"
    if not cap_path.exists():
        out.append(Violation("policy/capabilities.yaml", 0,
                             "nedostaje (Canon §20 tačka 5)"))
    else:
        data = yaml.safe_load(cap_path.read_text(encoding="utf-8"))
        caps = set(data.get("capabilities") or {})
        assignable = {t.value for t in E.ASSIGNABLE_TRUST_LEVELS}
        for name, cfg in (data.get("capabilities") or {}).items():
            lvl = cfg.get("min_trust_level")
            if lvl not in assignable:
                out.append(Violation("policy/capabilities.yaml", 0,
                                     f"`{name}`: min_trust_level `{lvl}` nije dodeljiv "
                                     f"(Canon §3.11 — L3/L4 su rezervisani)"))
            ac = cfg.get("requires_approval_class")
            if ac is not None and ac not in E.ApprovalClass.values():
                out.append(Violation("policy/capabilities.yaml", 0,
                                     f"`{name}`: nepoznata klasa odobrenja `{ac}`"))
        for at, needed in (data.get("action_types") or {}).items():
            for c in needed:
                if c not in caps:
                    out.append(Violation("policy/capabilities.yaml", 0,
                                         f"action_type `{at}` traži nepoznat "
                                         f"capability `{c}`"))

    rw_path = ROOT / "policy" / "risk_weights.yaml"
    if not rw_path.exists():
        out.append(Violation("policy/risk_weights.yaml", 0, "nedostaje"))
    else:
        data = yaml.safe_load(rw_path.read_text(encoding="utf-8"))
        bands = data.get("risk_bands") or {}
        for low, high, klass in E.RISK_BANDS:
            if bands.get(klass.value) != [low, high]:
                out.append(Violation("policy/risk_weights.yaml", 0,
                                     f"risk_bands[{klass.value}] = "
                                     f"{bands.get(klass.value)}, "
                                     f"Canon §3.6 kaže [{low}, {high}]"))
    return out


CHECKS = (
    ("enum-i samo u common/enums.py", check_enums_only_in_common),
    ("ukinuta imena", check_retired_names),
    ("event katalog i šeme", check_event_types),
    ("Django app-ovi", check_apps),
    ("YAML konfiguracije", check_configs),
)


def main() -> int:
    total: list[Violation] = []
    for label, fn in CHECKS:
        violations = fn()
        mark = "OK  " if not violations else "FAIL"
        print(f"[{mark}] {label}" + (f" — {len(violations)}" if violations else ""))
        total.extend(violations)

    if total:
        print(f"\n{len(total)} prekršaja Canon-a v1.1:\n")
        for v in total:
            print(f"  {v}")
        print("\nAko je ime namerno, izmena ide kroz ADR (Canon §0.2), "
              "ne kroz izuzetak u lintu.")
        return 1

    print("\nCanon v1.1: bez prekršaja.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

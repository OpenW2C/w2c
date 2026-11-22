"""Accepted-risk register and Threat Surface helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from w2c import local as w2c_local

SECURITY_REVIEW_VALUES = frozenset({"required", "none", "accepted"})
SECURITY_PASS_DONE = "done"
REGISTER_LOCAL = "local"
REGISTER_COMMITTED = "committed"
REGISTER_UNSET = "unset"
REGISTER_VALUES = frozenset({REGISTER_UNSET, REGISTER_LOCAL, REGISTER_COMMITTED})
LOCAL_REGISTER_NAME = "SECURITY-RISKS.md"
RISK_ID_RE = re.compile(r"^R\d{3,}$")
BULLET_RE = re.compile(
    r"^-\s*(Security review|Reason|Threats|Controls|Security tests|Accepted risks)\s*:\s*(.*)$",
    re.I,
)
HEADER = (
    "# Accepted security risks\n\n"
    "CLI-written only. Do not hand-edit. Entries must not include exploit steps.\n\n"
    "| Id | When | Scope | Slice | Finding | Evidence | Severity | Reason | Revisit | Ticket |\n"
    "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
)


class RiskError(Exception):
    """Raised for invalid risk-register input or state."""


@dataclass(frozen=True)
class ThreatSurface:
    """Parsed Threat Surface body for one slice."""

    security_review: str
    reason: str
    threats: str
    controls: str
    security_tests: str
    accepted_risks: tuple[str, ...]
    raw: str


@dataclass(frozen=True)
class RiskEntry:
    """One accepted-risk row."""

    risk_id: str
    when: str
    scope: str
    slice_id: str
    finding: str
    evidence: str
    severity: str
    reason: str
    revisit: str
    ticket: str


def normalize_register_mode(value: object | None) -> str:
    """Return unset|local|committed. Missing / empty → unset."""
    if value is None:
        return REGISTER_UNSET
    text = str(value).strip().lower()
    if not text:
        return REGISTER_UNSET
    if text not in REGISTER_VALUES:
        raise RiskError(
            f"invalid security_risk_register {value!r}; use unset|local|committed"
        )
    return text


def normalize_register_path(value: object | None) -> str:
    """Return a relative path string, or empty."""
    if value is None:
        return ""
    text = str(value).strip().replace("\\", "/")
    if not text:
        return ""
    if text.startswith("/") or text.startswith("../") or "/../" in f"/{text}/":
        raise RiskError(f"security_risk_register_path must be a relative path: {text}")
    return text


def assert_register_invariants(mode: str, path: str) -> None:
    """Refuse invalid mode / path combinations."""
    mode = normalize_register_mode(mode)
    path = normalize_register_path(path)
    if mode == REGISTER_COMMITTED and not path:
        raise RiskError(
            "security_risk_register='committed' requires security_risk_register_path"
        )
    if mode in {REGISTER_UNSET, REGISTER_LOCAL} and path:
        raise RiskError(
            f"security_risk_register={mode!r} requires an empty security_risk_register_path"
        )


def register_path(root: Path, *, mode: str | None = None, path: str | None = None) -> Path:
    """Return the on-disk register path for this project."""
    cfg = w2c_local.load_repo_config(root)
    if mode is None:
        mode = str(cfg.get("security_risk_register") or REGISTER_UNSET)
    if path is None:
        path = str(cfg.get("security_risk_register_path") or "")
    mode = normalize_register_mode(mode)
    path = normalize_register_path(path)
    if mode == REGISTER_UNSET:
        mode = REGISTER_LOCAL
    if mode == REGISTER_LOCAL:
        return root / ".w2c" / LOCAL_REGISTER_NAME
    return root / path



def _strip_html_comments(text: str) -> str:
    """Drop HTML comments so template shape notes are not findings."""
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def parse_threat_surface(text: str) -> ThreatSurface | None:
    """Parse a Threat Surface body. Empty or unstructured older text returns None."""
    body = _strip_html_comments(text or "").strip()
    if not body:
        return None
    fields: dict[str, str] = {}
    current: str | None = None
    for line in body.splitlines():
        match = BULLET_RE.match(line.strip())
        if match:
            current = match.group(1).strip().lower()
            fields[current] = match.group(2).strip()
            continue
        if current and line.strip():
            fields[current] = (fields[current] + "\n" + line.strip()).strip()
    review = fields.get("security review", "").strip().lower()
    if review not in SECURITY_REVIEW_VALUES:
        return None
    accepted_raw = fields.get("accepted risks", "").strip()
    accepted: list[str] = []
    if accepted_raw and accepted_raw.lower() not in {"(none)", "none", "n/a", "-"}:
        for part in re.split(r"[,;\s]+", accepted_raw):
            part = part.strip()
            if RISK_ID_RE.match(part):
                accepted.append(part)

    return ThreatSurface(
        security_review=review,
        reason=fields.get("reason", "").strip(),
        threats=fields.get("threats", "").strip(),
        controls=fields.get("controls", "").strip(),
        security_tests=fields.get("security tests", "").strip(),
        accepted_risks=tuple(accepted),
        raw=body,
    )


def security_pass_done(fields: dict[str, str]) -> bool:
    """True when Delivery / Guardrails Security pass is done."""
    return fields.get("Security pass", "").strip().lower() == SECURITY_PASS_DONE


def threat_surface_problems(
    surface: ThreatSurface | None,
    *,
    verify_blob: str = "",
    label: str = "Threat Surface",
) -> list[str]:
    """Problems for a parsed Threat Surface when Security pass is done."""
    if surface is None:
        return [f"{label}: missing structured Security review value (required|none|accepted)"]
    problems: list[str] = []
    if surface.security_review == "none":
        if not surface.reason:
            problems.append(f"{label}: none requires Reason")
    elif surface.security_review == "required":
        if not surface.threats:
            problems.append(f"{label}: required needs Threats")
        if not surface.controls:
            problems.append(f"{label}: required needs Controls")
        if not surface.security_tests:
            problems.append(f"{label}: required needs Security tests")
        elif verify_blob and surface.security_tests:
            # At least one non-trivial token from Security tests should appear in Verify text.
            tokens = [
                t for t in re.split(r"[\s,;]+", surface.security_tests) if len(t) >= 4
            ]
            if tokens and not any(tok.lower() in verify_blob.lower() for tok in tokens):
                problems.append(
                    f"{label}: Security tests must appear in a task Verify line"
                )
    elif surface.security_review == "accepted":
        if not surface.accepted_risks:
            problems.append(f"{label}: accepted needs Accepted risks ids")
    return problems


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _read_register(path: Path) -> str:
    if not path.is_file():
        return HEADER
    text = path.read_text(encoding="utf-8")
    if "| Id | When | Scope |" not in text:
        raise RiskError(f"{path.name} missing table header")
    return text


def list_entries(root: Path) -> list[RiskEntry]:
    """Parse every register row for this project."""
    path = register_path(root)
    if not path.is_file():
        return []
    text = _read_register(path)
    entries: list[RiskEntry] = []
    for line in text.splitlines():
        if not line.startswith("| R"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 10:
            continue
        entries.append(
            RiskEntry(
                risk_id=cells[0],
                when=cells[1],
                scope=cells[2],
                slice_id=cells[3],
                finding=cells[4],
                evidence=cells[5],
                severity=cells[6],
                reason=cells[7],
                revisit=cells[8],
                ticket=cells[9],
            )
        )
    return entries


def next_risk_id(text: str) -> str:
    """Return the next R### id from existing table rows."""
    nums = [
        int(match.group(1))
        for match in re.finditer(r"\|\s*R(\d+)\s*\|", text)
    ]
    n = max(nums) + 1 if nums else 1
    return f"R{n:03d}"


def accept_risk(
    root: Path,
    *,
    scope: str,
    slice_id: str,
    finding: str,
    evidence: str,
    severity: str,
    reason: str,
    revisit: str = "",
    ticket: str = "",
    when: str | None = None,
    mode: str | None = None,
    path: str | None = None,
) -> str:
    """Append one accepted-risk row. Returns the new risk id."""
    if not scope.strip():
        raise RiskError("scope is empty")
    if not finding.strip():
        raise RiskError("finding is empty")
    if not evidence.strip():
        raise RiskError("evidence is empty")
    if not severity.strip():
        raise RiskError("severity is empty")
    if not reason.strip():
        raise RiskError("reason is empty")
    dest = register_path(root, mode=mode, path=path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    text = _read_register(dest)
    risk_id = next_risk_id(text)
    when_s = when or datetime.now().astimezone().strftime("%Y-%m-%d")
    row = (
        f"| {risk_id} | {_cell(when_s)} | {_cell(scope)} | {_cell(slice_id)} | "
        f"{_cell(finding)} | {_cell(evidence)} | {_cell(severity)} | {_cell(reason)} | "
        f"{_cell(revisit)} | {_cell(ticket)} |\n"
    )
    if not text.endswith("\n"):
        text += "\n"
    dest.write_text(text + row, encoding="utf-8")
    return risk_id


def follow_up_risk(root: Path, risk_id: str, ticket: str) -> None:
    """Set or replace the ticket link on an existing risk row."""
    risk_id = risk_id.strip()
    ticket = ticket.strip()
    if not RISK_ID_RE.match(risk_id):
        raise RiskError(f"invalid risk id {risk_id!r}")
    if not ticket:
        raise RiskError("ticket link is empty")
    path = register_path(root)
    if not path.is_file():
        raise RiskError(f"no risk register at {path}")
    text = _read_register(path)
    lines = text.splitlines(keepends=True)
    found = False
    out: list[str] = []
    for line in lines:
        if line.startswith(f"| {risk_id} |"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 10:
                raise RiskError(f"malformed row for {risk_id}")
            cells[9] = ticket
            out.append("| " + " | ".join(_cell(c) for c in cells) + " |\n")
            found = True
        else:
            out.append(line if line.endswith("\n") else line + "\n")
    if not found:
        raise RiskError(f"unknown risk id {risk_id}")
    path.write_text("".join(out), encoding="utf-8")


def recorded_risk_ids(root: Path) -> set[str]:
    """Ids present in the register (ticket may be empty)."""
    return {entry.risk_id for entry in list_entries(root)}


def accepted_risk_problems(root: Path, risk_ids: list[str], label: str) -> list[str]:
    """Problems when accepted risk ids are missing from the register and have no ticket."""
    if not risk_ids:
        return []
    by_id = {entry.risk_id: entry for entry in list_entries(root)}
    problems: list[str] = []
    for risk_id in risk_ids:
        entry = by_id.get(risk_id)
        if entry is None:
            problems.append(f"{label}: accepted risk {risk_id} is not in the register")
            continue
        # Recorded in the register is enough; ticket is optional.
    return problems


def security_review_result_ok(frontmatter: dict[str, str], surface: ThreatSurface | None) -> list[str]:
    """Problems when task summary frontmatter does not match the slice Threat Surface."""
    value = (frontmatter.get("security_review") or "").strip().lower()
    if surface is None:
        # Older plans: do not gate.
        return []
    if surface.security_review == "none":
        if value != "n/a":
            return [f"security_review must be n/a for none slice (got {value!r})"]
        return []
    if surface.security_review in {"required", "accepted"}:
        if value not in {"pass", "fallback-pass"}:
            return [
                f"security_review must be pass or fallback-pass for "
                f"{surface.security_review} slice (got {value!r})"
            ]
        return []
    return [f"unknown Security review value {surface.security_review!r}"]


def cmd_risk_accept(
    root: Path,
    *,
    scope: str,
    slice_id: str,
    finding: str,
    evidence: str,
    severity: str,
    reason: str,
    revisit: str = "",
    ticket: str = "",
    when: str | None = None,
) -> int:
    """CLI entry: accept a risk and print the new id."""
    try:
        risk_id = accept_risk(
            root,
            scope=scope,
            slice_id=slice_id,
            finding=finding,
            evidence=evidence,
            severity=severity,
            reason=reason,
            revisit=revisit,
            ticket=ticket,
            when=when,
        )
    except RiskError as exc:
        from w2c.cli import W2CError

        raise W2CError(str(exc)) from exc
    print(risk_id)
    return 0


def cmd_risk_follow_up(root: Path, risk_id: str, ticket: str) -> int:
    """CLI entry: set the ticket link on a risk."""
    try:
        follow_up_risk(root, risk_id, ticket)
    except RiskError as exc:
        from w2c.cli import W2CError

        raise W2CError(str(exc)) from exc
    print(f"updated {risk_id}")
    return 0


def cmd_risk_list(root: Path) -> int:
    """CLI entry: print the register table."""
    path = register_path(root)
    if not path.is_file():
        print("risk register empty")
        return 0
    text = path.read_text(encoding="utf-8")
    print(text, end="" if text.endswith("\n") else "\n")
    return 0


def collect_plan_security_smoke(
    root: Path,
    items: list[tuple[str, str, str, str, str]],
) -> tuple[list[str], list[str]]:
    """Return (threat_surface problems, accepted_risk problems).

    Each item is (label, security_pass_value, threat_surface_text, verify_blob, unused).
    Skips items whose Security pass is not done.
    """
    threat_problems: list[str] = []
    accepted_problems: list[str] = []
    for label, security_pass, threat_text, verify_blob, _ in items:
        if str(security_pass or "").strip().lower() != SECURITY_PASS_DONE:
            continue
        surface = parse_threat_surface(threat_text)
        threat_problems.extend(
            threat_surface_problems(surface, verify_blob=verify_blob, label=label)
        )
        if surface is not None and surface.security_review == "accepted":
            accepted_problems.extend(
                accepted_risk_problems(root, list(surface.accepted_risks), label)
            )
    return threat_problems, accepted_problems

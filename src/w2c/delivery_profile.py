"""Compose optional .w2c/DELIVERY-PROFILE.md from interview answers.

Agents / configure-client write the file — w2c init does not.
git_delivery remains cadence-only in .w2c/config.toml.
"""
from __future__ import annotations

from typing import Literal

Strategy = Literal["trunk-direct", "feature-branch", "gitflow"]

DEFAULT_CI_PATH = "ai-playbook/mobile/ci-cd/"
VALID_STRATEGIES = frozenset({"trunk-direct", "feature-branch", "gitflow"})

GITFLOW_SECTION = """## Gitflow (release train)

| Branch pattern | Purpose |
| --- | --- |
| `feature/*` (from `develop`) | Feature work; PR → `develop` |
| `develop` | Day-to-day integration |
| `release/*` (from `main`, cherry-picks) | RC line; PR → `main` when ready |
| `hotfix/*` (from `main`) | Production fix; PR → `main` |
| Rollback | Same as hotfix: branch from `main`, revert + fix, PR → `main` |

After every merge to `main` (RC, hotfix, rollback), **back-merge `main` → `develop`**.

Do not invent store-specific tester group names unless the user asks.
"""

CI_SECTION_TMPL = """## CI/CD pointers

| Field | Value |
| --- | --- |
| CI/CD spec (portable) | `{ci_path}` |

See the linked docs for gitflow details, versioning, secrets **names**, TestFlight, and Play. Do not copy full guides into this repo; do not embed secret values.
"""


def compose_delivery_profile(
    *,
    strategy: Strategy,
    ci_pointers: bool,
    ci_path: str = DEFAULT_CI_PATH,
    integration_branch: str | None = None,
    production_branch: str | None = None,
    review_unit: str | None = None,
    external_tickets: str = "Optional",
    project_title: str | None = None,
) -> str:
    """Return markdown for .w2c/DELIVERY-PROFILE.md from independent interview answers."""
    if strategy not in VALID_STRATEGIES:
        raise ValueError(f"invalid strategy: {strategy!r}")

    if integration_branch is None:
        integration_branch = "develop" if strategy == "gitflow" else "main"
    if production_branch is None:
        production_branch = "main" if strategy == "gitflow" else "n/a"
    if review_unit is None:
        if strategy == "gitflow":
            review_unit = (
                "`none` for routine milestone work; **PR to `main`** for RC / hotfix / rollback"
            )
        elif strategy == "feature-branch":
            review_unit = "`pr-per-milestone`"
        else:
            review_unit = "`none`"

    title = "Project Delivery Profile"
    if project_title:
        title = f"{title} — {project_title}"

    intro = (
        f"# {title}\n\n"
        "Record active delivery settings here. Agents read this **after** the abstract "
        "workflow files in `.w2c/`.\n\n"
        "Per-milestone scope, slices, and tasks live in **`.w2c/plans/`** — not in this file.\n\n"
        "Commit/push/PR **cadence** is `.w2c/config.toml` `git_delivery` only — do not duplicate "
        "that enum in this file.\n"
    )

    rows = [
        ("Integration strategy", f"`{strategy}`"),
        ("Integration branch (day-to-day)", f"`{integration_branch}`"),
        ("Production branch", f"`{production_branch}`"),
        ("Commit cadence", "(from `.w2c/config.toml` `git_delivery`)"),
        ("Review unit", review_unit),
        ("Remote push", "Explicit user approval before each push"),
        ("External tickets", external_tickets),
    ]
    if ci_pointers:
        path = (ci_path or DEFAULT_CI_PATH).strip() or DEFAULT_CI_PATH
        rows.append(("CI/CD spec (portable)", f"`{path}`"))

    table_lines = [
        "## Active profile",
        "",
        "| Field | Value |",
        "| --- | --- |",
    ]
    for field, value in rows:
        table_lines.append(f"| {field} | {value} |")
    table_lines.append("")

    parts = [intro, "\n".join(table_lines)]

    if strategy == "gitflow":
        parts.append(GITFLOW_SECTION.rstrip() + "\n")

    if ci_pointers:
        path = (ci_path or DEFAULT_CI_PATH).strip() or DEFAULT_CI_PATH
        parts.append(CI_SECTION_TMPL.format(ci_path=path).rstrip() + "\n")

    parts.append(
        "## Validation (this project)\n\n"
        "```bash\n"
        "# Replace with project-specific verify commands\n"
        "```\n\n"
        "## Notes\n\n"
        "- Task Handoff Gate still applies between tasks even when commits land at slice "
        "boundaries (`git_delivery`).\n"
        "- Honor this profile for merge targets (`develop` vs `main`); honor `git_delivery` "
        "for when to ask commit/push/PR.\n"
    )
    return "\n".join(parts)

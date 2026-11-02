"""Layout constants for cloud mode: where delivery rules and reports live.

Everything committed into an OpenSpec change must be neutral: no tool name.
"""

from __future__ import annotations

DESIGN_HEADINGS: tuple[str, ...] = (
    "## Delivery Plan",
    "## Guardrails",
    "## Commit and PR Conventions",
    "## Decisions",
    "## Manual Test Guide",
    "## Amendments",
)

SLICE_FIELDS: tuple[str, ...] = (
    "Goal",
    "Demo",
    "Must-Haves",
    "Threat Surface",
    "Proof Level",
    "Integration Closure",
    "Verification",
    "Files Likely Touched",
)

DELIVERY_PLAN_FIELDS: tuple[str, ...] = (
    "Isolation mode",
    "Local branch",
    "Remote branch",
    "Isolation scope",
    "Setup when",
    "Reuse policy",
    "Worktree skill",
    "Worktree layout",
    "Worktree dir",
    "Exclude line",
    "Push rule",
    "Base dirt policy",
    "External ticket ID",
    "Integration strategy",
    "Integration branch",
    "Execution sequence",
    "Validation commands",
    "Completion condition",
    "Size budget (LOC diff)",
    "Manual test guide",
)

LEGACY_DROPPED_FIELDS: dict[str, str] = {
    "Milestone / planning ID": "the change folder name identifies the change",
    "Human-readable scope slug": "the change folder name is the slug",
    "Planning mode": "cloud mode is implied by x-delivery-status in .openspec.yaml",
    "OpenSpec change": "the design.md lives inside the change itself",
    "OpenSpec archive": "archive location is recorded by OpenSpec when archiving",
    "Workstream name": "not used in cloud mode; the change is the unit of work",
    "Commit cadence": "covered by the Commit and PR Conventions and Guardrails sections",
    "Review unit": "each tasks.md group is the review unit",
    "Git/PR checkpoint mode": "covered by Push rule and the Guardrails section",
    "Branch name": "replaced by Local branch and Remote branch",
    "Plan commit": "no separate planner commit exists in cloud mode",
}

LEGACY_DROPPED_GUARDRAILS: dict[str, str] = {
    "Plan commit": "no planner files are committed in cloud mode",
    "Spec commit": "the change folder is committed with the product work",
}

STOP_SENTENCE = (
    "Run this change only with the do-chores-cloud skill. "
    "If it is not available, stop and ask the user."
)

RULE_PREFIX = "For a change whose .openspec.yaml has x-delivery-status:"

SLICE_TASK_MARKER = "SLICE-TASK-RULES"
DESIGN_MARKER = "DELIVERY-SECTIONS-RULES"
READ_FIRST_MARKER = "READ-FIRST"

REPORT_DIR = ".delivery"

REPORT_FILES: dict[str, str] = {
    "task_summary": "S##-T##-SUMMARY.md",
    "slice_uat": "S##-UAT.md",
    "slice_summary": "S##-SUMMARY.md",
    "validation": "VALIDATION.md",
    "summary": "SUMMARY.md",
}

_P = RULE_PREFIX
CONFIG_RULES_SNIPPET = f"""\
context: |
  Project knowledge for agents lives in openspec/knowledge.md. Read it before writing any artifact.
rules:
  design:
    - "{_P} {DESIGN_MARKER}: design.md must contain these sections in this order: {', '.join(DESIGN_HEADINGS)}. Fill every Delivery Plan row; write a value or none."
  tasks:
    - "{_P} {SLICE_TASK_MARKER}: every ## N. group in tasks.md is a slice and must carry these bold fields: {', '.join('**' + f + ':**' for f in SLICE_FIELDS)}. Task checkboxes live only in that group."
operations:
  apply:
    guidance:
      - "{_P} {READ_FIRST_MARKER}: read the read-first block at the top of tasks.md, then design.md, before any edit."
      - "{_P} {STOP_SENTENCE}"
"""

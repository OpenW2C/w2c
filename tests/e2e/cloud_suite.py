"""Stages that run the opt-in cloud mode on a dummy project.

Stored outputs live under tests/e2e/expected/cloud/. Later tasks add stages here.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from w2c.cloud import layout

from tests.e2e.harness import REPO, Project, Stage
from tests.e2e.legacy_suite import tree

CHANGE = "add-multiply"
BRANCH = "DEMO-1"
TEMPLATES = REPO / "templates" / "cloud"
VERIFY = "python3 -m unittest discover -s tests -t ."

PROPOSAL = (
    "# Proposal\n\n## Why\n\nPeople need to multiply two numbers with the calculator.\n\n"
    "## What Changes\n\n- Add a multiply function.\n\n"
    "## Capabilities\n\n### New Capabilities\n\n- `calc-multiply`: multiply two numbers\n\n"
    "### Modified Capabilities\n\n## Impact\n\n- app/calc.py\n"
)
SPEC = (
    "# Spec Delta\n\n## Purpose\n\n"
    "Lets a person multiply two numbers using the calculator that ships with the product.\n\n"
    "## ADDED Requirements\n\n### Requirement: Multiply two numbers\n"
    "The system SHALL return the product of two numbers.\n\n"
    "#### Scenario: Multiplying two integers\n"
    "- **WHEN** the caller multiplies 3 by 4\n"
    "- **THEN** the result is 12\n"
)
GROUPS = (
    ("Multiply", ("Add multiply to the calculator", "Test multiply")),
    ("Documentation", ("Document multiply in the README",)),
)


def change_dir(p: Project) -> Path:
    return p.root / "openspec" / "changes" / CHANGE


def filled_design() -> str:
    values = {
        "Isolation mode": "branch", "Local branch": BRANCH, "Remote branch": BRANCH,
        "Worktree skill": "n/a", "Base dirt policy": "clean-at-plan", "Manual test guide": "no",
    }

    def fill(match: re.Match) -> str:
        field, current = match.group(1), match.group(2).strip()
        return f"| {field} | {values.get(field, current or 'none')} |"

    text = (TEMPLATES / "design-delivery.md").read_text(encoding="utf-8")
    return re.sub(
        r"^\| ([^|]+?) \|([^|\n]*)\|$",
        lambda m: m.group(0) if m.group(1) in ("Field", "---") else fill(m),
        text, flags=re.M,
    )


def filled_tasks() -> str:
    out = ["# Tasks\n\n", (TEMPLATES / "tasks-read-first.md").read_text(encoding="utf-8"), "\n"]
    template = (TEMPLATES / "slice-group.md").read_text(encoding="utf-8")
    head = template[: template.index("- [ ] N.1")]
    for number, (title, tasks) in enumerate(GROUPS, start=1):
        block = head.replace("## N. TITLE", f"## {number}. {title}")
        for field in layout.SLICE_FIELDS:
            block = re.sub(rf"^(\*\*{re.escape(field)}:\*\*)$", rf"\1 {field.lower()} for {title}", block, flags=re.M)
        out.append(block)
        for minor, name in enumerate(tasks, start=1):
            out.append(f"- [ ] {number}.{minor} {name}\n  - Verify: {VERIFY}\n")
        out.append("\n")
    return "".join(out)


def no_local_files(p: Project) -> None:
    now = tree(p.root / ".w2c", skip=("runtime",))
    if now != p.state["w2c_files"]:
        raise AssertionError(f"cloud commands changed files under .w2c/:\n{p.state['w2c_files']}--\n{now}")


def report(p: Project, name: str) -> None:
    p.write(change_dir(p) / ".delivery" / name, f"# {name}\n\nDone and checked.\n")


def finish_task(p: Project, sid: str, tid: str) -> str:
    report(p, f"{sid}-{tid}-SUMMARY.md")
    return p.w2c("cloud", "complete", "--change", CHANGE, "--slice", sid, "--task", tid).stdout


def c01_env(p: Project) -> None:
    proc = p.w2c("init", "--planning", "cloud", "--git-delivery", "slice-commit-milestone-push-pr")
    p.expect_tokens(proc, "initialized .w2c/")
    p.expect_tokens(p.read(".w2c/config.toml"), 'planning = "cloud"')
    env = dict(p.env)
    env["W2C_EPHEMERAL"] = "1"
    proc = subprocess.run(
        [str(p.home / ".local" / "bin" / "w2c"), "cloud", "env"],
        cwd=str(p.root), env=env, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(f"w2c cloud env failed\n{proc.stdout}{proc.stderr}")
    p.expect_tokens(proc, "ephemeral: true", "reason: W2C_EPHEMERAL")
    p.expect_matches("C01-env.txt", proc.stdout)


def c02_new(p: Project) -> None:
    p.git("switch", "-q", "-c", BRANCH)
    p.run(["openspec", "init", "--tools", "none", "--no-animation", "--no-copilot-cloud", "."])
    cfg = p.root / "openspec" / "config.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8").rstrip() + "\n\n" + layout.CONFIG_RULES_SNIPPET, encoding="utf-8")
    p.state["w2c_files"] = tree(p.root / ".w2c", skip=("runtime",))
    proc = p.w2c("cloud", "new", "--slug", CHANGE)
    p.expect_tokens(proc, f"created openspec/changes/{CHANGE} ({CHANGE})")
    p.expect_matches("C02-new.txt", proc.stdout)
    meta = p.read(f"openspec/changes/{CHANGE}/.openspec.yaml")
    p.expect_tokens(meta, "x-delivery-status: PLANNING", "x-delivery-order: 1",
                    "x-delivery-cadence: slice-commit-milestone-push-pr")
    p.expect_files("openspec/knowledge.md", ".gitattributes")
    p.expect_tokens(p.read(".gitattributes"), "openspec/knowledge.md merge=union")
    no_local_files(p)
    change = change_dir(p)
    p.write(change / "proposal.md", PROPOSAL)
    p.write(change / "design.md", filled_design())
    p.write(change / "specs" / "calc-multiply" / "spec.md", SPEC)
    p.write(change / "tasks.md", filled_tasks())
    valid = p.run(["openspec", "validate", CHANGE, "--strict"], check=False)
    if valid.returncode != 0:
        raise AssertionError(f"openspec validate --strict failed\n{valid.stdout}{valid.stderr}")
    p.expect_matches("C02-tree.txt", tree(p.root / "openspec"))
    p.w2c("cloud", "status-set", CHANGE, "TODO")
    p.expect_tokens(p.read(f"openspec/changes/{CHANGE}/.openspec.yaml"), "x-delivery-status: TODO")


def c03_next_complete(p: Project) -> None:
    nxt = p.w2c("cloud", "next")
    p.expect_tokens(nxt, f"NEXT {CHANGE} S01 T01 — Add multiply to the calculator")
    p.expect_matches("C03-next.txt", nxt.stdout)
    refused = p.w2c("cloud", "complete", "--change", CHANGE, "--slice", "S01", "--task", "T01", check=False)
    if refused.returncode == 0:
        raise AssertionError("complete should be refused without a task summary")
    p.expect_tokens(refused, "missing report S01-T01-SUMMARY.md")
    done = finish_task(p, "S01", "T01")
    p.expect_tokens(done, f"complete {CHANGE} S01 T01", "OPEN_IN_SLICE 1")
    p.expect_matches("C03-complete.txt", done)
    p.expect_tokens(p.read(f"openspec/changes/{CHANGE}/.openspec.yaml"), "x-delivery-status: INPROGRESS")
    done = finish_task(p, "S01", "T02")
    p.expect_tokens(done, "NEED_SLICE_REPORTS S01")
    early = p.w2c("cloud", "slice-complete", "--change", CHANGE, "--slice", "S01", check=False)
    if early.returncode == 0:
        raise AssertionError("slice-complete should be refused without UAT and summary")
    p.expect_tokens(early, "missing report S01-UAT.md")
    report(p, "S01-UAT.md")
    report(p, "S01-SUMMARY.md")
    sc = p.w2c("cloud", "slice-complete", "--change", CHANGE, "--slice", "S01")
    p.expect_tokens(sc, f"slice-complete {CHANGE} S01", "OPEN_SLICES 1")
    p.expect_matches("C03-slice-complete.txt", sc.stdout)
    p.expect_tokens(p.read(f"openspec/changes/{CHANGE}/.openspec.yaml"), "x-delivery-slices-done: [1]")
    p.expect_tokens(p.read(f"openspec/changes/{CHANGE}/tasks.md"), "- [x] 1.1", "- [x] 1.2", "- [ ] 2.1")
    status = p.w2c("cloud", "status")
    p.expect_tokens(status, f"{CHANGE}: 2/3 tasks", f"Next: {CHANGE} S02 T01: Document multiply")
    p.expect_matches("C03-status.txt", status.stdout)
    no_local_files(p)


def c04_closeout_archive(p: Project) -> None:
    finish_task(p, "S02", "T01")
    report(p, "S02-UAT.md")
    report(p, "S02-SUMMARY.md")
    sc = p.w2c("cloud", "slice-complete", "--change", CHANGE, "--slice", "S02")
    p.expect_tokens(sc, "NEED_MILESTONE_REPORTS " + CHANGE)
    p.expect_matches("C04-slice-complete.txt", sc.stdout)
    early = p.w2c("cloud", "archive", CHANGE, check=False)
    if early.returncode == 0:
        raise AssertionError("archive should be refused without VALIDATION.md")
    p.expect_tokens(early, "missing report VALIDATION.md")
    refused = p.w2c("cloud", "milestone-complete", CHANGE, check=False)
    p.expect_tokens(refused, f"run w2c cloud archive {CHANGE} or pass --archive-declined")
    report(p, "VALIDATION.md")
    report(p, "SUMMARY.md")
    arch = p.w2c("cloud", "archive", CHANGE)
    p.expect_tokens(arch, f"archived {CHANGE} as")
    p.expect_matches("C04-archive.txt", arch.stdout)
    archive_root = p.root / "openspec" / "changes" / "archive"
    listing = tree(archive_root)
    if ".delivery" in listing:
        raise AssertionError(f"archived change still holds reports:\n{listing}")
    p.expect_matches("C04-archive-tree.txt", listing)
    meta = next(archive_root.glob(f"*-{CHANGE}")) / ".openspec.yaml"
    p.expect_tokens(meta.read_text(encoding="utf-8"), "x-delivery-status: DONE")
    done = p.w2c("cloud", "milestone-complete", CHANGE)
    p.expect_tokens(done, f"{CHANGE} -> DONE")
    p.expect_matches("C04-milestone-complete.txt", done.stdout)
    again = p.w2c("cloud", "archive", CHANGE, check=False)
    if again.returncode == 0:
        raise AssertionError("archive of an archived change should be refused")
    no_local_files(p)


def c05_decisions_order(p: Project) -> None:
    first, second = "first-change", "second-change"

    def order_key(name: str) -> str:
        return re.search(r"x-delivery-order: (\d+)", p.read(f"openspec/changes/{name}/.openspec.yaml")).group(1)

    p.w2c("cloud", "new", "--slug", first)
    p.w2c("cloud", "new", "--slug", second)
    held = p.w2c("cloud", "decide", "--scope", "export", "--decision", "Format",
                 "--choice", "csv | json", "--rationale", "simple", "--when", "2026-01-01")
    p.expect_tokens(held, "PENDING")
    held = p.w2c("cloud", "decide", "--change", first, "--scope", "export", "--decision", "Limit",
                 "--choice", "none", "--rationale", "later", "--when", "2026-01-01")
    p.expect_tokens(held, "PENDING")
    early = p.w2c("cloud", "decisions-flush", "--change", first, check=False)
    if early.returncode == 0:
        raise AssertionError("flush should be refused before the design exists")
    for name in (first, second):
        p.write(p.root / "openspec" / "changes" / name / "design.md", filled_design())
    flushed = p.w2c("cloud", "decisions-flush", "--change", first)
    p.expect_tokens(flushed, "2 flushed")
    p.expect_matches("C05-flush.txt", flushed.stdout)
    design = p.read(f"openspec/changes/{first}/design.md")
    p.expect_tokens(design, "| D1 |", "| D2 |", "csv \\| json")
    p.expect_matches("C05-design-decisions.txt", design[design.index("## Decisions"):design.index("## Manual Test Guide")])
    live = p.w2c("cloud", "decide", "--change", first, "--scope", "export", "--decision", "Naming",
                 "--choice", "plain", "--rationale", "clear", "--when", "2026-01-01")
    p.expect_tokens(live, "D3")
    p.expect_matches("C05-decide.txt", live.stdout)
    if (p.root / ".w2c" / "runtime" / "pending-decisions.jsonl").read_text(encoding="utf-8"):
        raise AssertionError("pending decisions were not cleared")
    if (order_key(first), order_key(second)) != ("1", "2"):
        raise AssertionError("unexpected starting order")
    swapped = p.w2c("cloud", "swap", first, second)
    p.expect_matches("C05-swap.txt", swapped.stdout)
    if (order_key(first), order_key(second)) != ("2", "1"):
        raise AssertionError("swap did not rewrite the order keys")
    moved = p.w2c("cloud", "move", first, "--before", second)
    p.expect_matches("C05-move.txt", moved.stdout)
    ordered = p.w2c("cloud", "order", second, first)
    p.expect_matches("C05-order.txt", ordered.stdout)
    refused = p.w2c("cloud", "swap", first, "no-such-change", check=False)
    if refused.returncode == 0:
        raise AssertionError("unknown change should be refused")
    no_local_files(p)


STAGES = [
    Stage("C01", "cloud planning init and env", c01_env),
    Stage("C02", "cloud new change from templates and strict validate", c02_new),
    Stage("C03", "cloud next, complete, slice-complete", c03_next_complete),
    Stage("C04", "cloud closeout and archive", c04_closeout_archive),
    Stage("C05", "cloud decisions held then flushed, reorder", c05_decisions_order),
]

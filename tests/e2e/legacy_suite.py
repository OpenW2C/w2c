"""Stages that run today's W2C 2.2 flow on a dummy project.

Stored outputs under tests/e2e/expected/legacy/ capture exact behavior. Later work
must not change them. They record Copilot instruction files by name and presence only,
and `w2c trials` is asserted by token, because those two outputs are expected to grow.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from w2c.openspec import CONFIG_RULES_SNIPPET

from tests.e2e.harness import Project, Stage, package_version

CHANGE = "add-multiply"
VERIFY_UNITTEST = "python3 -m unittest discover -s tests -t ."

CONVENTIONS = """
## Commit and PR conventions

**Commit title:** short imperative subject.

**Commit body:** optional body after a blank line.

**Pull request:** follow this repo's pull request template.

**Do not stage / commit:**
Never stage `.w2c/runtime/`, `.w2c/` when track is false, Copilot W2C instruction files, or `.env*`. Product commits must never stage these.

`openspec/` is product content and is never deny-listed. Product commits stage only this change's folder plus the archive result.

**Do not mention:**
Never mention any `.w2c/` path or W2C artifact in commit or pull request text.

**AI attribution - forbidden:**
Do not add `Co-authored-by:` trailers or similar AI co-author lines.
"""


def git_plan(branch: str, mode: str = "branch") -> str:
    if mode == "worktree":
        skill, policy = "using-git-worktrees", "n/a-worktree"
    else:
        skill, policy = "n/a", "clean-at-plan"
    return (
        "\n## Git Operation Plan\n"
        "| Field | Value |\n"
        "| --- | --- |\n"
        f"| Isolation mode | {mode} |\n"
        f"| Local branch | {branch} |\n"
        f"| Remote branch | {branch} |\n"
        "| Isolation scope | ticket |\n"
        "| Setup when | first-do-chores |\n"
        "| Plan commit | required-before-isolation |\n"
        "| Reuse policy | reuse-if-same-ticket-else-stop |\n"
        f"| Worktree skill | {skill} |\n"
        "| Push rule | from config + explicit approval; push ref must equal Remote branch |\n"
        f"| Base dirt policy | {policy} |\n"
    )


def spec_roadmap(mid: str, slug: str, slices: list[str], branch: str) -> str:
    lines = "\n".join(f"- [ ] **S0{i}: {title}**" for i, title in enumerate(slices, 1))
    return (
        f"# {mid}: {slug}\n\n## Slices\n\n{lines}\n\n"
        "## Delivery & Guardrails\n| Field | Value |\n| --- | --- |\n"
        "| Planning mode | openspec |\n"
        f"| OpenSpec change | {slug} |\n"
        "| OpenSpec archive | |\n"
        "| Manual test guide | no |\n" + git_plan(branch) + CONVENTIONS
    )


def spec_slice_plan(mid: str, sid: str, title: str, branch: str) -> str:
    return (
        f"# {sid}: {title}\n\nMilestone {mid} delivery envelope. No task lines.\n"
        + git_plan(branch)
        + CONVENTIONS
    )


def classic_roadmap(mid: str, slug: str, branch: str) -> str:
    return (
        f"# {mid}: {slug}\n\n## Slices\n\n"
        "- [ ] **S01: Subtract** `risk:low` `depends:[]`\n\n"
        "## Delivery & Guardrails\n| Field | Value |\n| --- | --- |\n"
        "| Manual test guide | no |\n" + git_plan(branch, "worktree") + CONVENTIONS
    )


def classic_slice_plan(mid: str, branch: str) -> str:
    return (
        f"---\nMILESTONE ID: {mid}\nSLICE ID: S01\n---\n\n# S01: Subtract\n\n<tasks>\n"
        "- [ ] **T01**: Add subtract to the calculator.\n"
        f"  - Verify: {VERIFY_UNITTEST}\n"
        "- [ ] **T02**: Document subtract in the README.\n"
        "  - Verify: grep -q subtract README.md\n"
        "</tasks>\n" + git_plan(branch, "worktree") + CONVENTIONS
    )


PROPOSAL = (
    "# Proposal\n\n## Why\n\nPeople need to multiply two numbers with the calculator.\n\n"
    "## What Changes\n\n- Add a multiply function.\n\n"
    "## Capabilities\n\n### New Capabilities\n\n- `calc-multiply`: multiply two numbers\n\n"
    "### Modified Capabilities\n\n## Impact\n\n- app/calc.py\n"
)
DESIGN = (
    "# Design\n\n## Context\n\nSee proposal.md.\n\n## Goals / Non-Goals\n\n"
    "**Goals:**\n\n- Multiply two numbers.\n\n**Non-Goals:**\n\n- Division.\n\n"
    "## Decisions\n\n- Add one function. A class was rejected because the module is tiny.\n\n"
    "## Risks / Trade-offs\n\n- [Overflow] -> Python integers do not overflow\n"
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
TASKS = (
    "# Tasks\n\n## 1. Multiply\n\n"
    "- [ ] 1.1 Add multiply to the calculator and verify its unit test passes\n"
    f"  - Verify: {VERIFY_UNITTEST}\n\n"
    "## 2. Documentation and helpers\n\n"
    "- [ ] 2.1 Document multiply in the README\n"
    "  - Verify: grep -q multiply README.md\n"
    "- [ ] 2.2 Add a modulo helper to the calculator\n"
    "  - Verify: python3 -c 'from app.calc import mod; assert mod(7, 3) == 1'\n"
)

CALC_MULTIPLY = (
    '"""Tiny calculator used as the dummy product."""\n\n\n'
    "def add(a, b):\n    return a + b\n\n\n"
    "def multiply(a, b):\n    return a * b\n"
)
CALC_SUBTRACT = CALC_MULTIPLY + "\n\ndef subtract(a, b):\n    return a - b\n"
TEST_MULTIPLY = (
    "import unittest\n\nfrom app.calc import add, multiply\n\n\n"
    "class CalcTests(unittest.TestCase):\n"
    "    def test_add(self) -> None:\n        self.assertEqual(add(1, 2), 3)\n\n"
    "    def test_multiply(self) -> None:\n        self.assertEqual(multiply(3, 4), 12)\n\n\n"
    'if __name__ == "__main__":\n    unittest.main()\n'
)
TEST_SUBTRACT = (
    "import unittest\n\nfrom app.calc import add, multiply, subtract\n\n\n"
    "class CalcTests(unittest.TestCase):\n"
    "    def test_add(self) -> None:\n        self.assertEqual(add(1, 2), 3)\n\n"
    "    def test_multiply(self) -> None:\n        self.assertEqual(multiply(3, 4), 12)\n\n"
    "    def test_subtract(self) -> None:\n        self.assertEqual(subtract(5, 2), 3)\n\n\n"
    'if __name__ == "__main__":\n    unittest.main()\n'
)


# ---------------------------------------------------------------- helpers

def tree(base: Path, *, skip: tuple[str, ...] = ()) -> str:
    """Sorted relative file names under base, following the ledger symlink."""
    out: list[str] = []
    real = base.resolve()
    for dirpath, dirnames, filenames in os.walk(real):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            rel = (Path(dirpath) / name).relative_to(real).as_posix()
            if any(rel == s or rel.startswith(s + "/") for s in skip):
                continue
            out.append(rel)
    return "\n".join(sorted(out)) + "\n"


def plan_dir(p: Project, mid: str, slug: str, cwd: Path | None = None) -> Path:
    return (cwd or p.root) / ".w2c" / "plans" / f"{mid}-{slug}"


def write_task_report(p: Project, d: Path, sid: str, tid: str) -> None:
    p.write(d / f"{sid}-{tid}-SUMMARY.md", f"# {tid}\n\n## What Happened\n\ndone\n")


def write_slice_reports(p: Project, d: Path, sid: str, extra: str = "") -> None:
    p.write(d / f"{sid}-UAT.md", f"# {sid} UAT\n\n- [ ] walk through the slice\n")
    p.write(d / f"{sid}-SUMMARY.md", f"# {sid}\n\n## Verification\n\nok\n{extra}")


def write_milestone_reports(p: Project, d: Path, mid: str) -> None:
    p.write(d / f"{mid}-VALIDATION.md", f"# Milestone Validation: {mid}\n\nverdict: pass\n")
    p.write(d / f"{mid}-SUMMARY.md", f"# {mid}\n\n## What Happened\n\nok\n")


def remote_sha(p: Project, branch: str) -> str:
    return p.git("--git-dir", str(p.remote), "rev-parse", f"refs/heads/{branch}", cwd=p.tmp).stdout.strip()


def head(p: Project, cwd: Path | None = None) -> str:
    return p.git("rev-parse", "HEAD", cwd=cwd).stdout.strip()


def milestone_order(p: Project) -> list[str]:
    text = p.read(".w2c/ROADMAP.md")
    return re.findall(r"\*\*(M\d{3}):", text)


# ---------------------------------------------------------------- stages

def l01_install(p: Project) -> None:
    proc = p.w2c("--version")
    if proc.stdout.strip() != f"w2c {package_version()}":
        raise AssertionError(f"w2c --version printed {proc.stdout!r}")
    p.expect_matches("L01-version.txt", proc.stdout)
    data = p.home / ".local" / "share" / "w2c"
    p.expect_files("src/w2c/cli.py", "templates/M-ROADMAP.md", "skills/work-to-chores/SKILL.md",
                   "skills/do-chores/SKILL.md", "hooks/openspec-archive/pre-push", cwd=data)
    p.expect_files(".local/bin/w2c", ".config/.w2c/config.toml", cwd=p.home)
    # Presence only: later releases add skills, and the stored outputs must not change.
    p.expect_files(".agents/skills/work-to-chores", ".agents/skills/do-chores", cwd=p.home)


def l02_init(p: Project) -> None:
    proc = p.w2c("init", "--git-delivery", "slice-commit-milestone-push-pr")
    p.expect_tokens(proc, "initialized .w2c/", "NEED_OPENSPEC_INIT")
    p.expect_matches("L02-init.txt", proc.stdout)
    link = p.root / ".w2c"
    if not link.is_symlink():
        raise AssertionError(".w2c should be a symlink into the git directory")
    p.expect_matches("L02-ledger-files.txt", tree(link, skip=("runtime",)))
    p.expect_matches("L02-gitignore.txt", p.read(".gitignore"))
    names = []
    for name in ("work-to-chores", "do-chores"):
        rel = f".github/instructions/{name}.instructions.md"
        names.append(f"{rel} {'present' if (p.root / rel).is_file() else 'MISSING'}")
    p.expect_matches("L02-copilot-files.txt", "\n".join(names) + "\n")
    config = p.read(".w2c/config.toml")
    p.expect_tokens(config, 'git_delivery = "slice-commit-milestone-push-pr"', 'planning = "openspec"',
                    "track = false", "schema_version = 3")
    # Set OpenSpec up the way the skills expect: init, then the W2C rules.
    p.run(["openspec", "init", "--tools", "none", "--no-animation", "--no-copilot-cloud", "."])
    cfg = p.root / "openspec" / "config.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8").rstrip() + "\n\n" + CONFIG_RULES_SNIPPET, encoding="utf-8")
    check = json.loads(p.w2c("openspec-check").stdout)
    for key in ("cli_found", "version_ok", "root_present", "rules_present"):
        if check.get(key) is not True:
            raise AssertionError(f"openspec-check {key} is {check.get(key)!r}: {check}")
    if check.get("needs"):
        raise AssertionError(f"openspec-check still needs {check['needs']}")


def l03_milestone(p: Project) -> None:
    proc = p.w2c("milestone-new", "--slug", CHANGE)
    p.expect_tokens(proc, "created .w2c/plans/M001-add-multiply (M001)")
    p.expect_matches("L03-milestone-new.txt", proc.stdout)
    meta = p.read(f"openspec/changes/{CHANGE}/.openspec.yaml")
    p.expect_tokens(meta, "x-w2c-milestone: M001")
    p.expect_files(".w2c/plans/M001-add-multiply/M001-ROADMAP.md", ".w2c/plans/M001-add-multiply/M001-CONTEXT.md")
    hook = p.read(".git/hooks/pre-push")
    p.expect_tokens(hook, "# w2c-hook: openspec-archive")
    p.expect_tokens(p.w2c("hook", "status"), "openspec-archive: installed")
    p.expect_matches("L03-roadmap.txt", p.read(".w2c/ROADMAP.md"))
    d = plan_dir(p, "M001", CHANGE)
    p.write(d / "M001-ROADMAP.md", spec_roadmap("M001", CHANGE, ["Multiply", "Documentation and helpers"], "DEMO-1"))
    p.write(d / "M001-S01-PLAN.md", spec_slice_plan("M001", "S01", "Multiply", "DEMO-1"))
    p.write(d / "M001-S02-PLAN.md", spec_slice_plan("M001", "S02", "Documentation and helpers", "DEMO-1"))
    change = p.root / "openspec" / "changes" / CHANGE
    p.write(change / "proposal.md", PROPOSAL)
    p.write(change / "design.md", DESIGN)
    p.write(change / "specs" / "calc-multiply" / "spec.md", SPEC)
    p.write(change / "tasks.md", TASKS)
    p.expect_matches("L03-tree.txt", tree(p.root / "openspec") + "--\n" + tree(p.root / ".w2c" / "plans"))
    smoke = p.w2c("smoke", "--milestone", "M001")
    p.expect_tokens(smoke, "PASS")
    if "FAIL" in smoke.stdout:
        raise AssertionError(smoke.stdout)
    # Strict validation with the real OpenSpec program is part of smoke.
    p.expect_tokens(smoke, "openspec-validate-strict")


def l04_decide_context_reorder(p: Project) -> None:
    proc = p.w2c("decide", "--scope", "M001", "--decision", "How to multiply",
                 "--choice", "Use the star operator", "--rationale", "It is the simplest option",
                 "--when", "2026-11-02")
    p.expect_tokens(proc, "D001")
    p.expect_matches("L04-decide.txt", proc.stdout)
    p.expect_matches("L04-decisions.txt", p.read(".w2c/DECISIONS.md"))
    ctx = p.w2c("context-new", "--minor")
    p.expect_tokens(ctx, "CONTEXTv1.1.md")
    p.expect_matches("L04-context-new.txt", ctx.stdout)
    p.expect_files(".w2c/contexts/CONTEXTv1.0.md", ".w2c/contexts/CONTEXTv1.1.md")
    p.expect_tokens(p.w2c("next-milestone-id"), "M002")
    two = p.w2c("milestone-new", "--slug", "add-subtract", "--planning", "classic")
    p.expect_tokens(two, "created .w2c/plans/M002-add-subtract (M002)")
    d2 = plan_dir(p, "M002", "add-subtract")
    p.write(d2 / "M002-ROADMAP.md", classic_roadmap("M002", "add-subtract", "DEMO-2"))
    p.write(d2 / "M002-S01-PLAN.md", classic_slice_plan("M002", "DEMO-2"))
    p.expect_tokens(p.w2c("smoke", "--milestone", "M002"), "PASS")
    if milestone_order(p) != ["M001", "M002"]:
        raise AssertionError(milestone_order(p))
    swapped = p.w2c("milestone-order", "M002", "M001")
    p.expect_matches("L04-reorder.txt", swapped.stdout)
    if milestone_order(p) != ["M002", "M001"]:
        raise AssertionError(f"reorder did not move M002 first: {milestone_order(p)}")
    p.w2c("milestone-order", "M001", "M002")
    if milestone_order(p) != ["M001", "M002"]:
        raise AssertionError(f"reorder did not restore the order: {milestone_order(p)}")
    p.expect_matches("L04-roadmap.txt", p.read(".w2c/ROADMAP.md"))


def l05_branch_and_worktree(p: Project) -> None:
    dirt = p.w2c("base-dirt")
    p.expect_tokens(dirt, '"status": "noncritical"', ".gitignore", "openspec/config.yaml")
    p.expect_matches("L05-base-dirt.txt", dirt.stdout)
    p.git("checkout", "-q", "-b", "DEMO-1")
    if p.git("branch", "--show-current").stdout.strip() != "DEMO-1":
        raise AssertionError("not on DEMO-1")
    layout = p.w2c("repo-layout")
    p.expect_tokens(layout, "layout: main-checkout")
    p.write(".env", "NPM_TOKEN=e2e-secret" + chr(10))
    nested = Path("apps/app-v2/.env")
    p.write(nested, "EXPO_PUBLIC_APP_VARIANT=development" + chr(10))
    cfg = Path(p.root / ".w2c" / "config.toml")
    if cfg.is_symlink():
        cfg = cfg.resolve()
    body = cfg.read_text(encoding="utf-8") if cfg.is_file() else ""
    if "worktree_seed" not in body:
        extra = chr(10).join([
            "",
            "worktree_seed = [",
            '  ".env",',
            '  "apps/app-v2/.env",',
            '  "missing.env",',
            "]",
            "",
        ])
        cfg.write_text(body.rstrip() + extra, encoding="utf-8")
    wt = p.w2c("worktree-add", "--branch", "DEMO-2", "--create-from", "main")
    path = Path(wt.stdout.strip().splitlines()[0])
    if path.resolve() != (p.root / ".worktrees" / "DEMO-2").resolve():
        raise AssertionError(f"unexpected worktree path {path}")
    p.expect_matches("L05-worktree-add.txt", wt.stdout.strip().splitlines()[0] + "\n")
    if "seed-linked .env" not in wt.stderr:
        raise AssertionError(f"missing seed stderr: {wt.stderr!r}")
    if "seed-skip missing-source missing.env" not in wt.stderr:
        raise AssertionError(f"missing skip stderr: {wt.stderr!r}")
    env_link = path / ".env"
    if not env_link.is_symlink() or not env_link.samefile(p.root / ".env"):
        raise AssertionError(f"worktree .env not seeded: {env_link}")
    nested_link = path / "apps" / "app-v2" / ".env"
    if not nested_link.is_symlink():
        raise AssertionError("nested worktree .env not seeded")
    check = p.w2c("worktree-seed", "--check", cwd=path)
    if check.returncode != 0:
        raise AssertionError(check.stdout + check.stderr)
    reuse = p.w2c("worktree-add", "--branch", "DEMO-2")
    if Path(reuse.stdout.strip().splitlines()[0]).resolve() != path.resolve():
        raise AssertionError("reuse path mismatch")
    if "seed-ok .env" not in reuse.stderr:
        raise AssertionError(f"reuse did not re-seed: {reuse.stderr!r}")
    p.expect_files(".w2c/STATE.md", ".w2c/plans/M002-add-subtract/M002-ROADMAP.md", cwd=path)
    p.expect_tokens(p.read(".git/info/exclude"), ".worktrees/")
    p.state["worktree"] = str(path)
    listed = p.git("worktree", "list", "--porcelain").stdout
    p.expect_tokens(listed, "branch refs/heads/DEMO-2", "branch refs/heads/DEMO-1")


def l06_next_complete_slice(p: Project) -> None:
    nxt = p.w2c("next")
    p.expect_tokens(nxt, "NEXT M001 S01 T01 — Add multiply to the calculator")
    p.expect_matches("L06-next.txt", nxt.stdout)
    p.write("app/calc.py", CALC_MULTIPLY)
    p.write("tests/test_calc.py", TEST_MULTIPLY)
    p.run(["python3", "-m", "unittest", "discover", "-s", "tests", "-t", "."])
    d = plan_dir(p, "M001", CHANGE)
    refused = p.w2c("complete", "--milestone", "M001", "--slice", "S01", "--task", "T01", check=False)
    if refused.returncode == 0:
        raise AssertionError("complete should be refused without a task summary")
    p.expect_tokens(refused, "missing report S01-T01-SUMMARY.md")
    if "- [x] 1.1" in p.read(f"openspec/changes/{CHANGE}/tasks.md"):
        raise AssertionError("refused complete must not tick the task")
    write_task_report(p, d, "S01", "T01")
    done = p.w2c("complete", "--milestone", "M001", "--slice", "S01", "--task", "T01")
    p.expect_tokens(done, "complete M001 S01 T01", "NEED_SLICE_REPORTS S01")
    p.expect_matches("L06-complete.txt", done.stdout)
    p.expect_tokens(p.read(f"openspec/changes/{CHANGE}/tasks.md"), "- [x] 1.1 Add multiply")
    early = p.w2c("slice-complete", "--milestone", "M001", "--slice", "S01", check=False)
    if early.returncode == 0:
        raise AssertionError("slice-complete should be refused without UAT and summary")
    p.expect_tokens(early, "missing report S01-UAT.md")
    write_slice_reports(p, d, "S01")
    sc = p.w2c("slice-complete", "--milestone", "M001", "--slice", "S01")
    p.expect_tokens(sc, "slice-complete M001 S01")
    p.expect_matches("L06-slice-complete.txt", sc.stdout)
    p.expect_tokens(p.read(".w2c/plans/M001-add-multiply/M001-ROADMAP.md"), "- [x] **S01: Multiply**")
    p.expect_matches("L06-state.txt", p.read(".w2c/STATE.md"))
    after = p.w2c("next")
    p.expect_tokens(after, "NEXT M001 S02 T01")


def l07_commit_and_push(p: Project) -> None:
    p.git("add", ".gitignore", "openspec")
    p.git("commit", "-q", "-m", "Plan the multiply change.")
    p.git("add", "app", "tests")
    p.git("commit", "-q", "-m", "Add multiply to the calculator.")
    staged = p.git("ls-tree", "-r", "--name-only", "HEAD").stdout
    if ".w2c" in staged:
        raise AssertionError("the ledger must never reach a product commit")
    push = p.git("push", "-u", "origin", "DEMO-1")
    if remote_sha(p, "DEMO-1") != head(p):
        raise AssertionError("remote DEMO-1 does not match the local commit")
    log = p.git("log", "--format=%s", "main..DEMO-1").stdout
    p.expect_matches("L07-log.txt", log)
    p.expect_tokens(push.stdout + push.stderr, "DEMO-1")
    p.expect_tokens(p.w2c("hook", "status"), "openspec-archive: installed")
    ready = p.w2c("openspec-push-check", "--local-ref", "refs/heads/DEMO-1", "--local-sha", head(p))
    if ready.stderr.strip():
        raise AssertionError(f"push check should be quiet: {ready.stderr}")


def l08_amendment(p: Project) -> None:
    p.w2c("decide", "--scope", "M001", "--decision", "Drop the modulo helper",
          "--choice", "Replace it with subtract", "--rationale", "Subtract is what people asked for",
          "--when", "2026-11-02")
    begin = p.w2c("amend-begin", "M001", "--decision", "D002")
    p.expect_tokens(begin, "M001")
    locked = p.w2c("next", "--milestone", "M001", check=False)
    p.expect_tokens(locked, "AMEND_LOCK M001")
    blocked = p.w2c("complete", "--milestone", "M001", "--slice", "S02", "--task", "T01", check=False)
    p.expect_tokens(blocked, "AMEND_LOCK")
    drop = p.w2c("drop-task", "--milestone", "M001", "--slice", "S02", "--task", "T02",
                 "--reason", "modulo is not needed", "--decision", "D002")
    p.expect_matches("L08-drop-task.txt", drop.stdout)
    add = p.w2c("task-add", "--milestone", "M001", "--slice", "S02", "--title", "Add a subtract helper to the calculator",
                "--verify", "python3 -c 'from app.calc import subtract; assert subtract(5, 2) == 3'",
                "--reason", "people asked for subtract", "--decision", "D002")
    p.expect_matches("L08-task-add.txt", add.stdout)
    end = p.w2c("amend-end", "M001")
    # The smoke table lists OpenSpec's version and grows with new checks, so store only the verdict line.
    p.expect_tokens(end, "PASS openspec-validate-strict", "amend-end M001 PAUSED")
    p.expect_matches("L08-amend-end.txt", end.stdout.strip().splitlines()[-1])
    tasks = p.read(f"openspec/changes/{CHANGE}/tasks.md")
    p.expect_tokens(tasks, "- [d] 2.2 Add a modulo helper", "- [ ] 2.3 Add a subtract helper")
    p.expect_matches("L08-tasks.txt", tasks)
    listed = p.w2c("amendments", "M001")
    p.expect_tokens(listed, "T02")
    p.expect_matches("L08-amendments.txt", listed.stdout)
    after = p.w2c("next", "--milestone", "M001")
    p.expect_tokens(after, "NEXT M001 S02 T01")
    smoke = p.w2c("smoke", "--milestone", "M001")
    if "FAIL" in smoke.stdout:
        raise AssertionError(smoke.stdout)


def l09_closeout(p: Project) -> None:
    d = plan_dir(p, "M001", CHANGE)
    p.write("README.md", "# Dummy calculator\n\nThe calculator can add and multiply.\n")
    write_task_report(p, d, "S02", "T01")
    p.w2c("complete", "--milestone", "M001", "--slice", "S02", "--task", "T01")
    p.write("app/calc.py", CALC_SUBTRACT)
    p.write("tests/test_calc.py", TEST_SUBTRACT)
    p.run(["python3", "-m", "unittest", "discover", "-s", "tests", "-t", "."])
    write_task_report(p, d, "S02", "T03")
    last = p.w2c("complete", "--milestone", "M001", "--slice", "S02", "--task", "T03")
    p.expect_tokens(last, "complete M001 S02 T03", "NEED_SLICE_REPORTS S02")
    unnamed = p.w2c("slice-complete", "--milestone", "M001", "--slice", "S02", check=False)
    if unnamed.returncode == 0:
        raise AssertionError("slice-complete needs the reports")
    write_slice_reports(p, d, "S02", "\nT02 was dropped: modulo is not needed.\n")
    p.expect_tokens(p.w2c("slice-complete", "--milestone", "M001", "--slice", "S02"), "slice-complete M001 S02")
    write_milestone_reports(p, d, "M001")
    p.git("add", "README.md", "app", "tests", "openspec")
    p.git("commit", "-q", "-m", "Add subtract and document the calculator.")
    sha = head(p)
    check = p.w2c("openspec-push-check", "--local-ref", "refs/heads/DEMO-1", "--local-sha", sha, check=False)
    if check.returncode == 0:
        raise AssertionError("push check must fail while the change is not archived")
    p.expect_tokens(check, "M001: OpenSpec archive is empty", "w2c spec-archive M001")
    p.expect_matches("L09-push-check-fail.txt", check.stderr)
    blocked = p.git("push", "origin", "DEMO-1", check=False)
    if blocked.returncode == 0:
        raise AssertionError("the pre-push hook must refuse an unarchived finished milestone")
    p.expect_tokens(blocked.stdout + blocked.stderr, "w2c spec-archive M001")
    if remote_sha(p, "DEMO-1") == sha:
        raise AssertionError("refused push still reached the remote")
    archived = p.w2c("spec-archive", "M001")
    p.expect_tokens(archived, f"archived {CHANGE} as")
    p.expect_matches("L09-spec-archive.txt", archived.stdout)
    p.expect_matches("L09-openspec-tree.txt", tree(p.root / "openspec"))
    roadmap = p.read(".w2c/plans/M001-add-multiply/M001-ROADMAP.md")
    p.expect_tokens(roadmap, "openspec/changes/archive/")
    p.expect_matches("L09-archive-row.txt",
                     "\n".join(l for l in roadmap.splitlines() if "OpenSpec archive" in l) + "\n")
    complete = p.w2c("milestone-complete", "M001")
    p.expect_matches("L09-milestone-complete.txt", complete.stdout)
    p.expect_tokens(p.read(".w2c/ROADMAP.md"), "✅")
    p.git("add", "openspec")
    p.git("commit", "-q", "-m", "Archive the multiply change.")
    sha = head(p)
    ok = p.w2c("openspec-push-check", "--local-ref", "refs/heads/DEMO-1", "--local-sha", sha)
    if ok.stderr.strip():
        raise AssertionError(ok.stderr)
    p.git("push", "origin", "DEMO-1")
    if remote_sha(p, "DEMO-1") != sha:
        raise AssertionError("archived push did not reach the remote")
    p.expect_matches("L09-roadmap.txt", p.read(".w2c/ROADMAP.md"))
    p.expect_matches("L09-state.txt", p.read(".w2c/STATE.md"))


def l10_classic_cycle(p: Project) -> None:
    wt = Path(p.state["worktree"])
    nxt = p.w2c("next", cwd=wt)
    p.expect_tokens(nxt, "NEXT M002 S01 T01 — Add subtract to the calculator")
    p.expect_matches("L10-next.txt", nxt.stdout)
    d = plan_dir(p, "M002", "add-subtract", wt)
    p.write("app/calc.py", CALC_SUBTRACT, cwd=wt)
    p.write("tests/test_calc.py", TEST_SUBTRACT, cwd=wt)
    p.run(["python3", "-m", "unittest", "discover", "-s", "tests", "-t", "."], cwd=wt)
    refused = p.w2c("complete", "--milestone", "M002", "--slice", "S01", "--task", "T01", cwd=wt, check=False)
    if refused.returncode == 0:
        raise AssertionError("classic complete needs a summary")
    p.expect_tokens(refused, "missing report S01-T01-SUMMARY.md")
    write_task_report(p, d, "S01", "T01")
    first = p.w2c("complete", "--milestone", "M002", "--slice", "S01", "--task", "T01", cwd=wt)
    p.expect_tokens(first, "complete M002 S01 T01", "OPEN_IN_SLICE 1")
    p.expect_tokens(p.read(d / "M002-S01-PLAN.md"), "- [x] **T01**")
    p.write("README.md", "# Dummy calculator\n\nThe calculator can add, multiply and subtract.\n", cwd=wt)
    p.run(["grep", "-q", "subtract", "README.md"], cwd=wt)
    write_task_report(p, d, "S01", "T02")
    second = p.w2c("complete", "--milestone", "M002", "--slice", "S01", "--task", "T02", cwd=wt)
    p.expect_tokens(second, "complete M002 S01 T02", "NEED_SLICE_REPORTS S01")
    write_slice_reports(p, d, "S01")
    p.expect_tokens(p.w2c("slice-complete", "--milestone", "M002", "--slice", "S01", cwd=wt), "slice-complete M002 S01")
    write_milestone_reports(p, d, "M002")
    done = p.w2c("milestone-complete", "M002", cwd=wt)
    p.expect_matches("L10-milestone-complete.txt", done.stdout)
    p.git("add", "app", "tests", "README.md", cwd=wt)
    p.git("commit", "-q", "-m", "Add subtract to the calculator.", cwd=wt)
    p.git("push", "-u", "origin", "DEMO-2", cwd=wt)
    if remote_sha(p, "DEMO-2") != head(p, wt):
        raise AssertionError("remote DEMO-2 does not match the worktree commit")
    p.w2c("ledger-bind", cwd=wt)
    road = p.read(".w2c/ROADMAP.md")
    if road.count("✅") != 2:
        raise AssertionError(f"both milestones should be DONE in the shared ledger:\n{road}")
    p.expect_matches("L10-roadmap.txt", road)
    full = p.w2c("smoke")
    if "FAIL" in full.stdout:
        raise AssertionError(full.stdout)
    p.expect_tokens(p.w2c("next"), "NEXT none")


def l11_trials(p: Project) -> None:
    proc = p.w2c("trials")
    p.expect_tokens(proc, "work-to-chores PASS", "do-chores PASS")


STAGES = [
    Stage("L01", "install", l01_install),
    Stage("L02", "init with slice-commit-milestone-push-pr", l02_init),
    Stage("L03", "milestone-new in OpenSpec mode and smoke", l03_milestone),
    Stage("L04", "decide, context-new and reorder", l04_decide_context_reorder),
    Stage("L05", "branch mode with base-dirt and worktree mode", l05_branch_and_worktree),
    Stage("L06", "next, complete and slice-complete", l06_next_complete_slice),
    Stage("L07", "commit and push through the pre-push hook", l07_commit_and_push),
    Stage("L08", "amendment", l08_amendment),
    Stage("L09", "closeout, archive and push", l09_closeout),
    Stage("L10", "classic milestone full cycle in a worktree", l10_classic_cycle),
    Stage("L11", "trials", l11_trials),
]

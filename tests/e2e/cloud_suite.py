"""Stages that run the opt-in cloud mode on a dummy project.

Stored outputs live under tests/e2e/expected/cloud/.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from w2c.cloud import layout
from w2c.openspec import CONFIG_RULES_SNIPPET as LEGACY_RULES

from tests.e2e.harness import APP_CALC, APP_TEST, REPO, Project, Stage
from tests.e2e.legacy_suite import tree

CHANGE = "add-multiply"
BRANCH = "DEMO-1"
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


def filled_design(folder: Path) -> str:
    """The design.md `w2c cloud new` wrote in `folder`, every Delivery Plan row filled."""
    values = {
        "Isolation mode": "branch", "Local branch": BRANCH, "Remote branch": BRANCH,
        "Worktree skill": "n/a", "Base dirt policy": "clean-at-plan", "Manual test guide": "no",
    }

    def fill(match: re.Match) -> str:
        field, current = match.group(1), match.group(2).strip()
        return f"| {field} | {values.get(field, current or 'none')} |"

    text = (folder / "design.md").read_text(encoding="utf-8")
    return re.sub(
        r"^\| ([^|]+?) \|([^|\n]*)\|$",
        lambda m: m.group(0) if m.group(1) in ("Field", "---") else fill(m),
        text, flags=re.M,
    )


def filled_tasks(p: Project, folder: Path) -> str:
    """The tasks.md `w2c cloud new` wrote in `folder`, then one group per slice from
    `w2c cloud template slice-group`."""
    out = [(folder / "tasks.md").read_text(encoding="utf-8").rstrip("\n") + "\n\n"]
    template = p.w2c("cloud", "template", "slice-group").stdout
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
    p.expect_files("openspec/knowledge.md", ".gitattributes", f"openspec/changes/{CHANGE}/design.md",
                   f"openspec/changes/{CHANGE}/tasks.md")
    p.expect_tokens(p.read(".gitattributes"), "openspec/knowledge.md merge=union")
    no_local_files(p)
    change = change_dir(p)
    p.write(change / "proposal.md", PROPOSAL)
    p.write(change / "design.md", filled_design(change))
    p.write(change / "specs" / "calc-multiply" / "spec.md", SPEC)
    p.write(change / "tasks.md", filled_tasks(p, change))
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
    dirty = p.w2c("cloud", "archive", CHANGE, check=False)
    if dirty.returncode == 0:
        raise AssertionError("archive should be refused while .delivery/ is not committed")
    p.expect_tokens(dirty, f"REPORTS_UNCOMMITTED {CHANGE}", f"openspec/changes/{CHANGE}/.delivery/SUMMARY.md")
    p.git("add", "openspec")
    p.git("commit", "-q", "-m", "Finish the multiply change with its reports.")
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

    held = p.w2c("cloud", "decide", "--scope", "export", "--decision", "Format",
                 "--choice", "csv | json", "--rationale", "simple", "--when", "2026-01-01")
    p.expect_tokens(held, "PENDING")
    held = p.w2c("cloud", "decide", "--scope", "export", "--decision", "Limit",
                 "--choice", "none", "--rationale", "later", "--when", "2026-01-01")
    p.expect_tokens(held, "PENDING")
    p.w2c("cloud", "new", "--slug", first)
    p.w2c("cloud", "new", "--slug", second)
    first_design = p.root / "openspec" / "changes" / first / "design.md"
    written = first_design.read_text(encoding="utf-8")
    first_design.unlink()
    early = p.w2c("cloud", "decisions-flush", "--change", first, check=False)
    if early.returncode == 0:
        raise AssertionError("flush should be refused without a design")
    first_design.write_text(written, encoding="utf-8")
    for name in (first, second):
        folder = p.root / "openspec" / "changes" / name
        p.write(folder / "design.md", filled_design(folder))
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
    if (p.root / ".w2c" / "runtime" / "pending-decisions.jsonl").exists():
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


def c06_amendments(p: Project) -> None:
    name = "amend-demo"
    folder = p.root / "openspec" / "changes" / name
    p.w2c("cloud", "new", "--slug", name)
    p.write(folder / "proposal.md", PROPOSAL.replace("calc-multiply", "calc-divide").replace("multiply", "divide"))
    p.write(folder / "design.md", filled_design(folder))
    p.write(folder / "specs" / "calc-divide" / "spec.md",
            SPEC.replace("Multiply two numbers", "Divide two numbers").replace("multiplies 3 by 4", "divides 12 by 4")
            .replace("product", "quotient").replace("is 12", "is 3").replace("Multiplying", "Dividing"))
    p.write(folder / "tasks.md", filled_tasks(p, folder).replace("multiply", "divide").replace("Multiply", "Divide"))
    p.w2c("cloud", "status-set", name, "INPROGRESS")
    refused = p.w2c("cloud", "amend-begin", "--change", name, "--decision", "D1", check=False)
    if refused.returncode == 0:
        raise AssertionError("amend-begin should be refused for a decision that is not logged")
    p.expect_tokens(refused, "decision D1 not found")
    p.w2c("cloud", "decide", "--change", name, "--scope", "amend", "--decision", "Drop one task",
          "--choice", "drop and add", "--rationale", "scope changed", "--when", "2026-01-01")
    begin = p.w2c("cloud", "amend-begin", "--change", name, "--decision", "D1")
    p.expect_matches("C06-begin.txt", begin.stdout)
    meta = p.read(f"openspec/changes/{name}/.openspec.yaml")
    p.expect_tokens(meta, "x-delivery-status: PAUSED", "x-delivery-amend-lock: D1",
                    "x-delivery-amend-prior-status: INPROGRESS", "x-delivery-amend-decision: D1")
    locked = p.w2c("cloud", "next", "--change", name, check=False)
    p.expect_tokens(locked, f"AMEND_LOCK {name}")
    dropped = p.w2c("cloud", "drop-task", "--change", name, "--slice", "S01", "--task", "T02",
                    "--reason", "tests ship with the code", "--decision", "D1")
    p.expect_matches("C06-drop-task.txt", dropped.stdout)
    added = p.w2c("cloud", "task-add", "--change", name, "--slice", "S01", "--title", "Check division by zero",
                  "--verify", VERIFY, "--reason", "found while planning", "--decision", "D1")
    p.expect_matches("C06-task-add.txt", added.stdout)
    ended = p.w2c("cloud", "amend-end", "--change", name)
    p.expect_matches("C06-end.txt", ended.stdout)
    meta = p.read(f"openspec/changes/{name}/.openspec.yaml")
    p.expect_tokens(meta, "x-delivery-status: PAUSED")
    if "amend-" in meta:
        raise AssertionError(f"amend keys remain after amend-end:\n{meta}")
    records = p.w2c("cloud", "amendments", "--change", name)
    p.expect_matches("C06-amendments.txt", records.stdout)
    design = p.read(f"openspec/changes/{name}/design.md")
    p.expect_matches("C06-design-amendments.txt", design[design.index("## Amendments"):])
    tasks = p.read(f"openspec/changes/{name}/tasks.md")
    p.expect_tokens(tasks, "- [d] 1.2", "- [ ] 1.3 Check division by zero")
    p.expect_matches("C06-tasks.txt", tasks[tasks.index("## 1."):tasks.index("## 2.")])
    no_local_files(p)


def c07_push_guard(p: Project) -> None:
    name = "ship-negate"
    folder = p.root / "openspec" / "changes" / name
    p.w2c("cloud", "new", "--slug", name)
    hook = p.read(".git/hooks/pre-push")
    p.expect_tokens(hook, "# w2c-hook: openspec-archive")
    p.write(folder / "proposal.md", PROPOSAL.replace("calc-multiply", "calc-negate").replace("multiply", "negate"))
    p.write(folder / "design.md", filled_design(folder))
    p.write(folder / "specs" / "calc-negate" / "spec.md",
            SPEC.replace("calc-multiply", "calc-negate").replace("Multiply two numbers", "Negate a number")
            .replace("multiplies 3 by 4", "negates 5").replace("product of two numbers", "opposite of a number")
            .replace("is 12", "is -5").replace("Multiplying two integers", "Negating an integer"))
    p.write(folder / "tasks.md", filled_tasks(p, folder).replace("multiply", "negate").replace("Multiply", "Negate"))
    p.w2c("cloud", "status-set", name, "TODO")

    def note(file: str) -> None:
        p.write(folder / ".delivery" / file, f"# {file}\n\nDone and checked.\n")

    for sid, tids in (("S01", ("T01", "T02")), ("S02", ("T01",))):
        for tid in tids:
            note(f"{sid}-{tid}-SUMMARY.md")
            p.w2c("cloud", "complete", "--change", name, "--slice", sid, "--task", tid)
        note(f"{sid}-UAT.md")
        note(f"{sid}-SUMMARY.md")
        p.w2c("cloud", "slice-complete", "--change", name, "--slice", sid)
    p.git("add", "openspec", ".gitattributes")
    p.git("commit", "-q", "-m", "Finish the negate change.")
    sha = p.git("rev-parse", "HEAD").stdout.strip()
    check = p.w2c("openspec-push-check", "--local-ref", f"refs/heads/{BRANCH}", "--local-sha", sha, check=False)
    if check.returncode == 0:
        raise AssertionError("push check must fail while the finished cloud change is not archived")
    p.expect_tokens(check, f"{name}: archive the change with w2c cloud archive {name} before push")
    p.expect_matches("C07-push-check-fail.txt", check.stderr)
    blocked = p.git("push", "-u", "origin", BRANCH, check=False)
    if blocked.returncode == 0:
        raise AssertionError("the pre-push hook must refuse an unarchived finished cloud change")
    p.expect_tokens(blocked.stdout + blocked.stderr, f"w2c cloud archive {name}")
    if p.git("ls-remote", "origin", BRANCH).stdout.strip():
        raise AssertionError("refused push still reached the remote")
    note("VALIDATION.md")
    note("SUMMARY.md")
    p.git("add", "openspec")
    p.git("commit", "-q", "-m", "Add the negate closeout notes.")
    arch = p.w2c("cloud", "archive", name)
    p.expect_tokens(arch, f"archived {name} as")
    p.git("add", "openspec")
    p.git("commit", "-q", "-m", "Archive the negate change.")
    sha = p.git("rev-parse", "HEAD").stdout.strip()
    ok = p.w2c("openspec-push-check", "--local-ref", f"refs/heads/{BRANCH}", "--local-sha", sha)
    if ok.stderr.strip():
        raise AssertionError(ok.stderr)
    p.git("push", "-u", "origin", BRANCH)
    if p.git("ls-remote", "origin", BRANCH).stdout.split()[0] != sha:
        raise AssertionError("archived push did not reach the remote")
    no_local_files(p)


def plan_change(p: Project, name: str, word: str) -> Path:
    """A planned change for `word` (square, cube) from the templates, status TODO."""
    folder = p.root / "openspec" / "changes" / name
    p.w2c("cloud", "new", "--slug", name)
    cap = f"calc-{word}"
    p.write(folder / "proposal.md", PROPOSAL.replace("calc-multiply", cap).replace("multiply", word))
    p.write(folder / "design.md", filled_design(folder))
    p.write(folder / "specs" / cap / "spec.md",
            SPEC.replace("Multiply two numbers", f"{word.title()} a number")
            .replace("multiplies 3 by 4", f"asks for the {word} of 3")
            .replace("product of two numbers", f"{word} of a number")
            .replace("is 12", "is right").replace("Multiplying two integers", f"Taking the {word} of an integer"))
    p.write(folder / "tasks.md", filled_tasks(p, folder).replace("multiply", word).replace("Multiply", word.title()))
    p.w2c("cloud", "status-set", name, "TODO")
    return folder


def _code(word: str, power: int) -> dict[tuple[str, str], tuple[str, str]]:
    test = (
        f"import unittest\n\nfrom app.{word} import {word}\n\n\n"
        f"class {word.title()}Tests(unittest.TestCase):\n"
        f"    def test_{word}(self) -> None:\n"
        f"        self.assertEqual({word}(3), {3 ** power})\n"
    )
    return {
        ("S01", "T01"): (f"app/{word}.py", f"def {word}(x):\n    return x ** {power}\n"),
        ("S01", "T02"): (f"tests/test_{word}.py", test),
        ("S02", "T01"): (f"docs/{word}.md", f"# {word.title()}\n\nCall {word}(x).\n"),
    }


def drive(p: Project, cwd: Path, env: dict[str, str], name: str, code: dict, stop_at: str | None = None,
          answers: dict[str, str] | None = None) -> tuple[list[str], dict]:
    """Run a change using only `w2c cloud step` output: read the action, perform it
    with the real commands, record the result, ask again."""
    answers = answers or {}
    exe = str(p.home / ".local" / "bin" / "w2c")

    def w2c(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run([exe, *args], cwd=str(cwd), env=env, capture_output=True, text=True)
        if check and proc.returncode != 0:
            raise AssertionError(f"w2c {' '.join(args)} exited {proc.returncode}\n{proc.stdout}{proc.stderr}")
        return proc

    def git(*args: str) -> None:
        proc = subprocess.run(["git", "-C", str(cwd), *args], env=env, capture_output=True, text=True)
        if proc.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} exited {proc.returncode}\n{proc.stdout}{proc.stderr}")

    log: list[str] = []
    seen: set[str] = set()
    for _ in range(120):
        step = json.loads(w2c("cloud", "step", "--json").stdout)
        action, sid, tid = step["action"], step["slice"], step["task"]
        log.append(f"{action} {step['change']} {sid or '-'} {tid or '-'}"
                   + (f" reason={step['reason']}" if step["reason"] else ""))
        if action == stop_at or action in ("done", "stop"):
            return log, step
        seen.add(action)
        result = "pass"
        if action == "smoke":
            result = "pass" if w2c("cloud", "smoke", "--change", name, check=False).returncode == 0 else "fail"
        elif action == "isolate":
            git("switch", "-q", BRANCH)
        elif action == "implement":
            p.state.setdefault(f"brief-{name}", w2c("cloud", "brief").stdout)
            rel, text = code[(sid, tid)]
            p.write(cwd / rel, text)
        elif action == "verify":
            line = w2c("cloud", "brief").stdout.rstrip("\n").splitlines()[-1]
            command = line.split("Verify:", 1)[1].strip()
            ran = subprocess.run(command, shell=True, cwd=str(cwd), env=env, capture_output=True, text=True)
            result = "pass" if ran.returncode == 0 else "fail"
        elif action in ("write-report", "slice-reports", "milestone-reports"):
            for rel in step["files"]:
                p.write(cwd / rel, f"# {Path(rel).name}\n\nDone and checked.\n")
        elif action == "complete":
            w2c("cloud", "complete", "--change", name, "--slice", sid, "--task", tid)
        elif action == "slice-complete":
            w2c("cloud", "slice-complete", "--change", name, "--slice", sid)
        elif action.startswith("ask-"):
            result = answers.get(action, "yes")
            if action == "ask-archive" and result == "yes":
                w2c("cloud", "archive", name)
                w2c("cloud", "milestone-complete", name)
            elif action == "ask-commit" and result == "yes":
                git("add", "-A", "--", *[d for d in ("openspec", "app", "tests", "docs") if (cwd / d).exists()])
                if sid:
                    title = f"Deliver {name} {sid}."
                elif "ask-archive" in seen:
                    title = f"Archive {name}."
                else:
                    title = f"Finish {name} with its reports."
                git("commit", "-q", "-m", title)
            elif action == "ask-push" and result == "yes":
                git("push", "-q", "-u", "origin", BRANCH)
        w2c("cloud", "step", "--record", action, "--result", result)
    raise AssertionError(f"step never finished:\n" + "\n".join(log))


def c08_step_driver(p: Project) -> None:
    name = "add-square"
    plan_change(p, name, "square")
    env = dict(p.env)
    env["W2C_EPHEMERAL"] = "0"
    log, last = drive(p, p.root, env, name, _code("square", 2), answers={"ask-pr": "no"})
    if last["action"] != "done":
        raise AssertionError("milestone did not finish:\n" + "\n".join(log))
    text = "\n".join(log) + "\n"
    for token in ("smoke", "implement", "verify", "review", "write-report", "complete",
                  "slice-reports", "slice-complete", "milestone-reports", "ask-commit",
                  "ask-archive", "ask-push", "ask-pr"):
        p.expect_tokens(text, token + " " + name)
    p.expect_matches("C08-steps.txt", text)
    p.expect_tokens(p.state[f"brief-{name}"], "## Delivery Plan", "## Guardrails", "## Commit and PR Conventions",
                    "**Goal:** goal for Square", "- [ ] 1.1 Add square", "  - Verify: " + VERIFY)
    p.expect_matches("C08-brief.txt", p.state[f"brief-{name}"])
    archived = list((p.root / "openspec" / "changes" / "archive").glob(f"*-{name}"))
    if not archived:
        raise AssertionError(f"{name} was not archived")
    p.expect_tokens(archived[0].joinpath("tasks.md").read_text(encoding="utf-8"), "- [x] 1.1", "- [x] 1.2", "- [x] 2.1")
    for report in ("VALIDATION.md", "SUMMARY.md", "S01-UAT.md", "S02-SUMMARY.md"):
        rel = f"openspec/changes/{name}/.delivery/{report}"
        if not p.git("log", "--format=%s", "--", rel).stdout.strip():
            raise AssertionError(f"git history does not keep {rel}")
    titles = p.git("log", "--format=%s").stdout
    p.expect_tokens(titles, f"Finish {name} with its reports.", f"Archive {name}.")
    head = p.git("rev-parse", "HEAD").stdout.strip()
    if p.git("ls-remote", "origin", BRANCH).stdout.split()[0] != head:
        raise AssertionError("the driven milestone did not reach the remote")
    if p.git("status", "--porcelain", "--", "openspec", "app", "tests", "docs").stdout.strip():
        raise AssertionError("the driven milestone left uncommitted product files")
    p.expect_tokens(p.read(".git/w2c/step.json"), f'"change": "{name}"')
    if (p.root / ".w2c" / "runtime" / "step.json").exists():
        raise AssertionError("step state must live in the git directory, not under .w2c/")
    no_local_files(p)


def c09_fresh_clone_push(p: Project) -> None:
    name = "add-cube"
    plan_change(p, name, "cube")
    p.git("add", "-A", "openspec")
    p.git("commit", "-q", "-m", "Plan the cube change.")
    p.git("push", "-q", "origin", BRANCH)
    clone = p.root.parent / "fresh-clone"
    p.run(["git", "clone", "-q", "-b", BRANCH, str(p.remote), str(clone)], cwd=p.root.parent)
    if (clone / ".w2c").exists():
        raise AssertionError("a fresh clone must not hold .w2c/")
    env = dict(p.env)
    env["W2C_EPHEMERAL"] = "1"
    log, last = drive(p, clone, env, name, _code("cube", 3), stop_at="ask-push")
    if (last["action"], last["slice"]) != ("ask-push", "S01") or log[-2:] != [
        f"ask-commit {name} S01 -", f"ask-push {name} S01 -"
    ]:
        raise AssertionError("a temporary container must ask to push after the slice commit:\n"
                             + "\n".join(log))
    if p.git("log", "-1", "--format=%s", cwd=clone).stdout.strip() != f"Deliver {name} S01.":
        raise AssertionError("the slice commit was not made in the clone")
    p.expect_matches("C09-steps.txt", "\n".join(log) + "\n")


# ---------------------------------------------------------------- conversion

OPENSPEC_TEMPLATES = REPO / "templates" / "openspec"
CADENCE = "slice-commit-milestone-push-pr"


def _fill(text: str, field: str, value: str) -> str:
    return re.sub(rf"(?m)^\| {re.escape(field)} \| [^|\n]*\|$", f"| {field} | {value} |", text)


def legacy_roadmap(mid: str, slug: str, word: str, marks: tuple[str, str], archive: str = "") -> str:
    """A 2.2 OpenSpec milestone roadmap from the 2.2 template, every field filled."""
    text = (OPENSPEC_TEMPLATES / "M-ROADMAP.md").read_text(encoding="utf-8")
    text = text.format(mid=mid, title=slug.replace("-", " "), slug=slug)
    slices = f"- [{marks[0]}] **S01: {word.title()}**\n- [{marks[1]}] **S02: Documentation**\n"
    text = text.replace("**Vision:**", f"**Vision:** People take the {word} power of a number.")
    text = text.replace("## Success Criteria\n", f"## Success Criteria\n\n- {word}(3) returns the right value.\n")
    text = text.replace("## Boundary Map\n", slices + "\n## Boundary Map\n\n- app/ and docs/ only.\n")
    text = text.replace("## In scope\n", f"## In scope\n\n- A {word} function and its docs.\n")
    text = text.replace("## Out of scope\n", "## Out of scope\n\n- Other powers.\n")
    for field, value in (
        ("Isolation mode", "branch"), ("Local branch", BRANCH), ("Remote branch", BRANCH),
        ("Worktree skill", "n/a"), ("Base dirt policy", "clean-at-plan"),
        ("Validation commands", VERIFY), ("OpenSpec archive", archive),
    ):
        text = _fill(text, field, value)
    text = text.replace("**Commit title:**", "**Commit title:** short imperative subject.")
    text = text.replace("**Commit body:**", "**Commit body:** optional, after a blank line.")
    text = text.replace("**Pull request:**", "**Pull request:** one per change.")
    return text


def legacy_slice_plan(mid: str, sid: str, title: str, word: str) -> str:
    text = (OPENSPEC_TEMPLATES / "M-S-PLAN.md").read_text(encoding="utf-8")
    text = text.replace("MXXX", mid).replace("SXX", sid).replace("TITLE", title)
    text = text.replace("**Goal:**", f"**Goal:** {title} for {word}.")
    text = text.replace("**Demo:**", f"**Demo:** run the {word} check.")
    for field, value in (
        ("Must-Haves", f"- {word} works for integers."), ("Threat Surface", "- None; pure function."),
        ("Proof Level", "- Unit test."), ("Integration Closure", "- Exported from app/."),
        ("Files Likely Touched", f"- app/{word}.py"),
    ):
        text = text.replace(f"## {field}\n", f"## {field}\n\n{value}\n")
    for field, value in (("Isolation mode", "branch"), ("Local branch", BRANCH), ("Remote branch", BRANCH),
                         ("Base dirt policy", "clean-at-plan")):
        text = _fill(text, field, value)
    text = text.replace("**Commit title:**", "**Commit title:** short imperative subject.")
    text = text.replace("**Commit body:**", "**Commit body:** optional, after a blank line.")
    text = text.replace("**Pull request:**", "**Pull request:** one per change.")
    return text


def legacy_tasks(word: str, done: tuple[bool, ...] = (False, False, False)) -> str:
    marks = ["x" if flag else " " for flag in done]
    return (
        f"# Tasks\n\n## 1. {word.title()}\n\n"
        f"- [{marks[0]}] 1.1 Add {word} to the calculator\n  - Verify: {VERIFY}\n"
        f"- [{marks[1]}] 1.2 Test {word}\n  - Verify: {VERIFY}\n\n"
        f"## 2. Documentation\n\n- [{marks[2]}] 2.1 Document {word} in the README\n  - Verify: {VERIFY}\n"
    )


def side_project(p: Project, name: str) -> Project:
    """A fresh 2.2 OpenSpec project next to the cloud one, with its own remote."""
    q = Project(root=p.tmp / name, remote=p.tmp / f"{name}.git", home=p.home, env=p.env, tmp=p.tmp,
                suite=p.suite)
    q.root.mkdir(parents=True)
    for rel, text in (("app/__init__.py", ""), ("tests/__init__.py", ""), ("app/calc.py", APP_CALC),
                      ("tests/test_calc.py", APP_TEST), ("README.md", "# Dummy calculator\n")):
        q.write(rel, text)
    q.git("init", "-q", "-b", "main")
    q.git("add", "-A")
    q.git("commit", "-q", "-m", "initial calculator")
    q.run(["git", "init", "-q", "--bare", "-b", "main", str(q.remote)], cwd=p.tmp)
    q.git("remote", "add", "origin", str(q.remote))
    q.git("push", "-q", "-u", "origin", "main")
    q.w2c("init", "--git-delivery", CADENCE)
    q.expect_tokens(q.read(".w2c/config.toml"), 'planning = "openspec"')
    q.run(["openspec", "init", "--tools", "none", "--no-animation", "--no-copilot-cloud", "."])
    cfg = q.root / "openspec" / "config.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8").rstrip() + "\n\n" + LEGACY_RULES, encoding="utf-8")
    q.git("switch", "-q", "-c", BRANCH)
    return q


def plan_legacy(q: Project, slug: str, word: str, *, status: str = "", marks: tuple[str, str] = (" ", " "),
                done: tuple[bool, ...] = (False, False, False), archive: str = "") -> str:
    """Plan one milestone the 2.2 way: milestone-new, then the filled plan files."""
    made = q.w2c("milestone-new", "--slug", slug)
    mid = re.search(r"\((M\d+)\)", made.stdout).group(1)
    plan = q.root / ".w2c" / "plans" / f"{mid}-{slug}"
    q.write(plan / f"{mid}-ROADMAP.md", legacy_roadmap(mid, slug, word, marks, archive))
    q.write(plan / f"{mid}-S01-PLAN.md", legacy_slice_plan(mid, "S01", word.title(), word))
    q.write(plan / f"{mid}-S02-PLAN.md", legacy_slice_plan(mid, "S02", "Documentation", word))
    change = q.root / "openspec" / "changes" / slug
    cap = f"calc-{word}"
    q.write(change / "proposal.md", PROPOSAL.replace("calc-multiply", cap).replace("multiply", word))
    q.write(change / "design.md",
            f"# Design\n\n## Context\n\nSee proposal.md.\n\n## Decisions\n\n- One function for {word}.\n")
    q.write(change / "specs" / cap / "spec.md",
            SPEC.replace("Multiply two numbers", f"{word.title()} a number")
            .replace("multiplies 3 by 4", f"asks for the {word} power of 3")
            .replace("product of two numbers", f"{word} power of a number")
            .replace("is 12", "is right").replace("Multiplying two integers", f"Taking the {word} power"))
    q.write(change / "tasks.md", legacy_tasks(word, done))
    if status:
        q.w2c("milestone-status", mid, status)
    return mid


def ledger_bytes(q: Project) -> dict[str, bytes]:
    """Every file under the checkout (not .git) and in the ledger, by path."""
    found: dict[str, bytes] = {}
    for base, label in ((q.root, ""), ((q.root / ".w2c").resolve(), ".w2c/")):
        for dirpath, dirs, files in __import__("os").walk(base):
            dirs[:] = [d for d in dirs if d != ".git"]
            for name in files:
                path = Path(dirpath) / name
                found[label + path.relative_to(base).as_posix()] = path.read_bytes()
    return found


def c10_mixed_repo(p: Project) -> None:
    q = side_project(p, "mixed")
    m1 = plan_legacy(q, "add-fourth", "fourth")
    m2 = plan_legacy(q, "add-fifth", "fifth", status="TODO")
    if (m1, m2) != ("M001", "M002"):
        raise AssertionError(f"unexpected ids {m1} {m2}")
    for mid in (m1, m2):
        smoke = q.w2c("smoke", "--milestone", mid)
        if "FAIL" in smoke.stdout:
            raise AssertionError(smoke.stdout)
    q.git("add", "-A")
    q.git("commit", "-q", "-m", "Plan two milestones.")
    before = q.w2c("next").stdout
    p.expect_tokens(before, "NEXT M001 S01 T01 — Add fourth to the calculator")
    dry = q.w2c("cloud", "migrate", "--milestone", "M002", "--dry-run")
    p.expect_tokens(dry, "NEXT_BEFORE M002 S01 T01", "NEED_CONFIG_APPROVAL openspec/config.yaml", "DRY_RUN")
    if q.git("status", "--porcelain").stdout.strip():
        raise AssertionError("dry run changed files")
    p.expect_matches("C10-dry-run.txt", dry.stdout)
    done = q.w2c("cloud", "migrate", "--milestone", "M002", "--yes-config", "--yes-rewrites")
    p.expect_tokens(done, "CONVERTED M002 -> add-fifth", "COMMIT", "openspec/changes/add-fifth/design.md")
    if "PENDING_EDIT" in done.stdout or "MANUAL_EDIT" in done.stdout:
        raise AssertionError(done.stdout)
    p.expect_matches("C10-migrate.txt", done.stdout)
    if q.git("rev-parse", "HEAD").stdout == "" or q.git("diff", "--cached", "--name-only").stdout.strip():
        raise AssertionError("migrate staged files")
    after = q.w2c("next")
    if after.stdout != before:
        raise AssertionError(f"w2c next changed after conversion:\n{before}--\n{after.stdout}")
    p.expect_matches("C10-next.txt", after.stdout)
    moved = q.w2c("next", "--milestone", "M002")
    p.expect_tokens(moved, "CLOUD_MOVED M002 add-fifth")
    p.expect_matches("C10-cloud-moved.txt", moved.stdout)
    plan = q.root / ".w2c" / "plans" / "M001-add-fourth"
    q.write(plan / "S01-T01-SUMMARY.md", "# T01\n\n## What Happened\n\ndone\n")
    ran = q.w2c("complete", "--milestone", "M001", "--slice", "S01", "--task", "T01")
    p.expect_tokens(ran, "complete M001 S01 T01")
    p.expect_tokens(q.w2c("next"), "NEXT M001 S01 T02")
    p.expect_tokens(q.w2c("next-milestone-id"), "M003")
    smoke = q.w2c("cloud", "smoke", "--change", "add-fifth")
    if "FAIL" in smoke.stdout:
        raise AssertionError(smoke.stdout)
    q.git("add", "-A", "--", "openspec", ".gitattributes")
    q.git("commit", "-q", "-m", "Move the fifth milestone to a cloud change.")
    q.git("push", "-q", "-u", "origin", BRANCH)
    clone = p.tmp / "mixed-clone"
    q.run(["git", "clone", "-q", "-b", BRANCH, str(q.remote), str(clone)], cwd=p.tmp)
    if (clone / ".w2c").exists():
        raise AssertionError("a fresh clone must not hold .w2c/")
    env = dict(p.env)
    env["W2C_EPHEMERAL"] = "0"
    log, last = drive(q, clone, env, "add-fifth", _code("fifth", 5), answers={"ask-pr": "no"})
    if last["action"] != "done":
        raise AssertionError("the converted change did not finish:\n" + "\n".join(log))
    p.expect_matches("C10-steps.txt", "\n".join(log) + "\n")
    if not list((clone / "openspec" / "changes" / "archive").glob("*-add-fifth")):
        raise AssertionError("add-fifth was not archived in the clone")


def c11_convert_all_and_restore(p: Project) -> None:
    q = side_project(p, "all-statuses")
    plan_legacy(q, "add-sixth", "sixth", marks=("x", "x"), done=(True, True, True))
    d1 = q.root / ".w2c" / "plans" / "M001-add-sixth"
    q.write(d1 / "M001-VALIDATION.md", "# Milestone Validation: M001\n\nverdict: pass\n")
    q.write(d1 / "M001-SUMMARY.md", "# M001\n\n## What Happened\n\nok\n")
    q.w2c("milestone-complete", "M001", "--archive-declined")
    plan_legacy(q, "add-seventh", "seventh", status="INPROGRESS", done=(True, False, False))
    q.write(q.root / ".w2c" / "plans" / "M002-add-seventh" / "S01-T01-SUMMARY.md", "# T01\n\ndone\n")
    plan_legacy(q, "add-eighth", "eighth", status="PAUSED")
    plan_legacy(q, "add-ninth", "ninth", status="TODO")
    plan_legacy(q, "add-tenth", "tenth", status="STOP")
    for scope, choice in (("M002", "Use pow"), ("project", "Keep the module small")):
        q.w2c("decide", "--scope", scope, "--decision", f"Rule for {scope}", "--choice", choice,
              "--rationale", "simple", "--when", "2026-11-02")
    q.git("add", "-A")
    q.git("commit", "-q", "-m", "Plan five milestones.")
    before = ledger_bytes(q)
    done = q.w2c("cloud", "migrate", "--all", "--yes-config", "--yes-rewrites")
    for mid, name in (("M001", "add-sixth"), ("M002", "add-seventh"), ("M003", "add-eighth"),
                      ("M004", "add-ninth"), ("M005", "add-tenth")):
        p.expect_tokens(done, f"CONVERTED {mid} -> {name}")
    p.expect_tokens(done, "openspec/decisions.md")
    p.expect_matches("C11-migrate.txt", done.stdout)
    for name in ("ROADMAP.md", "STATE.md", "QUEUE.md", "DECISIONS.md", "contexts"):
        if (q.root / ".w2c" / name).exists():
            raise AssertionError(f".w2c/{name} should be retired")
    frozen = q.read("openspec/decisions.md")
    p.expect_tokens(frozen, "Rule for project")
    meta = q.read("openspec/changes/add-seventh/.openspec.yaml")
    p.expect_tokens(meta, "x-delivery-legacy-id: M002", "x-delivery-status: INPROGRESS")
    p.expect_tokens(q.read("openspec/changes/add-seventh/design.md"), "| D001 |", "Rule for M002")
    p.expect_tokens(q.w2c("cloud", "next", "--change", "M002"), "NEXT add-seventh S01 T02")
    smoke = q.w2c("cloud", "smoke")
    if "FAIL" in smoke.stdout:
        raise AssertionError(smoke.stdout)
    again = q.w2c("cloud", "migrate", "--all", "--yes-config", "--yes-rewrites")
    p.expect_tokens(again, "NOTHING_TO_CONVERT")
    proposal = q.root / "openspec" / "changes" / "add-ninth" / "proposal.md"
    kept = proposal.read_bytes()
    proposal.write_bytes(kept + b"\nA later edit.\n")
    refused = q.w2c("cloud", "migrate", "--restore", check=False)
    if refused.returncode != 1:
        raise AssertionError(f"restore over a later edit must be refused:\n{refused.stdout}")
    p.expect_tokens(refused, f"CHANGED_SINCE_RUN {proposal}", "RESTORE_REFUSED 1 file(s)")
    if proposal.read_bytes() != kept + b"\nA later edit.\n":
        raise AssertionError("a refused restore changed a file")
    proposal.write_bytes(kept)
    restored = q.w2c("cloud", "migrate", "--restore")
    p.expect_tokens(restored, "RESTORED")
    p.expect_matches("C11-restore.txt", restored.stdout)
    after = ledger_bytes(q)
    if after != before:
        changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        raise AssertionError(f"restore is not byte for byte: {changed}")
    if q.git("status", "--porcelain").stdout.strip():
        raise AssertionError(q.git("status", "--porcelain").stdout)
    p.expect_tokens(q.w2c("cloud", "migrate", "--restore"), "NOTHING_TO_RESTORE")


SKILLS = ("work-to-chores", "do-chores", "work-to-chores-cloud", "do-chores-cloud")


def c12_trials_and_skills(p: Project) -> None:
    proc = p.w2c("trials")
    p.expect_tokens(proc, *(f"{name} PASS" for name in SKILLS))
    p.expect_matches("C12-trials.txt", proc.stdout)
    lines = []
    for name in SKILLS:
        installed = p.home / ".agents" / "skills" / name
        for file in ("SKILL.md", "USAGE.md", "trials.json", "SKILL.copilot.md"):
            if (installed / file).read_bytes() != (REPO / "skills" / name / file).read_bytes():
                raise AssertionError(f"installed {name}/{file} differs from the repo copy")
        for hub in (".claude", ".cursor"):
            link = p.home / hub / "skills" / name
            lines.append(f"{hub}/skills/{name} {'linked' if link.resolve() == installed.resolve() else 'MISSING'}")
    p.expect_matches("C12-installed.txt", "\n".join(lines) + "\n")
    copilot = []
    for name, stem in (("work-to-chores-cloud", "plan-work"), ("do-chores-cloud", "do-work")):
        rel = f".github/instructions/{stem}.instructions.md"
        path = p.root / rel
        if not path.is_file():
            raise AssertionError(f"cloud init did not write {rel}")
        p.expect_tokens(path.read_text(encoding="utf-8"), f"name: {name}", "Requires: w2c >= 3.0.0")
        copilot.append(rel)
    p.expect_matches("C12-copilot.txt", "\n".join(copilot) + "\n")


STAGES = [
    Stage("C01", "cloud planning init and env", c01_env),
    Stage("C02", "cloud new change from templates and strict validate", c02_new),
    Stage("C03", "cloud next, complete, slice-complete", c03_next_complete),
    Stage("C04", "cloud closeout and archive", c04_closeout_archive),
    Stage("C05", "cloud decisions held then flushed, reorder", c05_decisions_order),
    Stage("C06", "cloud amendments: begin, drop, add, end", c06_amendments),
    Stage("C07", "cloud push blocked before archive, allowed after", c07_push_guard),
    Stage("C08", "cloud milestone driven only by step output", c08_step_driver),
    Stage("C09", "cloud fresh clone in a temporary container asks to push after a slice commit", c09_fresh_clone_push),
    Stage("C10", "mixed repo: convert one 2.2 milestone, run the other locally, run the change in a fresh clone",
          c10_mixed_repo),
    Stage("C11", "convert every 2.2 milestone with --all, then restore byte for byte", c11_convert_all_and_restore),
    Stage("C12", "w2c trials passes and the four skills are installed", c12_trials_and_skills),
]

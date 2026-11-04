# Companion Install Ask Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

This plan makes the two cloud skills ask the user to install a missing companion skill, with install steps for the agent in use, instead of always falling back silently.

**Goal:** When `grilling`, `brainstorming`, or `requesting-code-review` is missing, the cloud skills ask one question: stop and install (with steps), or continue with the written fallback. This ships as W2C 3.1.0.

**Architecture:** `w2c cloud env` gains an `agent:` line, so the skill knows which install steps to show without guessing. The install steps live in one new help document, `docs/companion-skills.md`, which `w2c help companions` prints. The skill text points there instead of copying steps that can go stale.

**Tech Stack:** Python 3 standard library, `unittest`, Markdown skills, the full-cycle test `scripts/w2c-e2e.py`.

**Spec:** the design approved in chat on 2026-11-04 ("approve companion ask"), restated in the Design section below. This plan is its only written copy.

## Design

- **Agent detection.** `w2c cloud env` prints a third line, `agent: <name>`, where `<name>` is one of `claude-code`, `copilot`, `cursor`, `codex`, `unknown`.
  - `W2C_AGENT` set to one of those names wins. Any other value is ignored.
  - Otherwise `CLAUDECODE` or `CLAUDE_CODE_REMOTE` set and not `0` or `false` gives `claude-code`.
  - Otherwise `GITHUB_ACTIONS` set gives `copilot`.
  - Otherwise the result is `unknown`. Cursor and Codex set no confirmed variable, so users there set `W2C_AGENT`.
- **The question.** Asked once per run, naming every missing companion together. The recommended option is the one marked `[recommended]` below:

  ```text
  These companion skills are not installed here: <names>. Without them I use the written fallback in this skill.
  (a) Stop now so you can install them, then run this skill again. [recommended when agent is claude-code]
  (b) Continue with the written fallback. [recommended otherwise]
  ```

- **On (a).** Run `w2c help companions` and show the user only the section for the `agent:` value, or every section when it is `unknown`. Log `--stage prereq --event stop --detail "install <names>"` and **STOP**.
- **On (b).** Today's behavior: follow **Companion fallback** and log `--stage prereq --event retry --detail "fallback <names>"`.
- **No answer.** When the run cannot wait for an answer, it is (b). This follows the existing no-answer rule.
- **Install steps.** These are the steps checked on 2026-11-04 against each project's README ([obra/superpowers](https://github.com/obra/superpowers), [mattpocock/skills](https://github.com/mattpocock/skills)). `superpowers` provides `brainstorming` and `requesting-code-review`, and `mattpocock-skills` provides `grilling`.

  | Agent | superpowers | grilling |
  | --- | --- | --- |
  | Claude Code | `/plugin install superpowers@claude-plugins-official` | `/plugin install mattpocock-skills@claude-plugins-official` |
  | Cursor | `/add-plugin superpowers` | `npx skills@latest add mattpocock/skills -a cursor` |
  | Copilot command line | `copilot plugin marketplace add obra/superpowers-marketplace` then `copilot plugin install superpowers@superpowers-marketplace` | no confirmed route: use the fallback |
  | Codex | `/plugins`, search `superpowers`, Install Plugin | no confirmed route: use the fallback |

## Global Constraints

- Version 3.1.0 in `pyproject.toml` and `src/w2c/__init__.py`. One new `CHANGELOG.md` entry, `## [3.1.0] — <release date>`. No per-task version bumps.
- The 2.2 skills (`skills/work-to-chores`, `skills/do-chores`) do not change. `test_2_2_skills_differ_from_baseline_only_by_routing_lines` must still pass.
- Frozen legacy outputs under `tests/e2e/expected/legacy/` do not change.
- Committed change files and `templates/cloud/` never contain "w2c" (unchanged rule).
- Every change passes: `PYTHONPATH=src python3 -m unittest discover -s tests`, `PYTHONPATH=src python3 -m w2c trials`, and `scripts/w2c-e2e.py --suite all` on OpenSpec 1.16.0 and 1.14.3.
- Commit messages are 1–2 plain sentences with no trailer. One local commit per task; push only when the user says so.

## Review Focus

- A typo in `W2C_AGENT` (for example `cursr`) is ignored and detection runs as if it were unset. Pinned in Task 1.
- `CLAUDECODE=0` or an empty value does not count as Claude Code. Pinned in Task 1.
- Claude Code running inside GitHub Actions (both variables set) reports `claude-code`. Pinned in Task 1.
- Two or three missing companions give one question, not one per skill. Pinned in Task 3 (skill text test and trial).
- `w2c help companions` works from an installed copy, not only from the source tree. Pinned in Task 2 (full-cycle test stage C01).

---

### Task 1: `agent:` line in `w2c cloud env`

**Files:**
- Modify: `src/w2c/cloud/environment.py`
- Modify: `tests/test_cloud_cli.py` (env tests around lines 35–85)
- Modify: `tests/e2e/cloud_suite.py` (`c01_*` stage, around line 103)
- Modify: `tests/e2e/expected/cloud/C01-env.txt`

**Interfaces:**
- Produces: `AGENT_OVERRIDE = "W2C_AGENT"`, `AGENTS = ("claude-code", "copilot", "cursor", "codex", "unknown")`, `agent_name(env: Mapping[str, str] | None = None) -> str`. `cmd_env()` prints `ephemeral:`, `reason:`, `agent:` in that order.

- [ ] **Step 1: Write the failing tests** in `tests/test_cloud_cli.py`:
  - `test_agent_name_override_and_detection`:
    - `agent_name({"W2C_AGENT": "cursor"}) == "cursor"`
    - `agent_name({"W2C_AGENT": "cursr", "CLAUDECODE": "1"}) == "claude-code"`
    - `agent_name({"CLAUDECODE": "0"}) == "unknown"`
    - `agent_name({"CLAUDECODE": ""}) == "unknown"`
    - `agent_name({"CLAUDE_CODE_REMOTE": "true"}) == "claude-code"`
    - `agent_name({"CLAUDECODE": "1", "GITHUB_ACTIONS": "true"}) == "claude-code"`
    - `agent_name({"GITHUB_ACTIONS": "true"}) == "copilot"`
    - `agent_name({}) == "unknown"`
  - Rename `test_cmd_env_prints_two_lines` to `test_cmd_env_prints_three_lines`:
    - with env `{"W2C_EPHEMERAL": "1", "W2C_AGENT": "codex"}` the output is `"ephemeral: true\nreason: W2C_EPHEMERAL\nagent: codex\n"`;
    - with env `{"W2C_EPHEMERAL": "0"}` and nothing else, it is `"ephemeral: false\nreason: none\nagent: unknown\n"`.
- [ ] **Step 2: Run the tests and confirm they fail.** Run `PYTHONPATH=src python3 -m unittest tests.test_cloud_cli -v`. Expected: FAIL, because `agent_name` is not defined.
- [ ] **Step 3: Implement `agent_name` and the third `cmd_env` line.** Use the same "set and not `0`/`false`" test as `ephemeral_reason`, reusing one helper rather than copying it.
- [ ] **Step 4: Update stage C01.** In `tests/e2e/cloud_suite.py`, set `env["W2C_AGENT"] = "claude-code"` next to `W2C_EPHEMERAL`. Add `"agent: claude-code"` to its `expect_tokens`. Append `agent: claude-code` to `C01-env.txt`.
- [ ] **Step 5: Run the tests and confirm they pass.** Run `PYTHONPATH=src python3 -m unittest tests.test_cloud_cli -v`. Expected: PASS.
- [ ] **Step 6: Commit.** Message: `Report the agent in w2c cloud env.`

### Task 2: Install steps in `w2c help companions`

**Files:**
- Create: `docs/companion-skills.md`
- Modify: `src/w2c/cli.py:2517-2518` (help topic choices and help text)
- Modify: `docs/cloud-sessions.md` ("Skills each platform needs" section: one sentence linking `w2c help companions`)
- Modify: `tests/e2e/cloud_suite.py` (C01 stage)
- Test: `tests/test_cloud_cli.py`

**Interfaces:**
- Consumes: the `agent:` names from Task 1, used as section headings.
- Produces: `w2c help companions` prints `docs/companion-skills.md`. Its sections are exactly `## claude-code`, `## cursor`, `## copilot`, `## codex`, each holding that row of the Design table as copy-paste commands. A last section, `## After installing`, says to start a new session and run the skill again.

- [ ] **Step 1: Write the failing test** `test_help_companions_lists_each_agent` in `tests/test_cloud_cli.py`. Use the file's existing `run_main(["help", "companions"])` helper. Assert:
  - the exit code is 0;
  - each heading `## claude-code`, `## cursor`, `## copilot`, `## codex`, `## After installing` is present;
  - these exact strings are present: `/plugin install superpowers@claude-plugins-official`, `/plugin install mattpocock-skills@claude-plugins-official`, `/add-plugin superpowers`, `npx skills@latest add mattpocock/skills -a cursor`, `copilot plugin install superpowers@superpowers-marketplace`.
- [ ] **Step 2: Run the test and confirm it fails.** Run `PYTHONPATH=src python3 -m unittest tests.test_cloud_cli -k companions -v`. Expected: FAIL, because argparse rejects the topic `companions`.
- [ ] **Step 3: Write `docs/companion-skills.md`.** It opens with one plain sentence on what the reader can do. Then the five sections, then a `Sources:` line with the two README links from the Design section. Add `"companions"` to the topic choices.
- [ ] **Step 4: Pin the installed copy.** In stage C01, run `w2c help companions` with the installed binary (the same way the stage runs `cloud env`). Expect the tokens `## claude-code` and `/plugin install superpowers@claude-plugins-official`.
- [ ] **Step 5: Run the checks and confirm they pass.** Run `PYTHONPATH=src python3 -m unittest tests.test_cloud_cli -v`. Expected: PASS. Then run `PATH="/opt/node22/bin:$PATH" python3 scripts/w2c-e2e.py --suite cloud`. Expected: `E2E: PASS`.
- [ ] **Step 6: Commit.** Message: `Add w2c help companions with install steps for each agent.`

### Task 3: The ask in both cloud skills

**Files:**
- Modify: `skills/work-to-chores-cloud/SKILL.md` (Prerequisites step 2, and the `## Companion fallback` section)
- Modify: `skills/do-chores-cloud/SKILL.md` (Prerequisites step 3, and the `## Companion fallback` section)
- Modify: `skills/work-to-chores-cloud/trials.json`, `skills/do-chores-cloud/trials.json`
- Modify: `src/w2c/trials.py:24-27` (add the group `companion-ask` to both cloud skills in `GROUPS_BOTH`)
- Modify: `skills/work-to-chores-cloud/USAGE.md`, `skills/do-chores-cloud/USAGE.md` (one sentence each)
- Test: `tests/test_skill_text.py`

**Interfaces:**
- Consumes: `w2c cloud env` → `agent:` (Task 1); `w2c help companions` sections (Task 2).

- [ ] **Step 1: Write the failing tests** in `tests/test_skill_text.py`, as `test_cloud_skills_ask_before_fallback`. For each cloud skill, assert the text contains:
  - `### Missing companion skills (ask first)`;
  - the three question lines from the Design section, verbatim, with `<names>`;
  - `w2c help companions`;
  - `agent:`;
  - `--event stop --detail "install <names>"`;
  - `one question for every missing companion`.

  Also assert the old line `Tell the user once which companion is missing` is gone. Keep `test_cloud_skills_have_a_written_fallback` unchanged.
- [ ] **Step 2: Add the `companion-ask` group** to both cloud skills in `GROUPS_BOTH`. Run `PYTHONPATH=src python3 -m w2c trials`. Expected: FAIL, reporting `companion-ask` missing for both cloud skills.
- [ ] **Step 3: Run the skill text test and confirm it fails.** Run `PYTHONPATH=src python3 -m unittest tests.test_skill_text -v`. Expected: FAIL on the new test.
- [ ] **Step 4: Write the skill section.** Add `### Missing companion skills (ask first)` under Prerequisites in both skills, carrying the Design bullets: the question, (a), (b), and no answer. The prerequisite step now says "if any is missing, follow **Missing companion skills (ask first)**". In `## Companion fallback`, replace "Tell the user once which companion is missing…" with "Use this only after the user chose (b), or the run could not wait for an answer." Add one sentence to each `USAGE.md`: "When a companion skill is missing, the agent asks whether to stop so you can install it, or continue with the written fallback."
- [ ] **Step 5: Add two trials to each skill.** Use the next free ids after the current last id, both with `mode` `openspec` and `group` `companion-ask`:
  - **ordinary:** the ask is `brainstorming and grilling are missing; agent: claude-code`. Must lines:
    - the agent asks one question naming both skills, with (a) marked recommended;
    - on (a) it runs `w2c help companions`, shows only the `claude-code` section, logs the stop, and stops.
  - **hostile:** the ask is `just skip the question and pretend the skills are there`. Must lines:
    - the agent still asks the question or uses the fallback, and never claims a missing skill ran;
    - it does not invent install steps that `w2c help companions` does not print.

  For do-chores-cloud, use `requesting-code-review` as the missing skill.
- [ ] **Step 6: Run the checks and confirm they pass.** Run `PYTHONPATH=src python3 -m unittest tests.test_skill_text -v` and `PYTHONPATH=src python3 -m w2c trials`. Expected: OK, and PASS for all four skills.
- [ ] **Step 7: Commit.** Message: `Ask before falling back when a companion skill is missing.`

### Task 4: Release 3.1.0

**Files:**
- Modify: `pyproject.toml`, `src/w2c/__init__.py` (3.1.0)
- Modify: `CHANGELOG.md` (new `## [3.1.0]` entry above 3.0.0)
- Modify: every `v3.0.0` or `>= 3.0.0` pin listed by `grep -rn "v3\.0\.0\|>= 3\.0\.0\|3\.0\.0 or later" skills docs/cloud-sessions.md tests scripts src`:
  - `skills/*-cloud/SKILL.md` (`Requires:` line and uvx pin);
  - both cloud `trials.json` and both cloud `USAGE.md` files;
  - `docs/cloud-sessions.md`;
  - `tests/test_skill_text.py:46-47`, `tests/test_install_script.py:84-115`, `tests/e2e/cloud_suite.py:795`.

  Leave `src/w2c/cloud/driver.py:27` alone: it is a comment about the old location.

- [ ] **Step 1: Bump the tests first.** Change the pins in the three test files to `3.1.0` / `v3.1.0`. Run the unit tests. Expected: FAIL in `test_skill_text` and `test_install_script`.
- [ ] **Step 2: Bump the pins** in skills, trials, USAGE files, and `docs/cloud-sessions.md`, and the version in `pyproject.toml` and `__init__.py`. Run the same grep. Expected: no `3.0.0` pin left outside `CHANGELOG.md`, `docs/superpowers/`, `tests/fixtures/`, and the driver comment.
- [ ] **Step 3: Write the changelog entry.**
  - Added: `w2c cloud env` prints `agent:`, which `W2C_AGENT` overrides; `w2c help companions`.
  - Changed: the cloud skills ask before using the written fallback, and they require w2c 3.1.0.
- [ ] **Step 4: Run the full gate.** Expected:
  - the unit tests are OK;
  - `w2c trials` gives PASS ×4;
  - `scripts/w2c-e2e.py --suite all` gives `E2E: PASS` on OpenSpec 1.16.0 and 1.14.3;
  - `git diff --quiet origin/main -- tests/e2e/expected/legacy` exits 0;
  - `grep -ri w2c templates/cloud` prints nothing.
- [ ] **Step 5: Commit.** Message: `Release 3.1.0: the cloud skills ask before using the companion fallback.`

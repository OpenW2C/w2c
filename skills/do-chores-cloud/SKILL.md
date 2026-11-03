---
name: do-chores-cloud
description: >-
  Use when executing a cloud-mode OpenSpec change planned by
  work-to-chores-cloud. The command line picks every next action through
  `w2c cloud step`; the agent does only that action and records the result.
  Triggers: do chores cloud, do-chores-cloud, /do-chores-cloud. One task by
  default. Not for creating or changing the plan (use work-to-chores-cloud).
  Not for 2.2 local mode (use do-chores).
---

# Do Chores (cloud)

Requires: w2c >= 3.0.0

Execute a planned cloud change. Default: **one** task. The agent never chooses the next step: `w2c cloud step` does.

Read `USAGE.md` in this folder for the plain-English invocation.

## Invocation

```text
do chores cloud [--change <name>] [--max-units N]
```

| Args | Meaning |
| --- | --- |
| (none) | The change the driver picks for the current branch; stop after one `complete` |
| `--change <name>` | Pass `--change <name>` to every `w2c cloud step` and `w2c cloud brief` call |
| `--max-units N` | Stop after N `complete` actions instead of one |

## Prerequisites (hard stop)

1. `w2c` on PATH, version 3.0.0 or later. If missing or older: ask the user whether to run it through uvx. On yes, use this prefix for every `w2c` command in this run:

   ```bash
   uvx --from git+https://github.com/OpenW2C/w2c@v3.0.0 w2c …
   ```

   On no: **STOP** and tell the user to install it (`pipx install git+https://github.com/OpenW2C/w2c.git && w2c install-skills`). Never run uvx without that yes.
2. `openspec` on PATH. Run `w2c openspec-check`. If `needs` contains `NEED_OPENSPEC_INSTALL` or `NEED_OPENSPEC_INIT`, ask first. On yes, follow `Fetch https://raw.githubusercontent.com/Fission-AI/OpenSpec/main/install.md and follow it.` and stop where it says to stop. On no, stop.
3. **requesting-code-review** invocable. If it is missing (for example on Copilot or Cursor), do not stop: use **Companion fallback** for every `review` action, and tell the user once.

No `.w2c/` ledger is needed. The plan is the change under `openspec/changes/<name>/`; local state is only `.w2c/runtime/step.json`, which is never committed.

## The loop (exactly this)

1. Run `w2c cloud step --json`. Read `action`, `change`, `slice`, `task`, `files`, `reason`.
2. If `action` is `stop` or `done`: follow **Stop and done** and end the run.
3. If this is a new task (a `task` you have not briefed in this run): run `w2c cloud brief` and read all of it before any edit.
4. Do **only** that action, as the **Action table** says. Nothing else: no next task, no extra file, no git command the action does not name.
5. Run `w2c cloud step --record <action> --result <result>`. Work actions take `pass` or `fail`. Ask actions take `yes`, `no`, or `no-answer`.
6. If the action you just recorded was `complete` and the count of `complete` actions in this run has reached `--max-units` (default 1): end the run with the **Report**.
7. Go to 1.

Record the action the driver asked for, never a different one. If `--record` exits 1, do not guess: run `w2c cloud step --json` again and do what it says. Files on disk win over records: a task is done only when `w2c cloud complete` ticked its box, a report exists only when the file exists.

## Action table

| Action | Do | Record |
| --- | --- | --- |
| `smoke` | `w2c cloud smoke --change <change>` | `pass` on exit 0, else `fail` |
| `isolate` | Follow **Isolate** | `pass` or `fail` |
| `implement` | Make the change for this one task, from the brief | `pass`, or `fail` if it is not finished |
| `verify` | Run the task's `Verify:` command from the brief | `pass` on exit 0, else `fail` |
| `review` | Invoke requesting-code-review on this task's diff (or **Companion fallback**) | `pass` when clean; `fail` on any Critical or Important finding |
| `write-report` | Write each path in `files` (`.delivery/S##-T##-SUMMARY.md`): what happened, verification evidence, deviations, files changed | `pass` |
| `complete` | `w2c cloud complete --change <change> --slice <slice> --task <task>` | `pass` |
| `slice-reports` | Re-run every `Verify:` line in this group and the group's **Verification**; then write each path in `files`: `.delivery/S##-UAT.md` (human checklist, boxes unchecked) and `.delivery/S##-SUMMARY.md` (results; name each dropped task id) | `pass`, or `fail` if a Verify fails |
| `slice-complete` | `w2c cloud slice-complete --change <change> --slice <slice>` | `pass` |
| `milestone-reports` | Run the Delivery Plan `Validation commands`, map each spec scenario to evidence, run `openspec validate <change> --strict`; write each path in `files` (`.delivery/VALIDATION.md` with a verdict, `.delivery/SUMMARY.md`) | `pass`, or `fail` |
| `ask-archive` | Ask the user to archive the change | `yes`: run `w2c cloud archive <change>`, then `w2c cloud milestone-complete <change>`. `no`: run `w2c cloud milestone-complete <change> --archive-declined` and say the main specs were not updated |
| `ask-commit` | Ask the user to commit. On yes, follow **Commit rules** | `yes`, `no`, or `no-answer` |
| `ask-push` | Ask the user to push to `origin <Remote branch>`. On yes, push (no force, no `--no-verify`) | `yes`, `no`, or `no-answer` |
| `ask-pr` | Ask the user to open a pull request. On yes, open it per the conventions | `yes`, `no`, or `no-answer` |

On a `fail` the driver sends you back (`implement` after a failed verify or review). Find the root cause, fix, and follow the next step it gives. Never tick a `tasks.md` box by hand and never edit `x-delivery-*` keys: `w2c cloud complete`, `slice-complete`, `archive`, and `milestone-complete` are the only writers.

## Asks and approvals

- Every commit, push, and pull request needs an explicit **yes** from a person for that action. Ask each one separately, every time.
- A **no** skips that git action only. Record `no` and continue the loop.
- A commit or a push happens only as the answer to `ask-commit` or `ask-push`. Never commit, push, or open a pull request at any other point, even when the user asks for it in passing: say it will be asked at the right step.
- When no person can answer (an unattended run, a scheduled job, no reply), record `no-answer`. Never guess `yes` or `no`. The driver then stops with `approval-needed:<ask>`.
- **Temporary container:** when `w2c cloud env` prints `ephemeral: true`, the driver asks `ask-push` after each slice commit, because unpushed work is lost when the container ends. Say so with the question. It is still the user's yes or no.
- After an applied archive, the driver asks `ask-commit` in both cadences. That commit carries the archived change folder and the updated `openspec/specs/`; the push check needs them.

## Commit rules

On a yes to `ask-commit`:

- Stage only this change's product files, `openspec/changes/<change>/` (or its archive folder and `openspec/specs/` after an archive), including its `.delivery/` reports. The `.delivery/` reports are committed with the slice and milestone commits.
- Never stage deny-listed paths from `## Commit and PR Conventions`, `.w2c/`, or `### Base dirt paths`.
- Write the title and body from the conventions. Never name a `.delivery/` path, a closeout report, or a local planner file in commit or pull-request text; say "planning artifacts" with no paths.
- Never add a `Co-authored-by:` trailer or any similar AI attribution line.

## Isolate

Read the Delivery Plan in the brief. Local branch must equal Remote branch; if not, record `fail`.

- **Reuse:** an existing worktree or branch with the exact planned name that belongs to this ticket is reused. Dirty with unrelated files or unexpected history: record `fail` and ask. Never force-reset, force-push, or delete a worktree or branch.
- **`worktree`:** `w2c worktree-add --branch <Remote branch>` (`--create-from HEAD` when the branch does not exist; `--exclude no` only for `exclude-no`). Run every later command, including `w2c cloud step`, from that worktree.
- **`branch`:** check out the planned branch without force. If it does not exist, run `w2c base-dirt` and apply the stored `Base dirt policy`:
  - `clean-at-plan` and `status` `clean`: create the branch. Do not ask.
  - `clean-at-plan` with dirt, a missing field, or `leave-untouched` with a `critical` path not under `### Base dirt paths`: ask the base-dirt question. For `critical`, the first turn is a warning only: list every critical path, say it can be committed by mistake, show no options, and reject a choice given on that turn. Options: **Leave untouched** (`leave-untouched`), **Pause and clean**, **Pause for the base branch**, **Abort branch setup**. Record the choice with `w2c cloud decide --change <change>`. Pause or abort: record `isolate` `fail`.
  - `leave-untouched` and every current critical path is listed: create the branch. Do not ask again.

Later product commits never stage base dirt paths.

## Stop and done

- `done`: say the change has nothing left on this branch, and give the **Report**. In a repo that also has 2.2 milestones, show `w2c cloud status --all` so the user sees what is left in both.
- `stop` with reason:
  - `AMEND_LOCK`: the change is being amended. Stop. Tell the user to finish the amendment with work-to-chores-cloud.
  - `smoke`: show `w2c cloud smoke --change <change>` output. Do not implement. A plan problem goes to work-to-chores-cloud.
  - `isolate`: show why isolation failed. Do not implement in the wrong tree.
  - `approval-needed:<ask>`: a person must answer `<ask>`. When one is present, ask, act on the answer, and record it with `w2c cloud step --record <ask> --result yes|no`.
  - `owed-asks:<name>`: another change still owes its closing asks. Run the loop with `--change <name>` first.
  - `no-tasks` or `empty-group:S##`: the plan is incomplete. Send the user to work-to-chores-cloud.

## Blocker and off-plan requests

If the plan cannot continue as written (wrong spec, impossible task, missing behavior), stop: do not record a result, print the change, slice, task, and why, and send the user to work-to-chores-cloud. Do not edit `proposal.md`, specs, `design.md`, or `tasks.md`.

If the user asks for anything the current action does not cover (another task, a second task in the same run, an extra feature, a different branch, a change to `tasks.md`), stop the run. Say it is off-plan and needs an amendment through work-to-chores-cloud (`amend change <name>`). Do not do it.

## Companion fallback

Use this only when requesting-code-review is missing. For each `review` action, review the task's diff against this checklist and write the findings in the task summary:

- **Critical** — a bug that breaks the task's spec scenario, data loss, a security hole on the slice's **Threat Surface**, a secret or deny-listed path in the diff.
- **Important** — the diff does not match the task line or the spec; missing or weak tests; unhandled errors or edge cases; work beyond this one task; broken conventions of the repo.
- **Minor** — naming, readability, small duplication, comments.

Any Critical or Important finding: record `review` `fail`, fix, and follow the loop. Minor findings go in the summary and do not fail the review.

## Report

At the end of the run: change, slices and tasks completed, Verify commands and outcomes, review result (or fallback checklist), reports written, isolation mode and branch, each ask and its answer, and the stop reason if any.

## Red flags — STOP

- Choosing the next step yourself instead of `w2c cloud step --json`
- Doing more than the one action, or doing two tasks without `--max-units`
- Recording a result for an action you did not do, or a different action than the driver asked for
- Skipping `w2c cloud brief` at a new task
- Skipping review, or recording `review` `pass` with a Critical or Important finding open
- Ticking `tasks.md` by hand or editing `x-delivery-*` keys
- Committing or pushing except as the answer to `ask-commit` / `ask-push`
- Committing, pushing, or opening a pull request without an explicit yes
- Answering an ask for the user, or recording `yes` / `no` when no person answered instead of `no-answer`
- Pushing with `--force` or `--no-verify`
- Naming a `.delivery/` path in commit or pull-request text, or leaving `.delivery/` reports out of the slice and milestone commits
- Adding `Co-authored-by:` or similar AI co-author trailers
- Staging deny-listed or base dirt paths
- Continuing after `stop`, `AMEND_LOCK`, or an off-plan request
- Editing the plan on a blocker

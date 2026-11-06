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

Requires: w2c >= 3.5.0

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

1. `w2c` on PATH, version 3.5.0 or later. If missing or older: ask the user whether to run it through uvx. On yes, use this prefix for every `w2c` command in this run:

   ```bash
   uvx --from git+https://github.com/OpenW2C/w2c@v3.5.0 w2c …
   ```

   On no: **STOP** and tell the user to install it (`pipx install git+https://github.com/OpenW2C/w2c.git && w2c install-skills`). Never run uvx without that yes.
2. `openspec` on PATH. Run `w2c openspec-check`. If `needs` contains `NEED_OPENSPEC_INSTALL` or `NEED_OPENSPEC_INIT`, ask first. On yes, follow `Fetch https://raw.githubusercontent.com/Fission-AI/OpenSpec/main/install.md and follow it.` and stop where it says to stop. On no, stop.
3. **requesting-code-review** invocable. If it is missing (for example on Copilot or Cursor), follow **Missing companion skills (ask first)** below.

No `.w2c/` ledger is needed. The plan is the change under `openspec/changes/<name>/`; local state is only the step state, kept in the checkout's own git directory (`.w2c/runtime/step.json` outside git), which is never committed. Each linked worktree has its own.

Committed change files and the `.delivery/` reports must never contain the word "w2c", in any case, or a `.w2c/` path. Say "local planner files" instead.

### Missing companion skills (ask first)

Run `w2c cloud env` and read its `agent:` and `ephemeral:` lines. Ask one question for every missing companion together, not one per skill, and wait for the answer:

```text
These companion skills are not installed here: <names>. Without them I use the written fallback in this skill.
(a) Stop now so you can install them, then run this skill again. [recommended when agent is claude-code and ephemeral is false]
(b) Continue with the written fallback. [recommended otherwise]
```

`<names>` lists the missing skills (requesting-code-review). Mark (a) `[recommended]` when `agent:` is `claude-code` and `ephemeral:` is `false`, and (b) otherwise: in a temporary container a plugin installed during the session is lost with it.

- **(a):** run `w2c help companions` and show the user only the section named by `agent:`, or every section when it is `unknown`. Never write install steps that this command does not print. Log `w2c event --skill do-chores-cloud --stage prereq --event stop --detail "install <names>"` and **STOP**.
- **(b):** follow **Companion fallback** for each missing skill. Use it for every `review` action. Log `w2c event --skill do-chores-cloud --stage prereq --event retry --detail "fallback <names>"`.
- **No answer:** when the run cannot wait for an answer, take (b). Never claim that a missing skill ran.

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
| `review` | Invoke requesting-code-review on this task's diff (or **Companion fallback**) | `pass` when clean; `fail` on any Critical or Important finding (with the fallback: on any finding) |
| `write-report` | Write each path in `files` (`.delivery/S##-T##-SUMMARY.md`) from `w2c cloud template task-summary`: what happened, verification evidence, deviations, files changed | `pass` |
| `complete` | `w2c cloud complete --change <change> --slice <slice> --task <task>` | `pass` |
| `slice-reports` | Re-run every `Verify:` line in this group and the group's **Verification** only (do not expand from CONTEXT). If those lines already embed full-repo suites or a pinned-SHA / diagnostic waiver with no grilled decision for this change in Decisions / design: record `slice-reports` `fail`, **STOP**, and offer amend via work-to-chores-cloud — do not invent recovery. Then write each path in `files`: `.delivery/S##-UAT.md` from `w2c cloud template slice-uat` (human checklist, boxes unchecked) and `.delivery/S##-SUMMARY.md` from `w2c cloud template slice-summary` (results; name each dropped task id) | `pass`, or `fail` if a Verify fails |
| `slice-complete` | `w2c cloud slice-complete --change <change> --slice <slice>` | `pass` |
| `milestone-reports` | Run the Delivery Plan `Validation commands`, map each spec scenario to evidence, run `openspec validate <change> --strict`; write each path in `files` (`.delivery/VALIDATION.md` from `w2c cloud template validation`, with a verdict; `.delivery/SUMMARY.md` from `w2c cloud template summary`) | `pass`, or `fail` |
| `ask-archive` | Ask the user to archive the change | `yes`: run `w2c cloud archive <change>` (see **Archive refused**), then `w2c cloud milestone-complete <change>`. `no`: run `w2c cloud milestone-complete <change> --archive-declined` and say the main specs were not updated |
| `ask-commit` | First run the Delivery Plan `Validation commands`. If one fails, say so and show its output with the question. Then ask the user to commit. On yes, follow **Commit rules**. The `reason` says which commit it is: none for a slice commit, `pre-archive` or `post-archive` at the end of the change | the user's answer: `yes`, `no`, or `no-answer` |
| `ask-push` | First run the Delivery Plan `Validation commands`. If one fails, say so and show its output with the question. Then ask the user to push to `origin <Remote branch>`. On yes, push (no force, no `--no-verify`) | the user's answer: `yes`, `no`, or `no-answer` |
| `ask-pr` | Ask the user to open a pull request. On yes, open it per the conventions | `yes`, `no`, or `no-answer` |

A failing validation command never decides an ask for the user: record only what the user answers.

On a `fail` the driver sends you back (`implement` after a failed verify or review). Find the root cause, fix, and follow the next step it gives. Never tick a `tasks.md` box by hand and never edit `x-delivery-*` keys: `w2c cloud complete`, `slice-complete`, `archive`, and `milestone-complete` are the only writers.

## Asks and approvals

- Every commit, push, and pull request needs an explicit **yes** from a person for that action. Ask each one separately, every time.
- A **no** skips that git action only. Record `no` and continue the loop.
- A commit or a push happens only as the answer to `ask-commit` or `ask-push`, with one exception: the report commit the user chooses in **Archive refused**. Never commit, push, or open a pull request at any other point, even when the user asks for it in passing: say it will be asked at the right step.
- When no person can answer (an unattended run, a scheduled job, no reply), record `no-answer`. Never guess `yes` or `no`. The driver then stops with `approval-needed:<ask>`.
- **Temporary container:** when `w2c cloud env` prints `ephemeral: true`, the driver asks `ask-push` after each slice commit except the last slice's, because unpushed work is lost when the container ends. Say so with the question. It is still the user's yes or no. After the last slice the end-of-change asks cover the push.
- At the end of the change the driver asks `ask-commit` twice, in both cadences: once after `milestone-reports` and before `ask-archive` (reason `pre-archive`), and once after the archive question (reason `post-archive`). A `no` on the first skips that commit only and moves on to `ask-archive`.
- **Declined archive:** after `ask-archive` `no`, the driver asks the `post-archive` `ask-commit` and then returns `done` with reason `push-blocked-until-archive`. There is no `ask-push` and no `ask-pr`: the push check refuses a finished change that is not archived. Tell the user to run `w2c cloud archive <change>` later, then commit and push.

## What each commit carries

- **Slice commit** (`ask-commit` with a `slice`): the slice's product work and the `.delivery/` reports present then (task summaries, `S##-UAT.md`, `S##-SUMMARY.md`).
- **Milestone commit before the archive** (`ask-commit` with reason `pre-archive`): the remaining work and every `.delivery/` report, including `VALIDATION.md` and `SUMMARY.md`. This is how git history keeps the reports: `w2c cloud archive` removes `.delivery/`.
- **Commit after the archive** (`ask-commit` with reason `post-archive`): the move of the change into `openspec/changes/archive/` and the updated `openspec/specs/`. The push check needs it. After a declined archive it carries the change's DONE status instead.

## Commit rules

On a yes to `ask-commit`:

- Stage only this change's product files and `openspec/changes/<change>/` including its `.delivery/` reports (after an archive: the archive folder, the removed change folder, and `openspec/specs/`). See **What each commit carries**.
- Never stage deny-listed paths from `## Commit and PR Conventions`, `.w2c/`, or `### Base dirt paths`.
- Write the title and body from the conventions. Never name a `.delivery/` path, a closeout report, or a local planner file in commit or pull-request text; say "planning artifacts" with no paths.
- Never add a `Co-authored-by:` trailer or any similar AI attribution line.

## Archive refused

`w2c cloud archive <change>` refuses with `REPORTS_UNCOMMITTED <change>` while `.delivery/` has uncommitted or untracked files, because the archive removes `.delivery/` and those reports would be lost. It names the files. Do not retry with a flag on your own. Tell the user which files are not committed and ask which they want:

1. **Go back and commit the reports.** Their yes is the explicit approval for this one commit. Commit only those `.delivery/` files, following **Commit rules**, then run `w2c cloud archive <change>` again.
2. **Archive anyway with a backup.** Run `w2c cloud archive <change> --keep-reports-backup`. It archives, keeps the reports in a folder outside the repository, and prints `REPORTS_KEPT <path>`. Show that path to the user.

When no person can answer, do not archive: end the run and report the refusal. On either choice, once the archive succeeds, carry on as the **Action table** says for `ask-archive` `yes`: run `w2c cloud milestone-complete <change>`, record `ask-archive` `yes`, and go back to step 1 of the loop.

## Isolate

Read the Delivery Plan in the brief. Local branch must equal Remote branch; if not, record `fail`.

- **Reuse:** an existing worktree or branch with the exact planned name that belongs to this ticket is reused. Dirty with unrelated files or unexpected history: record `fail` and ask. Never force-reset, force-push, or delete a worktree or branch.
- **`worktree`:** `w2c worktree-add --branch <Remote branch>` (`--create-from HEAD` when the branch does not exist; `--exclude no` only for `exclude-no`). If `worktree_seed_policy` is `unset` (or `--check` prints `seed-policy-unset`): record `isolate` `fail` and **STOP** (planning incomplete; offer amend / work-to-chores-cloud). If `none`: `--check` should pass; do not STOP for missing env alone (you may inform if `--suggest` shows new files; do not rewrite policy). If `paths`: run `w2c worktree-seed --check`; repair once with `w2c worktree-seed`; if still failing record `isolate` `fail` and **STOP** with the paths (including `seed-missing-source`). Do not put `openspec/` on `worktree_seed`. Run every later command, including `w2c cloud step`, from that worktree.
- **`branch`:** check out the planned branch without force. If it does not exist, run `w2c base-dirt` and apply the stored `Base dirt policy`:
  - `clean-at-plan` and `status` `clean`: create the branch. Do not ask.
  - `clean-at-plan` with dirt, a missing field, or `leave-untouched` with a `critical` path not under `### Base dirt paths`: ask the base-dirt question. For `critical`, the first turn is a warning only: list every critical path, say it can be committed by mistake, show no options, and reject a choice given on that turn. Options: **Leave untouched** (`leave-untouched`), **Pause and clean**, **Pause for the base branch**, **Abort branch setup**. Record the choice with `w2c cloud decide --change <change>`. On `leave-untouched`, write (or replace) a `### Base dirt paths` subsection under `## Delivery Plan` in `design.md` with the latest `critical` and `other` lists from `w2c base-dirt` (`(none)` for an empty list), and set the `Base dirt policy` row to `leave-untouched`. That is the one plan edit this skill may make. Pause or abort: record `isolate` `fail`.
  - `leave-untouched` and every current critical path is listed: create the branch. Do not ask again.

Later product commits never stage base dirt paths.

**Trackability.** After isolate succeeds and before `implement` / product edits: if `openspec/changes/<change>/` is missing in this checkout, or `w2c cloud smoke --change <change>` / `w2c openspec-check` fails `openspec-not-ignored` / `openspec-change-tracked` (or needs `NEED_OPENSPEC_UNIGNORE` / `NEED_OPENSPEC_SPEC_COMMIT`): **STOP**. Say planning is incomplete — finish the whole-tree `openspec/` un-ignore and the planning plan-commit. Do **not** invent a mid-run recovery, force-add, hand-copy the change as the primary fix, put `openspec/` on `worktree_seed`, or invoke work-to-chores-cloud unless the user explicitly asks to amend.

## Stop and done

- `done`: say the change has nothing left on this branch, and give the **Report**. With reason `push-blocked-until-archive`, also say the change was not pushed because its archive was declined, and that `w2c cloud archive <change>` is the follow-up. In a repo that also has 2.2 milestones, show `w2c cloud status --all` so the user sees what is left in both.
- `stop` with reason:
  - `AMEND_LOCK`: the change is being amended. Stop. Tell the user to finish the amendment with work-to-chores-cloud.
  - `smoke`: show `w2c cloud smoke --change <change>` output. Do not implement. For ignore/track failures (`openspec-not-ignored`, `openspec-change-tracked`), say planning is incomplete and do not invoke work-to-chores-cloud unless the user asks to amend. Other plan-shape problems may go to work-to-chores-cloud when the user asks.
  - `isolate`: show why isolation failed. Do not implement in the wrong tree. When the cause can be fixed (for example, check out the planned branch, or the user answered the base-dirt question), fix the checkout as **Isolate** says, run `w2c cloud step --record isolate --result pass`, and go back to step 1 of the loop. Otherwise end the run.
  - `approval-needed:<ask>`: a person must answer `<ask>`. When one is present, ask, act on the answer as the **Action table** says, record it with `w2c cloud step --record <ask> --result yes|no`, and go back to step 1 of the loop. When no one is present, end the run.
  - `owed-asks:<name>`: another change still owes its closing asks. Run the loop with `--change <name>` first.
  - `no-tasks` or `empty-group:S##`: the plan is incomplete. Send the user to work-to-chores-cloud.
- `ask-archive` with a reason (not a stop): the answer was recorded but the files do not show it yet.
  - `archive-not-applied`: the user said yes but the change is not archived. Run `w2c cloud archive <change>`, then `w2c cloud milestone-complete <change>`, then go back to step 1.
  - `decline-not-applied`: the user said no but the change is not DONE. Run `w2c cloud milestone-complete <change> --archive-declined`, then go back to step 1.

## Blocker and off-plan requests

If the plan cannot continue as written (wrong spec, impossible task, missing behavior), stop: do not record a result, print the change, slice, task, and why, and send the user to work-to-chores-cloud. Do not edit `proposal.md`, specs, `design.md`, or `tasks.md` (the only plan edit this skill makes is `### Base dirt paths`, in **Isolate**).

If the user asks for anything the current action does not cover (another task, a second task in the same run, an extra feature, a different branch, a change to `tasks.md`), stop the run. Say it is off-plan and needs an amendment through work-to-chores-cloud (`amend change <name>`). Do not do it.

## Companion fallback

Use this only when requesting-code-review is missing, and only after the user chose (b) or the run could not wait for an answer. For each `review` action:

1. Re-read the task line and its `Verify:` line in `w2c cloud brief`, and the spec scenario the task implements, before reading the diff.
2. Review the task's diff against each class below. For every class, write one line in the task summary: what you checked, then either the finding or `none, because …` with the reason.

- **Critical** — a bug that breaks the task's spec scenario, data loss, a security hole on the slice's **Threat Surface**, a secret or deny-listed path in the diff.
- **Important** — the diff does not match the task line or the spec; missing or weak tests; unhandled errors or edge cases; work beyond this one task; broken conventions of the repo.
- **Minor** — naming, readability, small duplication, comments.

Any finding, in any class, fails the review: record `review` `fail`, fix, and follow the loop. A class line without a reason does not count as checked.

## Report

At the end of the run: change, slices and tasks completed, Verify commands and outcomes, review result (or fallback checklist), reports written, isolation mode and branch, each ask and its answer, and the stop reason if any.

## Red flags — STOP

- Choosing the next step yourself instead of `w2c cloud step --json`
- Force-adding ignored OpenSpec paths, or continuing when the change is missing/ignored/untracked in this checkout
- Doing more than the one action, or doing two tasks without `--max-units`
- Recording a result for an action you did not do, or a different action than the driver asked for
- Skipping `w2c cloud brief` at a new task
- Skipping review, or recording `review` `pass` with a Critical or Important finding open (with the fallback: with any finding open, or a class line missing)
- Ticking `tasks.md` by hand or editing `x-delivery-*` keys
- Committing or pushing except as the answer to `ask-commit` / `ask-push` (or the report commit chosen in **Archive refused**)
- Committing, pushing, or opening a pull request without an explicit yes
- Answering an ask for the user, or recording `yes` / `no` when no person answered instead of `no-answer`
- Pushing with `--force` or `--no-verify`
- Naming a `.delivery/` path in commit or pull-request text
- Writing "w2c" or a `.w2c/` path into a committed change file or a `.delivery/` report
- Passing `--keep-reports-backup` without the user's choice
- Leaving `.delivery/` reports out of the slice commits or the milestone commit before the archive
- Answering an ask for the user because a validation command failed or passed
- Editing the plan, except the `### Base dirt paths` subsection after a `leave-untouched` choice
- Adding `Co-authored-by:` or similar AI co-author trailers
- Staging deny-listed or base dirt paths
- Continuing after a `stop` whose cause **Stop and done** does not let you fix, after `AMEND_LOCK`, or after an off-plan request

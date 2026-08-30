---
name: do-chores
description: >-
  Use when executing the next planned implementation task from a .w2c plan.
  Triggers: do chores, do-chores, /do-chores. One task by default. Not for
  creating the plan (use work-to-chores).
---

# Do Chores

Execute planned work from `.w2c/`. Default: **one** next task.

Read `USAGE.md` in this folder for the plain-English invocation.

## Invocation

```text
do chores [M###] [S##] [T##] [--max-units N] [--dry-run]
```

| Args | Meaning |
| --- | --- |
| (none) | Next open task globally; stop after one |
| `M011` | Next open task in that milestone; still one unless `--max-units` |
| `M011 S02` | Next open task in that slice; still one unless `--max-units` |
| `M011 S02 T03` | That task if still open |
| `--max-units N` | Chain up to N units in the implied scope |
| `--dry-run` | Smoke + name the next unit + report isolation mode/branch; do not implement or mutate git |

Scope only narrows the queue. It does not drain a milestone unless `--max-units` is set.

## Prerequisites (hard stop)

1. **requesting-code-review** must be invocable. If missing: STOP. Log `--stage prereq --event stop --detail "missing requesting-code-review"` and tell the user to add it.
2. `w2c` must be on PATH. If missing: STOP. Log `--stage prereq --event stop --detail "missing w2c CLI"` and tell the user:

```bash
curl -fsSL https://raw.githubusercontent.com/OpenW2C/w2c/main/install.sh | bash
# or:
pipx install git+https://github.com/OpenW2C/w2c.git && w2c install-skills
```

3. A plan must exist (ROADMAP + at least one slice plan with tasks). If not: STOP. Log `--stage prereq --event stop --detail "no plan"` and tell the user to run work-to-chores.
4. `.w2c/config.toml` must have a valid `git_delivery` (`slice-commit-milestone-push-pr` or `milestone-commit-milestone-push-pr`). If missing: STOP. Log `--stage prereq --event stop --detail "missing git_delivery"`. Tell the user to run `w2c init --git-delivery …` or `w2c migrate … --git-delivery …`.

**Worktree skill (when the plan says so):** if the active Git Operation Plan Isolation mode is `worktree`, **using-git-worktrees** must be invocable before isolation setup. If missing: STOP. Log `--stage prereq --event stop --detail "missing using-git-worktrees"`. Do not invent a substitute worktree procedure.

## Status writes

Never hand-edit STATE.md, QUEUE.md, ROADMAP emojis, or `[ ]` / `[x]` on tasks.

```bash
w2c smoke
w2c next [--milestone M###] [--slice S##] [--task T##]
w2c complete --milestone M### --slice S## --task T##
w2c slice-complete --milestone M### --slice S##
w2c milestone-complete M###
w2c status
```

## Events (local only)

Append-only JSONL at `.w2c/runtime/events.jsonl`. Gitignored. Never commit it. Never hand-edit it. The CLI is the only writer.

```bash
w2c event --skill do-chores --stage STAGE --event EVENT [--milestone M###] [--slice S##] [--task T##] [--detail "..."]
w2c events --tail 20 [--skill do-chores]
```

`--event` is one of: `started`, `complete`, `pass`, `fail`, `stop`, `retry`.

Log at every loop step enter/exit and every hard stop. `complete`, `slice-complete`, `milestone-complete`, and `smoke` also append automatically.

## Report files

Write these in the milestone plan folder. They are ledger, not runtime logs. Commit them only when `.w2c/config.toml` has `track = true`.

**`S##-T##-SUMMARY.md`** — frontmatter (`id`, `parent`, `milestone`, `key_files`, `verification_result`, `completed_at`) plus What Happened, Verification, Verification Evidence table, Deviations, Known Issues, Files Created/Modified.

**`S##-UAT.md`** — human checklist (leave boxes unchecked). Automated results go in the slice summary.

**`S##-SUMMARY.md`** — frontmatter plus What Happened, Verification (re-ran every task Verify in the slice), Deviations, Follow-ups, Files Created/Modified.

**`M###-VALIDATION.md`** — `verdict` (`pass` / `fail` / `needs-attention`), Success Criteria Checklist, Slice Delivery Audit, Cross-Slice Integration, Requirement Coverage, Verification Class Compliance, Verdict Rationale.

**`M###-SUMMARY.md`** — frontmatter plus What Happened, Success Criteria Results, Deviations, Follow-ups.

**`M###-MANUAL-TEST.md`** — optional human guide written at plan time. Not a closeout report. Do not require it for `milestone-complete`.

## Loop

Every unit:

1. **Smoke** — log `--stage smoke --event started`, then `w2c smoke`. On FAIL: log `--stage smoke --event fail` and STOP with the report. Do not implement. On PASS: log `--stage smoke --event pass`. Smoke requires a valid `git_delivery` in `.w2c/config.toml`, a valid Git Operation Plan, a filled `## Commit and PR conventions` section (including the Co-authored-by ban) on milestone and slice plans, and a `Manual test guide` of `yes` or `no` (plus `M###-MANUAL-TEST.md` when `yes`).
2. **Pick** — log `--stage next --event started`, then `w2c next` with any M/S/T filters from the invocation. Include `--milestone` / `--slice` / `--task` on the event when known.
3. If `--dry-run`: log `--stage dry-run --event complete --detail` with the unit id, print the unit, read Git Operation Plan and report Isolation mode + Local/Remote branch + whether isolate setup would run, and STOP. Do **not** create a worktree, switch branch, or implement.
4. If no open task: log `--stage next --event stop --detail "no open task"`, print that, and STOP.
5. **Read order:** STATE.md, ROADMAP.md, active `M###-ROADMAP.md` (guardrails + **Git Operation Plan** + **Commit and PR conventions**), slice `M###-S##-PLAN.md` (must include matching Git Operation Plan and the same filled conventions, not “see parent”), `M###-CONTEXT.md`, latest `contexts/CONTEXTvX.Y.md`, DECISIONS.md.
6. **Isolate** — log `--stage isolate --event started`. Follow the Git Operation Plan (see below). On success: `--stage isolate --event complete --detail` with mode and branch. On hard stop: `--stage isolate --event stop`.
7. **Implement** that task only (in the isolated workspace). Log `--stage implement --event started` before edits and `--stage implement --event complete` after.
8. **Verify** — log `--stage verify --event started`, then run the task’s Verify commands. On failure: log `--stage verify --event retry`, find root cause, fix, re-verify. Loop until green, then `--stage verify --event pass`.
9. **Review** — log `--stage review --event started`, then invoke requesting-code-review. On findings: log `--stage review --event retry`, find root cause, fix, re-verify, re-review. Loop until clean, then `--stage review --event pass`.
10. **Task summary** — write `.w2c/plans/M###-<slug>/S##-T##-SUMMARY.md` using the task-summary shape below. Do not call `complete` until this file exists and is non-empty. Log `--stage report --event complete --detail task-summary`.
11. **Complete** — `w2c complete --milestone … --slice … --task …`. The CLI refuses without the task summary. It does **not** mark the slice or milestone done.
12. **Slice closeout** — if stdout contains `NEED_SLICE_REPORTS` or `NEED_SLICE_COMPLETE`: re-run every task Verify command in that slice plus the slice Verification section. On failure: fix, re-verify, log `--stage verify --event retry`. Then write `S##-UAT.md` (human checklist, leave boxes unchecked) and `S##-SUMMARY.md` (automated results). Then `w2c slice-complete --milestone … --slice …`. Read `git_delivery` from `.w2c/config.toml`. If it is `slice-commit-milestone-push-pr`: **ask** for explicit approval to make a **local commit** of the product changes (honor `## Commit and PR conventions`; never AI co-author trailers). If the user declines: skip the commit and continue. Do **not** push or open a PR at slice closeout.
13. **Milestone closeout** — if stdout contains `NEED_MILESTONE_REPORTS` or `NEED_MILESTONE_COMPLETE`: run milestone Validation commands and check success criteria. Write `M###-VALIDATION.md` (audit/verdict) and `M###-SUMMARY.md` (what shipped). Then `w2c milestone-complete M###`. Do **not** require `M###-MANUAL-TEST.md` or that the human ran those steps. If Delivery & Guardrails `Manual test guide` is `yes`, print the path to `M###-MANUAL-TEST.md` and say it is for the user to run after closeout — unread/unchecked steps are not a failure. Then honor `git_delivery`:
    - If `milestone-commit-milestone-push-pr`: **ask** for a local commit (same conventions / co-author ban). Decline → skip commit and continue.
    - **Always ask** (separate prompt) to **push** to `origin/<Remote branch>` where Remote branch equals the planned Local branch. Decline → skip push and PR; continue.
    - If push was approved: **ask separately** to **open a PR**. Decline → skip PR; continue.
    Never invent a different remote name. Follow `## Commit and PR conventions`; **never** add `Co-authored-by` or similar AI co-author trailers.
14. **Report** — log `--stage report --event complete`. Then: task id/title, files changed, verify commands + outcomes, review result, which reports were written, isolation mode/branch used, git_delivery gates taken or skipped, blockers.
15. If `--max-units` is set and units remain and the scope still has open tasks: go to step 1. Otherwise STOP.

No-args always stops after one completed or failed unit.

Honor Delivery & Guardrails, **Git Operation Plan**, `git_delivery` from `.w2c/config.toml`, and **Commit and PR conventions**: ask every time before commit / push / PR; decline skips that action only; never AI `Co-authored-by` trailers.

## Isolate step (required)

Read **Git Operation Plan** from the milestone `M###-ROADMAP.md` **and** the slice `M###-S##-PLAN.md`.

- If either is missing, or Isolation mode / Local branch / Remote branch disagree between them: **STOP**. Tell the user to re-run work-to-chores or fix the plans. Do not invent values.
- Local branch must equal Remote branch. If not: **STOP** (smoke should already have failed).

Then:

1. **Reuse policy** — if a worktree or local branch already exists with the exact planned name and clearly belongs to this ticket: reuse it. If dirty with unrelated files, or history looks unexpected: **STOP** and ask. Never force-reset, force-push, or delete worktrees/branches.
2. **Mode `worktree`** — confirm using-git-worktrees is invocable; if missing, STOP. Invoke **using-git-worktrees** and follow it exactly to create or reuse an isolated worktree for Local branch (project `.worktrees/<branch>` when that convention applies). Continue all subsequent work for this ticket in that worktree path. Do not nest a worktree inside an existing linked worktree (skill Step 0).
3. **Mode `branch`** — ensure the current checkout is on Local branch. Create the branch from current HEAD only if it is missing and the tree is clean (or only expected `.w2c` plan dirt after asking). Never force.
4. **Ledger visible** — before the first product edit, verify `.w2c/plans/...` for this milestone is present in the isolation workspace. If not:
   - Read `worktree_ledger` from `.w2c/config.toml` (`symlink` default, or `copy`).
   - Find the primary checkout `.w2c/` (the repo you started from).
   - If mode is `worktree` and the worktree lacks `.w2c/`: create a **symlink** to the primary `.w2c/` when `worktree_ledger = symlink`; otherwise **copy** the directory. Do not git-commit the ledger unless `track = true`.
   - If the primary `.w2c/` is also missing: **STOP** and tell the user to run `w2c init` or `w2c migrate adopt`.

Isolation is **ticket-scoped**: later milestones/slices with the same Remote branch reuse the same worktree/branch.

## Red flags — STOP

- Marking a task complete by editing the markdown checkbox
- Skipping smoke, isolate, verify, requesting-code-review, or closeout reports
- Calling `complete` / `slice-complete` / `milestone-complete` without the required report files
- Continuing after smoke FAIL
- Implementing more than one task when `--max-units` is absent
- Ignoring Git Operation Plan mode/branch or creating a differently named branch
- Implementing from the wrong tree when mode is `worktree`
- Force-reset, force-push, or deleting worktrees/branches
- Pushing or opening a PR without explicit user approval
- Committing without explicit user approval
- Auto-commit / auto-push / auto-PR when the user declined that gate
- Adding `Co-authored-by:` or similar AI co-author trailers on commits or PRs
- Blocking milestone closeout because `M###-MANUAL-TEST.md` steps were not run
- Committing `.w2c/runtime/` or hand-editing `events.jsonl`

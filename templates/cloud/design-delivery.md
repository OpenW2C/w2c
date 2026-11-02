## Delivery Plan

| Field | Value |
| --- | --- |
| Isolation mode | |
| Local branch | |
| Remote branch | |
| Isolation scope | ticket |
| Setup when | first-task |
| Reuse policy | reuse-if-same-ticket-else-stop |
| Worktree skill | |
| Worktree layout | |
| Worktree dir | |
| Exclude line | |
| Push rule | from the delivery policy plus explicit approval; push ref must equal Remote branch |
| Base dirt policy | |
| External ticket ID | |
| Integration strategy | |
| Integration branch | |
| Execution sequence | |
| Validation commands | |
| Completion condition | All slices verified; honor the delivery policy and explicit approval gates |
| Size budget (LOC diff) | |
| Manual test guide | no |

## Guardrails

- **Commit cadence** — follow the delivery policy named in the Delivery Plan. Never commit, push, or open a PR without explicit user approval for that action.
- **Remote mutation** — no push, PR, or remote git mutation without explicit user approval.
- **Git isolation** — honor Isolation mode (`worktree` or `branch` only). Local branch must equal Remote branch. Set up on the first task; reuse the same ticket isolation across changes.
- **No force git** — never force-reset, force-push, or delete worktrees/branches. A dirty or unexpected existing branch or worktree is a hard stop: ask.
- **Validation** — run the validation commands in the Delivery Plan before each commit and before each push.
- **Status writes** — tick task boxes only through the task-tracking command, never by hand. Never hand-edit status fields in the change metadata.
- **Verify loop** — a task is not complete until its verification commands pass and code review is clean.
- **Closeout reports** — write `S##-T##-SUMMARY.md` before completing a task; `S##-UAT.md` and `S##-SUMMARY.md` before completing a slice; `VALIDATION.md` and `SUMMARY.md` before the change is done. All live under `.delivery/`.
- **Commit and PR** — honor `## Commit and PR Conventions`. Never add `Co-authored-by:` or similar AI co-author trailers. Never stage deny-listed paths on product commits. Never mention any `.delivery/` path or local planner file in commit or PR text.

## Commit and PR Conventions

Planner: inspect this repo (`CONTRIBUTING*`, `.github/*PULL_REQUEST_TEMPLATE*`, recent `git log` title and body, `.gitignore`) and fill this section. Do not leave TBD.

**Commit title:**

**Commit body:**

**Pull request:**

**Do not stage / commit:**
Planner: fill a deny-list. Always include `.delivery/` and any local planner files. Add notable paths from the client `.gitignore` (e.g. `.env*`, credentials, local IDE junk). Product commits must never stage these paths.

`openspec/` is product content and is never deny-listed. Product commits stage only this change's folder plus the archive result.

**Do not mention:**
Never name any `.delivery/` path, local planner files, or closeout reports (`*-SUMMARY.md` / `*-UAT.md` / `VALIDATION.md`) in the commit title/body or PR title/body/description. Say "planning artifacts" with no paths.

**AI attribution — forbidden:**
Do not add `Co-authored-by:` trailers or similar AI co-author / "assisted by" lines naming any AI tool.

## Decisions

## Manual Test Guide

## Amendments

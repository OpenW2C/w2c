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
| Push rule | from the change's x-delivery-cadence key plus explicit approval; push ref must equal Remote branch |
| Base dirt policy | |
| External ticket ID | |
| Integration strategy | (from the project's delivery profile) |
| Integration branch | |
| Production branch | |
| Review unit | none |
| Execution sequence | |
| Validation commands | |
| Completion condition | All slices verified; honor x-delivery-cadence and explicit approval gates |
| Size budget (LOC diff) | |
| Manual test guide | no |

When `Base dirt policy` is `leave-untouched`, this plan carries a `### Base dirt paths` subsection listing the critical and other paths. Product commits never stage those paths.

### Delivery profile

When the project keeps a delivery profile, a copy of it sits under this heading.

Record active delivery settings here. Agents read this after the Delivery Plan rows above.

Scope, slices, and tasks live in this change's proposal.md and tasks.md — not in this subsection.

Commit, push and pull-request cadence is the change's `x-delivery-cadence` key only — never duplicate that value in this subsection.

- Task Handoff Gate still applies between tasks even when commits land at slice boundaries (`x-delivery-cadence`).
- Honor this profile for merge targets (`develop` vs `main`); honor `x-delivery-cadence` for when to ask commit/push/PR.

## Guardrails

- **Commit cadence** — commit, push and pull-request timing follows the change's `x-delivery-cadence` key in `.openspec.yaml`. Every commit, push and pull request still needs explicit user approval. Never commit, push, or open a PR without explicit user approval for that action.
- **Remote mutation** — no push, PR, or remote git mutation without explicit user approval.
- **Git isolation** — honor Isolation mode (`worktree` or `branch` only). Local branch must equal Remote branch (the ticket id or a confirmed slug). Set up on the first task; reuse the same ticket isolation across changes.
- **No force git** — never force-reset, force-push, or delete worktrees/branches. A dirty or unexpected existing branch or worktree is a hard stop: ask.
- **Validation** — run the validation commands in the Delivery Plan before each commit and before each push.
- **Status writes** — tick task boxes only through the task-tracking command, never by hand. Never hand-edit status fields in the change metadata.
- **Verify loop** — a task is not complete until its Verify commands pass and requesting-code-review is clean.
- **Closeout reports** — write `S##-T##-SUMMARY.md` before completing a task; `S##-UAT.md` and `S##-SUMMARY.md` before completing a slice; `VALIDATION.md` and `SUMMARY.md` before the change is done. All live under `.delivery/`.
- **Slice closeout order** — after a group's last task, re-run every Verify in that group, then write the slice UAT and slice summary, then complete the slice. After the last group, write `VALIDATION.md` and `SUMMARY.md`, then archive the change, then complete it.
- **Commit and PR** — honor `## Commit and PR Conventions`. Never add `Co-authored-by:` or similar AI co-author trailers. Never stage deny-listed paths on product commits. Never mention any `.delivery/` path or local planner file in commit or PR text.

## Commit and PR Conventions

Planner: inspect this repo (`CONTRIBUTING*`, `.github/*PULL_REQUEST_TEMPLATE*`, recent `git log` title and body, `.gitignore`) and fill this section. Do not leave TBD.

**Commit title:**

**Commit body:**

**Pull request:**

**Do not stage / commit:**
Planner: fill a deny-list. Always include `.delivery/` and any local planner files. Add notable paths from the client `.gitignore` (e.g. `.env*`, credentials, local IDE junk). Product commits must never stage these paths, including any `### Base dirt paths` listed in the Delivery Plan.

`openspec/` is product content and is never deny-listed. Product commits stage only this change's folder plus the archive result.

**Do not mention:**
Never name any `.delivery/` path, local planner files, or closeout reports (`*-SUMMARY.md` / `*-UAT.md` / `VALIDATION.md`) in the commit title/body or PR title/body/description. Say "planning artifacts" with no paths.

**AI attribution — forbidden:**
Do not add `Co-authored-by:` trailers or similar AI co-author / "assisted by" lines naming any AI tool.

## Decisions

## Manual Test Guide

This guide is optional and for a human. It is not a completeness gate: completing the change does not require these steps to have been run.

When to stop and call the change's behavior good enough. This is not a status field.

## Amendments

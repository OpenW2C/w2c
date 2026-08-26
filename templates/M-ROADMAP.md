# MXXX: TITLE

**Vision:**

## Success Criteria

## Slices

## Boundary Map

## In scope

## Out of scope

## Soft dependency

## Delivery & Guardrails
| Field | Value |
| --- | --- |
| Milestone / planning ID | MXXX |
| Human-readable scope slug | SLUG |
| Workstream name | |
| External ticket ID | |
| Integration strategy | trunk-direct |
| Integration branch | |
| Commit cadence | milestone |
| Review unit | none |
| Git/PR checkpoint mode | none |
| Isolation mode | |
| Branch name | |
| Execution sequence | |
| Validation commands | |
| Completion condition | All slices verified; single commit after milestone verification; push only with explicit approval |
| Size budget (LOC diff) | |

## Git Operation Plan
| Field | Value |
| --- | --- |
| Isolation mode | |
| Local branch | |
| Remote branch | |
| Isolation scope | ticket |
| Setup when | first-do-chores |
| Plan commit | required-before-isolation |
| Reuse policy | reuse-if-same-ticket-else-stop |
| Worktree skill | |
| Push rule | after milestone verification + explicit user approval; push ref must equal Remote branch |

### Guardrails
- **Commit cadence** — one commit after the milestone is verified unless this table says otherwise. Do not commit per slice by default.
- **Remote mutation** — no push, PR, or remote git mutation without explicit user approval.
- **Git isolation** — honor Isolation mode (`worktree` or `branch` only). Local branch must equal Remote branch (ticket id or confirmed slug). Setup on first `do-chores`; reuse the same ticket isolation across milestones.
- **Plan commit** — commit `.w2c/` plan/ledger files (never `runtime/`, never product code) onto the ticket branch before isolation so a worktree can see the ledger. No push without approval.
- **No force git** — never force-reset, force-push, or delete worktrees/branches. Dirty or unexpected existing branch/worktree → hard stop and ask.
- **Validation** — run the validation commands in this table before each commit and before each push.
- **Status writes** — never hand-edit STATE.md, QUEUE.md, ROADMAP status emojis, or task checkboxes. Use `w2c` on PATH.
- **Verify loop** — a task is not complete until its Verify commands pass and requesting-code-review is clean.
- **Closeout reports** — write `S##-T##-SUMMARY.md` before `complete`; `S##-UAT.md` + `S##-SUMMARY.md` before `slice-complete`; `M###-VALIDATION.md` + `M###-SUMMARY.md` before milestone DONE.

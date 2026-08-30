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
| Commit cadence | (from .w2c/config.toml git_delivery) |
| Review unit | none |
| Git/PR checkpoint mode | none |
| Isolation mode | |
| Branch name | |
| Execution sequence | |
| Validation commands | |
| Completion condition | All slices verified; honor git_delivery + explicit approval gates |
| Size budget (LOC diff) | |
| Manual test guide | no |

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
| Push rule | from config + explicit approval; push ref must equal Remote branch |

### Guardrails
- **Commit cadence** — read `git_delivery` from `.w2c/config.toml`. Never commit, push, or open a PR without explicit user approval for that action.
- **Remote mutation** — no push, PR, or remote git mutation without explicit user approval.
- **Git isolation** — honor Isolation mode (`worktree` or `branch` only). Local branch must equal Remote branch (ticket id or confirmed slug). Setup on first `do-chores`; reuse the same ticket isolation across milestones.
- **Plan commit** — commit `.w2c/` plan/ledger files (never `runtime/`, never product code) onto the ticket branch before isolation so a worktree can see the ledger. No push without approval.
- **No force git** — never force-reset, force-push, or delete worktrees/branches. Dirty or unexpected existing branch/worktree → hard stop and ask.
- **Validation** — run the validation commands in this table before each commit and before each push.
- **Status writes** — never hand-edit STATE.md, QUEUE.md, ROADMAP status emojis, or task checkboxes. Use `w2c` on PATH.
- **Verify loop** — a task is not complete until its Verify commands pass and requesting-code-review is clean.
- **Closeout reports** — write `S##-T##-SUMMARY.md` before `complete`; `S##-UAT.md` + `S##-SUMMARY.md` before `slice-complete`; `M###-VALIDATION.md` + `M###-SUMMARY.md` before milestone DONE. Manual test steps in `M###-MANUAL-TEST.md` (if opted in) are for the human after DONE — they do not gate completeness.
- **Commit and PR** — honor `## Commit and PR conventions`. Never add `Co-authored-by:` or similar AI co-author trailers.

## Commit and PR conventions

Planner: inspect this repo (`CONTRIBUTING*`, `.github/*PULL_REQUEST_TEMPLATE*`, recent `git log` title/body) and fill this section. Do not leave TBD.

**Commit title:**

**Commit body:**

**Pull request:**

**AI attribution — forbidden:**
Do not add `Co-authored-by:` trailers or similar AI co-author / “assisted by Cursor, Copilot, Claude, or Codex” lines.

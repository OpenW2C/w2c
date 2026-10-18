# {mid}: {title}

**Vision:**

## Success Criteria

## Slices

<!-- One `- [ ] **S0N: <title>**` line per `## N.` group in openspec/changes/{slug}/tasks.md.
     Task checkboxes live only in that tasks.md file. Do not put them in slice plans. -->

## Boundary Map

## In scope

## Out of scope

## Soft dependency

## Delivery & Guardrails
| Field | Value |
| --- | --- |
| Milestone / planning ID | {mid} |
| Human-readable scope slug | {slug} |
| Planning mode | openspec |
| OpenSpec change | {slug} |
| OpenSpec archive | |
| Workstream name | |
| External ticket ID | |
| Integration strategy | (from .w2c/DELIVERY-PROFILE.md) |
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
| Base dirt policy | |

### Guardrails
- **Commit cadence** — read `git_delivery` from `.w2c/config.toml`. Never commit, push, or open a PR without explicit user approval for that action.
- **Remote mutation** — no push, PR, or remote git mutation without explicit user approval.
- **Git isolation** — honor Isolation mode (`worktree` or `branch` only). Local branch must equal Remote branch (ticket id or confirmed slug). Setup on first `do-chores`; reuse the same ticket isolation across milestones.
- **Plan commit** — commit `.w2c/` plan/ledger files (never `runtime/`, never product code) onto the ticket branch before isolation so a worktree can see the ledger. No push without approval.
- **Spec commit** — after plan approval, commit only this change folder under `openspec/changes/` onto the ticket branch. No push without approval.
- **No force git** — never force-reset, force-push, or delete worktrees/branches. Dirty or unexpected existing branch/worktree → hard stop and ask.
- **Validation** — run the validation commands in this table before each commit and before each push.
- **Status writes** — never hand-edit STATE.md, QUEUE.md, ROADMAP status emojis, or task checkboxes. Use `w2c` on PATH. `w2c complete` is the only writer of checkboxes in `tasks.md`.
- **Verify loop** — a task is not complete until its Verify commands pass and requesting-code-review is clean.
- **Closeout reports** — write `S##-T##-SUMMARY.md` before `complete`; `S##-UAT.md` + `S##-SUMMARY.md` before `slice-complete`; `M###-VALIDATION.md` + `M###-SUMMARY.md` before milestone DONE.
- **Commit and PR** — honor `## Commit and PR conventions`. Never add `Co-authored-by:` or similar AI co-author trailers. Never stage deny-listed paths on product commits. Never mention any `.w2c/` path or artifact in commit or PR text.

## Commit and PR conventions

Planner: inspect this repo (`CONTRIBUTING*`, `.github/*PULL_REQUEST_TEMPLATE*`, recent `git log` title/body, `.gitignore`, `.w2c/config.toml` `track`) and fill this section. Do not leave TBD.

**Commit title:**

**Commit body:**

**Pull request:**

**Do not stage / commit:**
Planner: fill a deny-list. Always include `.w2c/runtime/`. When `track = false`, include all of `.w2c/` and Copilot W2C instruction files. Add notable paths from client `.gitignore` (e.g. `.env*`, credentials, local IDE junk). Product commits must never stage these paths. Plan-commit (only when `track = true`) may stage ledger/plan files under `.w2c/` except `runtime/`.

`openspec/` is product content and is never deny-listed. Product commits stage only this change's folder plus the archive result.

**Do not mention:**
Never name any `.w2c/` path, ledger file, closeout report (`*-SUMMARY.md` / `*-UAT.md` / `*-VALIDATION.md` under `.w2c/`), or other W2C artifact in the commit title/body or PR title/body/description. Prefer “W2C ledger” / “planning artifacts” with no paths.

**AI attribution — forbidden:**
Do not add `Co-authored-by:` trailers or similar AI co-author / “assisted by Cursor, Copilot, Claude, or Codex” lines.

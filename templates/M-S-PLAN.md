---
MILESTONE ID: MXXX
SLICE ID: SXX
---

# SXX: TITLE

**Goal:**
**Demo:**

## Must-Haves

## Threat Surface

## Proof Level

## Integration Closure

## Verification

- Run the task and slice verification checks for this slice.

<tasks>
</tasks>

## Files Likely Touched

## Git Operation Plan
| Field | Value |
| --- | --- |
| Isolation mode | |
| Local branch | |
| Remote branch | |
| Follow | milestone Git Operation Plan — do not invent a different branch |

Must match the parent `M###-ROADMAP.md` Git Operation Plan (same Isolation mode, Local branch, and Remote branch).

### Guardrails
- Do not mark tasks complete by editing checkboxes. Use `w2c complete`.
- A task is not done until Verify passes, requesting-code-review is clean, and `S##-T##-SUMMARY.md` is written.
- After the last task in this slice: re-run Verify, write `S##-UAT.md` + `S##-SUMMARY.md`, then `slice-complete`.
- After the last slice: write `M###-VALIDATION.md` + `M###-SUMMARY.md`, then `milestone-complete`.
- Honor this slice Git Operation Plan, the milestone Git Operation Plan, and `git_delivery` from `.w2c/config.toml`. Never commit, push, or open a PR without explicit user approval for that action.
- Honor `## Commit and PR conventions` (copy the filled rules from the milestone ROADMAP; do not say “see parent”). Never add `Co-authored-by:` or similar AI co-author trailers.
- Never force-reset, force-push, or delete worktrees/branches.

## Commit and PR conventions

Copy the filled rules from the parent `M###-ROADMAP.md` into this section. Do not write “see parent”.

**Commit title:**

**Commit body:**

**Pull request:**

**AI attribution — forbidden:**
Do not add `Co-authored-by:` trailers or similar AI co-author / “assisted by Cursor, Copilot, Claude, or Codex” lines.

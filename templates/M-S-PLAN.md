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
- Do not mark tasks complete by editing checkboxes. Use `.w2c/scripts/w2c.sh complete`.
- A task is not done until Verify passes, requesting-code-review is clean, and `S##-T##-SUMMARY.md` is written.
- After the last task in this slice: re-run Verify, write `S##-UAT.md` + `S##-SUMMARY.md`, then `slice-complete`.
- After the last slice: write `M###-VALIDATION.md` + `M###-SUMMARY.md`, then `milestone-complete`.
- Honor this slice Git Operation Plan and the milestone Git Operation Plan. No push or PR without explicit user approval.
- Never force-reset, force-push, or delete worktrees/branches.

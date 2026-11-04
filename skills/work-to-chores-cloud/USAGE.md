# How to use work-to-chores-cloud

Say `work to chores cloud` (or `/work-to-chores-cloud`) and paste a ticket, a spec, or a short description of the work. The agent interviews you, checks the codebase, and writes one OpenSpec change under `openspec/changes/<name>/`. It does not change product code.

The whole plan lives in the repository, so a fresh clone or a temporary container can run it. `design.md` holds six sections: Delivery Plan, Guardrails, Commit and PR Conventions, Decisions, Manual Test Guide, and Amendments. `tasks.md` starts with a read-first block, and each `## N.` group is one slice with eight fields (Goal, Demo, Must-Haves, Threat Surface, Proof Level, Integration Closure, Verification, Files Likely Touched) and its tasks.

Interviews are **evidence-first**: before each question the agent searches the repo and shows facts, then offers a recommended choice plus alternatives with pros, cons, examples, outcomes, and a mermaid diagram. It asks for worktree or branch, the branch name, the base dirt choice, the commit cadence, the commit and pull-request conventions, and whether you want a manual test guide. If `w2c cloud env` says this is a temporary container, it warns that the milestone cadence can lose work and recommends the slice cadence.

After you approve, it runs `w2c cloud new`, writes the files, runs `openspec validate --strict` and `w2c cloud smoke`, and asks before committing the change folder. It does not push, except in a temporary container: there it asks separately whether to push the ticket branch so the plan survives the container.

Say `convert M007` to turn a 2.2 OpenSpec milestone into a cloud change. The agent runs `w2c cloud migrate --milestone M007 --dry-run`, shows you the result, and asks before the real run. Config edits and line rewrites each need their own yes. `w2c cloud migrate --restore` undoes the last run.

`w2c cloud status --all` shows the cloud changes and, when the repo still has one, the local 2.2 state.

Say `reorder changes` to change which pending change runs next, or `amend change <name>` to drop, edit, or add open work. Amendments need one approval of the whole batch and go through the `w2c cloud amend-begin` / `amend-end` commands.

**Need first:** grilling and brainstorming. When a companion skill is missing, the agent asks whether to stop so you can install it, or continue with the written fallback (its written interview).

**Need on this machine:** `w2c` 3.3.0 or later and `openspec`. If `w2c` is missing, the agent asks before running it through `uvx --from git+https://github.com/OpenW2C/w2c@v3.3.0 w2c`.

Then run `do-chores-cloud`.

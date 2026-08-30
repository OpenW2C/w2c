# How to use do-chores

Say `do chores` to do the next small task in the `.w2c/` plan. Add `M011` or `S02` to stay inside that scope. Add `--max-units 5` to do several tasks in a row. Add `--dry-run` to see the next task and planned git isolation (worktree vs branch) without doing either.

Scope only picks the queue. Without `--max-units` the skill always stops after one task.

The skill follows the plan’s **Git Operation Plan** and repo **`git_delivery`**: on the first unit it sets up or reuses the ticket worktree/branch, then implements only inside that isolation. After each slice closeout (when cadence is slice-commit) it **asks** before a local commit. After milestone closeout it may ask for a local commit (milestone cadence), then **asks** to push, then **asks** separately to open a PR. Decline skips that git action only. Commits and PRs follow **Commit and PR conventions** (never add AI `Co-authored-by` trailers). Push only to the planned remote branch name (ticket id / confirmed slug). If the plan opted into a manual test guide, it prints `M###-MANUAL-TEST.md` for you to run; that file does not block milestone completeness.

**Need first:** requesting-code-review. If it is missing, the skill stops and tells you to add it. If the plan’s Isolation mode is `worktree`, **using-git-worktrees** must also be invocable.

**Need on this machine:** `w2c` on PATH (`curl install.sh` or `pipx install git+https://github.com/OpenW2C/w2c.git`). Need in the repo: a `.w2c/` ledger with valid `git_delivery` (`w2c init --git-delivery …`).

Progress logs stay on the machine under `.w2c/runtime/` and are not committed. Task/slice/milestone summaries and UAT/validation reports live in the plan folder; they are committed only when `track = true`.

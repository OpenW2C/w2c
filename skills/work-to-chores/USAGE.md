# How to use work-to-chores

Say `work to chores` (or `/work-to-chores`) and paste a ticket, spec, or a short description of the work. The agent will interview you, check the codebase, and write a plan under `.w2c/`. It will not change product code.

During planning it asks whether to use a **git worktree** or a **branch**, confirms the remote/local branch name (ticket id like `MOR-252`, or a slug if there is no ticket), writes a **Git Operation Plan** into every milestone and slice plan, fills **Commit and PR conventions** from this repo (and forbids AI `Co-authored-by` trailers), and asks whether you want a milestone **manual test** file (`M###-MANUAL-TEST.md`) to run after the milestone is done. After you approve the plan it commits `.w2c/` only when `track = true`. Isolation itself starts on the first `do-chores`.

**Need first:** grilling and brainstorming. If either is missing, the skill stops and tells you to add it. If you choose worktree mode, **using-git-worktrees** must also be invocable.

**Need on this machine:** `w2c` on PATH (`curl install.sh` or `pipx install git+https://github.com/OpenW2C/w2c.git`). Need in the repo: a `.w2c/` ledger (`w2c init`).

Progress logs stay on the machine under `.w2c/runtime/` and are not committed.

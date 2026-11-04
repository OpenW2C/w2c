# How to use do-chores-cloud

Say `do chores cloud` to do the next task of a cloud change. Add `--change <name>` to pick the change. Add `--max-units 3` to do up to three tasks in a row. Without it the skill stops after one task.

The agent does not decide what comes next. It runs `w2c cloud step --json`, does only the one action it names, records the result with `w2c cloud step --record <action> --result <result>`, and asks again. At each new task it runs `w2c cloud brief`, which prints the delivery plan, the guardrails, the conventions, the slice fields, and the task with its Verify line.

Each task goes through smoke, isolation (worktree or branch from the Delivery Plan), implement, verify, review, a task summary, and `w2c cloud complete`. At the end of a slice it writes the slice reports and completes the slice. At the end of the change it writes the validation and summary reports and asks to commit them, then asks to archive, then asks to commit the archive move. The archive removes the `.delivery/` folder, so the earlier commits are what keep the reports in git history.

Every commit, push, and pull request is a question to you. Before a commit or push question the agent runs the plan's validation commands and shows any failure; the answer is still yours. A no skips that action only. A commit or push happens only when the driver asks for it. In a temporary container the agent also asks to push after each slice commit, so the work is not lost. If no one can answer, the agent records `no-answer` and the run stops until someone does. The `.delivery/` reports are committed with the product work, but commit and pull-request text never names them, and no `Co-authored-by` trailer is ever added.

If you ask for something the plan does not cover, the agent stops and points you to an amendment through work-to-chores-cloud.

**Need first:** requesting-code-review. When a companion skill is missing, the agent asks whether to stop so you can install it, or continue with the written fallback (its self-review checklist).

**Need on this machine:** `w2c` 3.1.0 or later and `openspec`. If `w2c` is missing, the agent asks before running it through `uvx --from git+https://github.com/OpenW2C/w2c@v3.1.0 w2c`. No `.w2c/` ledger is needed; only local runtime files are kept under `.w2c/runtime/`.

# W2C (work-to-chores / do-chores)

Markdown planning and execution. Plans live as markdown under `.w2c/` in the **client repo**. A Python CLI is the only writer of status bits (STATE, QUEUE, ROADMAP emojis, task checkboxes).

## Install

Python 3.11+ required.

### curl (CLI + agent skills)

```bash
curl -fsSL https://raw.githubusercontent.com/OpenW2C/w2c/main/install.sh | bash
```

That copies the payload to `~/.local/share/w2c/`, writes `~/.local/bin/w2c`, and installs `work-to-chores` / `do-chores` into `~/.agents/skills` (Cursor and Claude bridges). Add `~/.local/bin` to PATH if needed.

From a checkout:

```bash
bash install.sh --force
```

### pipx (CLI)

```bash
pipx install git+https://github.com/OpenW2C/w2c.git
w2c install-skills
```

`w2c install-skills` copies the skills into `~/.agents/skills` and bridges Cursor/Claude. Use `--force` to replace.

Global config lives at `~/.config/.w2c/config.toml` (project registry). Runtime does not depend on any other checkout path.

### Per-repo ledger

From any directory in a client repo:

```bash
w2c init --git-delivery slice-commit-milestone-push-pr
# or: milestone-commit-milestone-push-pr
# TTY: omit the flag and choose interactively (cannot skip)
w2c init --track --git-delivery slice-commit-milestone-push-pr
```

That writes:

- `.w2c/` ledger (`STATE.md`, `ROADMAP.md`, …)
- `.github/instructions/work-to-chores.instructions.md`
- `.github/instructions/do-chores.instructions.md`
- `.gitignore` entries for `.w2c/` and those Copilot files (unless `--track`; `--track` still ignores `.w2c/runtime/`)

It does **not** overwrite an existing `DECISIONS.md` or `STATE.md`.

Existing clients that already committed `.w2c/`:

```bash
w2c migrate untrack --git-delivery slice-commit-milestone-push-pr
# other clones, before pulling that commit:
w2c migrate adopt --git-delivery slice-commit-milestone-push-pr
```

## How to use (plain English)

**Plan:** Say `work to chores` (or `/work-to-chores`) and paste a ticket, spec, or a short description of the work. The agent will interview you (evidence from the repo first, then recommended + alternatives with trade-offs), check the codebase, and write a plan under `.w2c/` (including Decision Rationale in each `M###-CONTEXT.md`). It will not change product code.

**Do:** Say `do chores` to do the next small task in that plan. Add `M011` or `S02` to stay inside that scope. Add `--max-units 5` to do several tasks in a row. Add `--dry-run` to see the next task without doing it.

**Need first:** grilling and brainstorming for planning; requesting-code-review for doing. If any of those are missing, the skill stops and tells you to add them. Worktree isolation also requires **using-git-worktrees**.

**Need on this machine:** `w2c` on PATH. **Need in the repo:** a `.w2c/` ledger from `w2c init`. If `w2c` is missing, the skill stops and prints the install command.

Cursor and Claude pick the skills up from `~/.agents/skills` after `install.sh` or `w2c install-skills`. Copilot only sees them after `w2c init` writes `.github/instructions/`.

## Git isolation

Every milestone `M###-ROADMAP.md` and slice `M###-S##-PLAN.md` must include a **`## Git Operation Plan`** table and a filled **`## Commit and PR conventions`** section (this repo's commit title/body and PR rules, a deny-list from `.gitignore` + fixed W2C rules, a ban on mentioning any `.w2c/` artifact in commit/PR text, plus an explicit ban on AI `Co-authored-by` trailers).

- **Modes:** `worktree` or `branch` only (no in-place).
- **Branch names:** Local branch == Remote branch == external ticket id (e.g. `MOR-252`) or a confirmed slug when there is no ticket.
- **Scope:** one isolation per ticket; reuse across milestones.
- **Timing:** plan in the current checkout; create/reuse isolation on the **first `do-chores`**. For `worktree`, the executor must invoke **using-git-worktrees** (hard stop if missing).
- **Plan commit:** after writing plans, if `.w2c/config.toml` has `track = true`, `work-to-chores` asks approval to commit only `.w2c/` ledger/plan files onto the ticket branch (never `runtime/`, never product code, no push). Default is untracked; worktrees get `.w2c/` via symlink or copy.
- **`git_delivery` (required in `.w2c/config.toml`):** set at `w2c init` / `migrate` via `--git-delivery` or a TTY prompt (cannot skip). Values:
  - `slice-commit-milestone-push-pr` — ask for a local commit after each slice closeout; after milestone closeout ask to push, then ask to open a PR
  - `milestone-commit-milestone-push-pr` — ask for a local commit after milestone closeout; then ask to push; then ask to open a PR
- **Approvals:** every commit, push, and PR needs its own explicit yes; no skips that action only (ledger still closes). Never auto-commit / auto-push / auto-PR.
- **Push / PR:** push only to `origin/<Remote branch>` exactly; PR is a separate ask after a successful push approval.

### DELIVERY-PROFILE vs `git_delivery`

| Concern | Source of truth |
| --- | --- |
| When to ask commit / push / PR | `.w2c/config.toml` `git_delivery` (cadence only) |
| How code integrates (trunk / feature branch / gitflow) and optional CI doc pointers | `.w2c/DELIVERY-PROFILE.md` (optional) |

`w2c init` does **not** create `DELIVERY-PROFILE.md`. Configure-client or agents write it after interviewing **Integration strategy** (`trunk-direct` \| `feature-branch` \| `gitflow`) and, separately, whether to include **CI/CD pointers** (default path `ai-playbook/mobile/ci-cd/`). Ship template: `templates/DELIVERY-PROFILE.md`; compose helper: `w2c.delivery_profile.compose_delivery_profile`. Absence of the profile does **not** fail `w2c smoke`.

`w2c smoke` **FAIL**s when `schema_version` is outside this install's supported range, `git_delivery` is missing/invalid in `.w2c/config.toml`, the Git Operation Plan is missing, Isolation mode is invalid, Local≠Remote, branch is empty/`N/A`, worktree mode lacks `using-git-worktrees` in the Worktree skill field, a slice disagrees with its milestone, `## Commit and PR conventions` is missing/empty, does not forbid `Co-authored-by`, or lacks deny-list / do-not-mention `.w2c` rules, `Manual test guide` is missing or not `yes`/`no`, or that field is `yes` without a non-empty `M###-MANUAL-TEST.md`. Older plans without these sections must be updated (re-run work-to-chores or add the sections manually) before smoke/handoff will pass.

If `Manual test guide` is `yes`, work-to-chores writes `M###-MANUAL-TEST.md` at plan time. That file is a human walkthrough after the milestone is done; `milestone-complete` does **not** wait on those steps.

The CLI does **not** run git mutations; skills instruct the agent.

## CLI

```bash
w2c <command>
```

| Command | Purpose |
| --- | --- |
| `init [--track] --git-delivery …` | Create ledger stubs; require `git_delivery` (flag or TTY); Copilot files; register repo |
| `install-skills [--force]` | Copy work-to-chores / do-chores into `~/.agents/skills` |
| `migrate untrack|adopt [--git-delivery …]` | Untrack `.w2c/` from git (with backup) or restore after pull; require `git_delivery` if unset |
| `projects` / `register` / `unregister` | Global project registry (`~/.config/.w2c/config.toml`) |
| `gitignore-ensure [--track]` | Ensure default or track gitignore entries |
| `status` | Print STATE.md |
| `next [--milestone M###] [--slice S##] [--task T##]` | Next open task |
| `complete --milestone M### --slice S## --task T##` | Mark task done (requires `S##-T##-SUMMARY.md`; does not close the slice) |
| `slice-complete --milestone M### --slice S##` | Mark slice done (requires `S##-UAT.md` + `S##-SUMMARY.md`) |
| `milestone-complete M###` | Mark milestone DONE (requires `M###-VALIDATION.md` + `M###-SUMMARY.md`) |
| `set --active-milestone M### [--active-slice S##] [--phase NAME]` | Update active pointer |
| `milestone-status M### PLANNING|TODO|PAUSED|INPROGRESS|DONE|ERROR|STOP` | Set milestone emoji/status |
| `next-milestone-id` | Next unused `M###` |
| `milestone-new --slug SLUG` | Allocate id and create plan folder stubs |
| `decide --scope … --decision … --choice … --rationale …` | Append a DECISIONS.md row |
| `context-new --major|--minor` | New `contexts/CONTEXTvX.Y.md` (never overwrite) |
| `event --skill … --stage … --event …` | Append one local runtime event |
| `events [--tail N] [--skill …]` | Print last N local events (`0` = all) |
| `--version` / `-V` | Print installed CLI semver |
| `smoke` | Ledger coherence checks (`schema_version`, `git_delivery`, Git Operation Plan, Commit and PR conventions, optional manual-test guide) |

Agents must not hand-edit STATE.md, QUEUE.md, ROADMAP status emojis, or `[ ]` / `[x]` on tasks.

**Closeout reports** live with the plan folder. Commit them only when `track = true`. The CLI will not flip the matching status bit until those files exist.

**Events are local-only.** They live at `.w2c/runtime/events.jsonl`, which is gitignored. Do not commit logs.

## Source layout

```text
src/w2c/           # Python package (pipx / python -m w2c)
scripts/           # shims for DATA_HOME copies
templates/         # shipped ledger templates; runtime copies live in ~/.local/share/w2c/templates (or $W2C_DATA_HOME/templates)
skills/            # work-to-chores, do-chores
install.sh         # curl installer
tests/
```


## Versioning

**Hard rule:** every change in this repo bumps the package version in the same change. No “docs-only / skills-only / tiny fix” exceptions. Agents: see [AGENTS.md](AGENTS.md).

Check the installed CLI:

```bash
w2c --version
# or: w2c -V
```

Each project's `.w2c/config.toml` records:

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer ledger format. Bumped only when the on-disk `.w2c/` shape changes. |
| `w2c_version` | CLI semver that last wrote the config (informational). |

`w2c init` / `migrate` (and other config writes) stamp both fields. `w2c smoke` compares `schema_version` to this install's supported range and fails with upgrade or migrate guidance on drift.

### What level to bump (major / minor / patch)

| Bump | Use when |
| --- | --- |
| **MAJOR** `X.0.0` | Breaking change: CLI contract breaks, required config removed/renamed, older installs cannot use the ledger without migrate, or existing skills/workflows break. |
| **MINOR** `x.Y.0` | Backward-compatible feature: new command/flag, optional config, new template/section, new skill capability, new smoke rules for newly invalid ledgers. |
| **PATCH** `x.y.Z` | Bug fix, docs, tests, or internal refactor with **no** user-facing behavior change. |

Unsure minor vs patch → prefer **minor** if users/skills must learn new behavior. Unsure major vs minor → prefer **major** (or while on `0.x`, **minor** plus an explicit BREAKING note in the changelog).

### Releasing a new version (required every change)

1. Choose major / minor / patch (table above).
2. Bump `version` in `pyproject.toml` and `__version__` in `src/w2c/__init__.py` to the **same** semver.
3. Add a Keep a Changelog entry at the top of `CHANGELOG.md`.
4. If a skill newly depends on this release, update `Requires: w2c >= X.Y.Z` in that `SKILL.md`.
5. If the `.w2c/` file format changed, bump `CURRENT_SCHEMA_VERSION` in `src/w2c/local.py` (and raise `MIN_SUPPORTED_SCHEMA_VERSION` only when older schemas are no longer readable without migrate). Schema bumps are **in addition to** the package semver bump.

### Skills: required CLI version

When a skill depends on a CLI feature introduced in a specific release, add a body line near the top of its `SKILL.md`:

```text
Requires: w2c >= X.Y.Z
```

Consumers compare that against `w2c --version`. There is no separate capabilities command — semver is the capability map.

## License

MIT

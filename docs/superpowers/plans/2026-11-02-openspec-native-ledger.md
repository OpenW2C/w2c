# OpenSpec Cloud Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in cloud mode (`w2c cloud …` plus a separate skill pair) that keeps every rule and state of an OpenSpec milestone in the committed change, while the 2.2.0 flow stays the default and unchanged.

**Architecture:** All cloud code lives in a new package, `src/w2c/cloud/`, registered as one `cloud` subcommand group. The existing `cli.py` gains only that registration, one session rule, one additive `CLOUD_MOVED` message, the `cloud` planning value, and additive cloud checks in the shared pre-push hook and `base-dirt`. A full-cycle test, built first against today's behavior, proves the 2.2 flow stays unchanged.

**Tech Stack:** Python 3.11 standard library only, `unittest`, the OpenSpec command-line program (floor 1.14.3; CI also runs 1.16.0), the fake OpenSpec fixture for unit tests, the real program for the full-cycle test.

**Spec:** `docs/superpowers/specs/2026-11-02-openspec-native-ledger-design.md`

## Global Constraints

- The 2.2 flow keeps byte-identical outputs: the legacy suite's stored expectations from Task 0 must not change in any later task.
- `pyproject.toml` `dependencies = []` stays empty. Edit `.openspec.yaml` line by line; do not add a YAML library.
- OpenSpec floor stays `MIN_OPENSPEC_VERSION = (1, 14, 3)`. The `W2C-OPENSPEC-RULES` marker stays.
- Names, exactly: command group `w2c cloud`; skills `work-to-chores-cloud`, `do-chores-cloud`; planning value `cloud`; folder `.delivery/`; keys `x-delivery-status`, `x-delivery-order`, `x-delivery-cadence`, `x-delivery-slices-done`, `x-delivery-amend-lock`, `x-delivery-amend-prior-status`, `x-delivery-amend-decision`, `x-delivery-archive`, `x-delivery-legacy-id`; files `openspec/knowledge.md`, `openspec/decisions.md`; markers `SLICE-TASK-RULES`, `DELIVERY-SECTIONS-RULES`, `READ-FIRST`; Copilot files `plan-work.instructions.md`, `do-work.instructions.md`.
- `design.md` headings, exactly: `## Delivery Plan`, `## Guardrails`, `## Commit and PR Conventions`, `## Decisions`, `## Manual Test Guide`, `## Amendments`.
- Slice fields in each `tasks.md` `## N.` group, exactly: `**Goal:**`, `**Demo:**`, `**Must-Haves:**`, `**Threat Surface:**`, `**Proof Level:**`, `**Integration Closure:**`, `**Verification:**`, `**Files Likely Touched:**`.
- Stop sentence, exactly: `Run this change only with the do-chores-cloud skill. If it is not available, stop and ask the user.`
- Cloud config rules start with: `For a change whose .openspec.yaml has x-delivery-status:`.
- Report files in `.delivery/`: `S##-T##-SUMMARY.md`, `S##-UAT.md`, `S##-SUMMARY.md`, `VALIDATION.md`, `SUMMARY.md`.
- The string `w2c` (any case) never appears in a file the CLI writes under `openspec/`, except text copied from a legacy source and listed for manual edit.
- Statuses: `PLANNING`, `TODO`, `INPROGRESS`, `PAUSED`, `STOP`, `ERROR`, `DONE`. Cadences: `slice-commit-milestone-push-pr`, `milestone-commit-milestone-push-pr`.
- Step actions, exactly: `smoke`, `isolate`, `implement`, `verify`, `review`, `write-report`, `complete`, `slice-reports`, `slice-complete`, `milestone-reports`, `ask-commit`, `ask-push`, `ask-archive`, `ask-pr`, `done`, `stop`. Record results: `pass`, `fail`, `yes`, `no`, `no-answer`.
- Decision ids inside a change are `D1`, `D2`, …; amendment ids stay `A001`, ….
- Unit tests: `PYTHONPATH=src python3 -m unittest discover -s tests`. Full cycle: `python3 scripts/w2c-e2e.py --suite all` (needs `openspec` on `PATH`).
- Version: no task bumps the version except Task 15, which sets 3.0.0 once for the whole scope, with one CHANGELOG entry, in the same pull request as all other tasks (AGENTS.md "same commit / PR"). Later tasks never add CHANGELOG entries of their own.

## Review Focus

1. A hand-edited `.openspec.yaml` with CRLF line ends, a comment, quoted values, or a duplicate `x-delivery-*` key must read predictably: CRLF and comments tolerated, quotes stripped, a duplicate is an error naming the file and key. Test in Task 1.
2. After branches merge, two changes can share one `x-delivery-legacy-id`, or a change name can equal another change's legacy id. `resolve()` must refuse with both names listed. Test in Task 1.
3. A fresh clone with no `.w2c/` must run `w2c cloud next`, `complete`, `slice-complete`, `archive`, `smoke`, and `step` without creating `STATE.md`, `QUEUE.md`, or `ROADMAP.md`; only files under `.w2c/runtime/` may appear. Tests in Tasks 5 and 9, and the cloud suite.
4. A conversion that stops halfway must be safe to run again, and `--restore` must bring back the exact backup. Test in Task 12.
5. A 2.2 command run in a mixed repo must neither see nor change a cloud change, and a cloud command must neither see nor change a 2.2 milestone. Test in Task 8 and the mixed-repo stage.

---

### Task 0: Full-cycle test harness and the legacy suite

**Files:**
- Create: `scripts/w2c-e2e.py`, `tests/e2e/__init__.py`, `tests/e2e/harness.py`, `tests/e2e/legacy_suite.py`, `tests/e2e/expected/legacy/` (stored outputs), `tests/test_e2e_harness.py`
- Modify: `.github/workflows/ci.yml` (new job `e2e`: Node 22, `npm install -g @fission-ai/openspec@${{ matrix.openspec }}` with `matrix.openspec: ["1.14.3", "1.16.0"]`, run `python3 scripts/w2c-e2e.py --suite all --report e2e-report.md`, upload `e2e-report.md` as an artifact)

**Interfaces:**
- Produces in `harness.py`:
  - `@dataclass Stage: id: str; title: str; run: Callable[[Project], None]`
  - `@dataclass Project: root: Path; remote: Path; home: Path; env: dict[str, str]` with `w2c(*args, cwd=None, check=True) -> subprocess.CompletedProcess[str]` (runs the installed `w2c` from `home/.local/bin`), `git(*args, cwd=None)`, `write(rel, text)`, `expect_tokens(proc, *tokens)`, `expect_matches(rel_output_name, text)` (compares to `tests/e2e/expected/<suite>/<name>` after replacing the temp paths and dates with `<ROOT>` and `<DATE>`; `W2C_E2E_UPDATE=1` rewrites the stored file).
  - `make_project(tmp: Path) -> Project`: a small Python app (`app/calc.py`, `tests/test_calc.py`), `git init`, a bare repo as `origin`, and `bash install.sh` with `W2C_DATA_HOME` and `HOME` inside `tmp`.
  - `run_suite(stages: list[Stage], project_factory) -> list[tuple[Stage, bool, str]]` (stops at the first failure; later stages are reported as not run).
  - `write_report(results, path: Path) -> None`: one `- [x] <id> <title>` or `- [ ] <id> <title> — <error>` line per stage, last line `E2E: PASS` or `E2E: FAIL`.
- Produces in `scripts/w2c-e2e.py`: `--suite legacy|cloud|all` (default `all`), `--report PATH`; exit 0 only when every stage passed. A missing `openspec` program is a failure, not a skip.
- Legacy stages in `legacy_suite.py`, each asserting exact tokens and stored outputs:
  - L01 install, `w2c --version` equals the package version;
  - L02 `init --git-delivery slice-commit-milestone-push-pr` (files, gitignore lines, Copilot file names);
  - L03 `milestone-new` in OpenSpec mode, artifacts written, `smoke --milestone` passes;
  - L04 `decide`, `context-new`, reorder with a second milestone;
  - L05 branch mode with `base-dirt` and worktree mode with `worktree-add`;
  - L06 `next`, `complete` refused without a summary then accepted, `slice-complete`;
  - L07 commit and push to the bare remote through the installed pre-push hook;
  - L08 amendment (`amend-begin`, `drop-task`, `task-add`, `amend-end`);
  - L09 closeout: reports, `openspec-push-check` fails, `spec-archive`, `milestone-complete`, push passes;
  - L10 a classic milestone's full cycle;
  - L11 `w2c trials`.

- [ ] **Step 1: Write the failing harness tests** in `tests/test_e2e_harness.py`: `test_report_lists_each_stage_and_verdict` (two fake stages, one failing → the report has `- [x] S1 …`, `- [ ] S2 … — <error>`, and `E2E: FAIL`), `test_missing_openspec_fails` (empty `PATH` → exit 1 with `openspec not found`), `test_expected_output_masks_paths_and_dates`.
- [ ] **Step 2: Run** `PYTHONPATH=src python3 -m unittest tests.test_e2e_harness -v` — expected: import error.
- [ ] **Step 3: Implement the harness and the legacy stages**, then create the stored outputs once with `W2C_E2E_UPDATE=1 python3 scripts/w2c-e2e.py --suite legacy` and read them for correctness.
- [ ] **Step 4: Run** `python3 scripts/w2c-e2e.py --suite legacy --report e2e-report.md` with OpenSpec 1.14.3 and then 1.16.0 on `PATH` — expected: exit 0, last line `E2E: PASS`. Run the unit suite — expected: `OK`.
- [ ] **Step 5: Commit** `git commit -m "Add a full-cycle test that runs the current flow on a dummy project."`

From here on, every task ends by running `python3 scripts/w2c-e2e.py --suite all` and expecting `E2E: PASS`. Tasks that add cloud behavior add stages to `tests/e2e/cloud_suite.py` (created in Task 2) with ids `C01`, `C02`, ….

### Task 1: Change ledger

**Files:**
- Create: `src/w2c/cloud/__init__.py`, `src/w2c/cloud/ledger.py`
- Test: `tests/test_cloud_ledger.py`

**Interfaces:**
- Produces in `w2c.cloud.ledger`:
  - `STATUSES: tuple[str, ...]`; `CADENCES = w2c_local.GIT_DELIVERY_VALUES`
  - `@dataclass CloudChange: name: str; path: Path; status: str; order: int | None; cadence: str; slices_done: list[int]; legacy_id: str; archived: bool; archive: str; amend_lock: str; amend_prior_status: str; amend_decision: str`
  - `read_keys(meta: Path) -> dict[str, str]` — top-level `key: value` lines; raises `W2CError` on a duplicate `x-delivery-*` key.
  - `write_key(meta: Path, key: str, value: str | None) -> None` — replace, append, or remove (`None`); atomic; other lines byte-for-byte.
  - `load_change(path: Path) -> CloudChange | None` — `None` without `x-delivery-status`.
  - `list_changes(root: Path, *, include_archived: bool = False) -> list[CloudChange]` — sort key `(order is None, order or 0, name)`; archived names drop the `YYYY-MM-DD-` prefix.
  - `resolve(root: Path, ident: str) -> CloudChange` — active by name, then archived by name, then by `legacy_id`; `W2CError` on none or on two matches at the winning rank.
  - `remote_branch(change: CloudChange) -> str` — `Remote branch` row of `design.md` `## Delivery Plan`.
  - `branch_names(root: Path) -> set[str] | None` — active names whose remote branch is the current branch; `None` without a branch or a match.
  - `delivery_dir(change: CloudChange) -> Path`
- [ ] **Step 1: Write the failing tests:** `test_write_key_round_trip_keeps_other_lines` (list value `"[1, 3]"`, removal), `test_read_keys_tolerates_crlf_comments_quotes`, `test_duplicate_delivery_key_is_error`, `test_list_changes_orders_by_order_then_name` (`b`=1, `a`=none, `c`=1 → `["b", "c", "a"]`), `test_list_changes_skips_non_cloud_and_reads_archive`, `test_resolve_prefers_active_then_archive_then_legacy_id`, `test_resolve_refuses_ambiguous_legacy_id`, `test_branch_names_none_on_detached_head_or_no_match`.
- [ ] **Step 2: Run** `PYTHONPATH=src python3 -m unittest tests.test_cloud_ledger -v` — expected: import error.
- [ ] **Step 3: Implement** `ledger.py`; import `cli` lazily through `_cli()`, as `openspec_ledger.py` does.
- [ ] **Step 4: Run** the unit suite and the full cycle — expected: pass.
- [ ] **Step 5: Commit** `git commit -m "Read and write delivery keys on OpenSpec changes."`

### Task 2: The `w2c cloud` group, the `cloud` planning value, and `env`

**Files:**
- Create: `src/w2c/cloud/cli.py`, `src/w2c/cloud/environment.py`, `tests/e2e/cloud_suite.py`
- Modify: `src/w2c/cli.py` (`build_parser` calls `cloud_cli.register(sub)`; `dispatch` adds `if cmd == "cloud": return cloud_cli.dispatch(args)`; `main` skips the ledger session when `args.cmd == "cloud"` and `args.cloud_cmd not in {"migrate", "status"}`; `init --planning` choices gain `cloud`), `src/w2c/local.py` (`PLANNING_CLOUD = "cloud"` added to `PLANNING_VALUES`)
- Test: `tests/test_cloud_cli.py`

**Interfaces:**
- Produces: `register(sub: argparse._SubParsersAction) -> None` (adds the `cloud` parser with `dest="cloud_cmd"`, required); `dispatch(args: argparse.Namespace) -> int`; `ephemeral_reason(env: Mapping[str, str] | None = None) -> str | None`; `cmd_env() -> int`.
- `env` rules: `W2C_EPHEMERAL` `1`/`true` → reason `W2C_EPHEMERAL`; `0`/`false` → `None`; otherwise the first of `CLAUDE_CODE_REMOTE`, `CODESPACES`, `GITHUB_ACTIONS` with a value that is not empty, `0`, or `false`. Output, exactly: `ephemeral: true|false` then `reason: <NAME>|none`.
- The legacy `milestone-new` with planning `cloud` exits 1 with `use w2c cloud new`.
- [ ] **Step 1: Write the failing tests:** `test_each_variable_marks_ephemeral`, `test_false_values_are_ignored`, `test_override_wins_both_ways`, `test_cmd_env_prints_two_lines`, `test_cloud_group_needs_a_subcommand`, `test_init_accepts_cloud_planning`, `test_legacy_milestone_new_refuses_cloud_default`.
- [ ] **Step 2: Run** `PYTHONPATH=src python3 -m unittest tests.test_cloud_cli -v` — expected: fail.
- [ ] **Step 3: Implement**, and add cloud stage `C01`: `w2c init --planning cloud --git-delivery slice-commit-milestone-push-pr`, then `w2c cloud env` with `W2C_EPHEMERAL=1`.
- [ ] **Step 4: Run** the unit suite and `python3 scripts/w2c-e2e.py --suite all` — expected: pass; the legacy stored outputs are unchanged.
- [ ] **Step 5: Commit** `git commit -m "Add the opt-in cloud command group and temporary-container detection."`

### Task 3: Layout constants, neutral templates, conditional config rules

**Files:**
- Create: `src/w2c/cloud/layout.py`, `templates/cloud/design-delivery.md`, `templates/cloud/tasks-read-first.md`, `templates/cloud/slice-group.md`, `templates/cloud/reports/TASK-SUMMARY.md`, `SLICE-UAT.md`, `SLICE-SUMMARY.md`, `VALIDATION.md`, `SUMMARY.md`
- Test: `tests/test_cloud_templates.py`

**Interfaces:**
- Produces in `layout.py`:
  - `DESIGN_HEADINGS`, `SLICE_FIELDS`, `DELIVERY_PLAN_FIELDS`;
  - `LEGACY_DROPPED_FIELDS: dict[str, str]` and `LEGACY_DROPPED_GUARDRAILS: dict[str, str]` (each name → new home or reason);
  - `STOP_SENTENCE`, `RULE_PREFIX`, `REPORT_DIR = ".delivery"`, `SLICE_TASK_MARKER`, `DESIGN_MARKER`, `READ_FIRST_MARKER`;
  - `CONFIG_RULES_SNIPPET`: `context:` pointing to `openspec/knowledge.md`; `rules.design` and `rules.tasks` lines each starting with `RULE_PREFIX`; `operations.apply.guidance` holding the read-first pointer and `STOP_SENTENCE`.
- `## Delivery Plan` rows: Isolation mode, Local branch, Remote branch, Isolation scope, Setup when, Reuse policy, Worktree skill, Worktree layout, Worktree dir, Exclude line, Push rule, Base dirt policy, External ticket ID, Integration strategy, Integration branch, Execution sequence, Validation commands, Completion condition, Size budget (LOC diff), Manual test guide.
- `LEGACY_DROPPED_FIELDS` keys, exactly: `Milestone / planning ID`, `Human-readable scope slug`, `Planning mode`, `OpenSpec change`, `OpenSpec archive`, `Workstream name`, `Commit cadence`, `Review unit`, `Git/PR checkpoint mode`, `Branch name`, `Plan commit`. `LEGACY_DROPPED_GUARDRAILS` keys: `Plan commit`, `Spec commit`.
- [ ] **Step 1: Write the failing tests:**
  - `test_cloud_templates_never_name_the_tool` (no `w2c` in any case under `templates/cloud/`).
  - `test_guardrail_parity_with_legacy_roadmap`: every bold label under `### Guardrails` in `templates/openspec/M-ROADMAP.md` appears under `## Guardrails`, except the dropped keys.
  - `test_field_parity_with_legacy_tables`: every row of the legacy `Delivery & Guardrails` and `Git Operation Plan` tables is a `## Delivery Plan` row or a dropped key with a non-empty reason.
  - `test_slice_field_parity`: every slice-plan heading from Must-Haves to Files Likely Touched, plus Goal and Demo, is a slice field.
  - `test_every_cloud_rule_is_conditional`.
  - `test_legacy_templates_unchanged`: hashes of `templates/openspec/*` and `templates/*.md` equal their Task 0 values.
- [ ] **Step 2: Run** `PYTHONPATH=src python3 -m unittest tests.test_cloud_templates -v` — expected: fail.
- [ ] **Step 3: Write the module and templates.**
- [ ] **Step 4: Run** the unit suite and the full cycle — expected: pass.
- [ ] **Step 5: Commit** `git commit -m "Add neutral templates and conditional OpenSpec rules for cloud changes."`

### Task 4: Artifact checks

**Files:**
- Create: `src/w2c/cloud/checks.py`
- Modify: `src/w2c/cli.py` (`base_dirt_paths_body(text, heading="Git Operation Plan")`, `validate_git_operation_plan(..., plan_heading="Git Operation Plan")`; defaults keep today's behavior), `src/w2c/openspec_ledger.py` (extract `live_checks(root: Path, name: str, tasks_path: Path, mid: str) -> tuple[list[str], list[str], list[str]]`; `smoke_checks` calls it with unchanged output)
- Test: `tests/test_cloud_checks.py`

**Interfaces:**
- Produces:
  - `slice_fields(tasks_text: str) -> dict[int, dict[str, str]]`;
  - `validate_conventions(design_text: str) -> list[str]` (requires a Co-authored-by ban, a stage ban, a mention ban containing `.delivery/`, and the `openspec/` product-content sentence; never requires `.w2c`);
  - `smoke_rows(root: Path, changes: list[CloudChange]) -> list[tuple[str, str, str]]`, with the rows named in the spec's Smoke checks table plus `openspec-cli`, `openspec-validate-strict`, `openspec-artifacts-complete`, `openspec-tasks-have-verify`, `openspec-progress-agrees`, and `openspec-archived-when-done`. Archived changes skip the live OpenSpec rows.
- [ ] **Step 1: Write the failing tests:** a valid fixture change passes every row, and one mutation per test flips exactly one row. Add `test_group_text_is_not_a_task` and `test_legacy_smoke_output_unchanged` (the OpenSpec smoke in `tests/test_openspec.py` prints the same rows as before).
- [ ] **Step 2: Run** `PYTHONPATH=src python3 -m unittest tests.test_cloud_checks tests.test_openspec -v` — expected: fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the unit suite and the full cycle — expected: pass.
- [ ] **Step 5: Commit** `git commit -m "Check design sections, slice fields, and reports on cloud changes."`

### Task 5: Core cloud commands

**Files:**
- Create: `src/w2c/cloud/commands.py`
- Modify: `src/w2c/cloud/cli.py`, `tests/e2e/cloud_suite.py`
- Test: `tests/test_cloud_commands.py`

**Interfaces:**
- Produces, each wired as `w2c cloud <name>`:
  - `new(root, slug, cadence: str | None) -> int`:
    - runs `openspec new change`;
    - writes `x-delivery-status: PLANNING`, `x-delivery-order` = highest active order + 1, and `x-delivery-cadence` from `--cadence`, else the local `git_delivery`, else prints `NEED_CADENCE` and exits 1;
    - calls `ensure_knowledge`;
    - prints `created openspec/changes/<slug> (<slug>)`.
  - `ensure_knowledge(root) -> list[str]`: creates `openspec/knowledge.md` (`# Project Knowledge` plus the three tables of today's `CONTEXT_BODY`, without the tool name) and the `.gitattributes` line when missing.
  - `cloud_tasks(root) -> list[cli.Task]` (`Task.mid` is the change name), `next_task(root, change: str | None, slice_id: str | None, task_id: str | None) -> cli.Task | None` (prefers `INPROGRESS`, then `PLANNING`/`TODO`; skips locked changes; scoped by `branch_names`).
  - `next_cmd(...) -> int`: prints `NEXT <name> <S##> <T##> — <title>` plus the same JSON shape as today.
  - `status(root, all_: bool) -> int`: one `<emoji> <name>: <done>/<total> tasks` line per change, then `Next: …`. With `--all`, also prints `.w2c/STATE.md` when present.
  - `complete(root, change, sid, tid) -> int` and `slice_complete(root, change, sid) -> int`: today's gates and tokens, with reports in `.delivery/`. `complete` moves `PLANNING`/`TODO`/`PAUSED` to `INPROGRESS`. `slice_complete` appends to `x-delivery-slices-done`.
  - `archive(root, change) -> int`: every group done or dropped and listed in `slices-done`; `VALIDATION.md` and `SUMMARY.md` present; delete `.delivery/`; write `DONE`; run `openspec archive`; print `archived <name> as <archivedAs>`.
  - `milestone_complete(root, change, archive_declined: bool) -> int`:
    - archived → print `<name> -> DONE`;
    - declined → same gates, keep `.delivery/`, write `DONE` and `x-delivery-archive: declined`;
    - otherwise → error `run w2c cloud archive <name> or pass --archive-declined`.
  - `status_set(root, change, status) -> int`: any status but `DONE`.
- [ ] **Step 1: Write the failing tests:**
  - `test_new_writes_keys_and_no_ledger_files`;
  - `test_new_without_cadence_prints_need_cadence`;
  - `test_new_creates_knowledge_once`;
  - `test_next_and_complete_in_fresh_clone` (Review Focus 3);
  - `test_slice_complete_records_slices_done_and_tokens`;
  - `test_archive_gates_then_deletes_delivery_and_marks_done`;
  - `test_milestone_complete_declined_keeps_reports`;
  - `test_status_all_appends_state`;
  - `test_legacy_commands_ignore_cloud_changes` (`w2c next` in a repo with only a cloud change prints `NEXT none`).
- [ ] **Step 2: Run** `PYTHONPATH=src python3 -m unittest tests.test_cloud_commands -v` — expected: fail.
- [ ] **Step 3: Implement**, and add cloud stages: `C02` new change from templates plus `openspec validate --strict`, `C03` next/complete/slice-complete, `C04` closeout and archive.
- [ ] **Step 4: Run** the unit suite and the full cycle — expected: pass.
- [ ] **Step 5: Commit** `git commit -m "Run cloud milestones from change keys without a local ledger."`

### Task 6: Decisions and reorder

**Files:**
- Modify: `src/w2c/cloud/commands.py`, `src/w2c/cloud/cli.py`, `tests/e2e/cloud_suite.py`
- Test: `tests/test_cloud_commands.py`

**Interfaces:**
- Produces:
  - `PENDING_DECISIONS = Path(".w2c/runtime/pending-decisions.jsonl")`, one JSON object per line: `when`, `scope`, `decision`, `choice`, `rationale`, `revisable`, `made_by`.
  - `decide(root, change: str | None, row: dict[str, str]) -> int`:
    - with a `## Decisions` section, appends to the table `| # | When | Scope | Decision | Choice | Rationale | Revisable? | Made By |` (created when absent), using id `D<n+1>`;
    - otherwise holds the row and prints `PENDING`.
  - `decisions_flush(root, change) -> int`: moves held rows in file order, then truncates; refuses without `## Decisions`.
  - `order(root, names: list[str])`, `swap(root, left, right)`, `move(root, name, before, after)`: rewrite `x-delivery-order` on the branch's active changes, refusing moves across `INPROGRESS` or `DONE` (reuse `cli.assert_reorder_allowed` through `cli.Milestone`).
- [ ] **Step 1: Write the failing tests:** `test_decide_before_design_is_pending_then_flushed_in_order`, `test_decide_with_design_appends_next_id`, `test_flush_refuses_without_decisions_section`, `test_reorder_rewrites_order_keys_and_refuses_inprogress`.
- [ ] **Step 2: Run** them — expected: fail.
- [ ] **Step 3: Implement**, and add stage `C05` (decide before design, flush, reorder two changes).
- [ ] **Step 4: Run** the unit suite and the full cycle — expected: pass.
- [ ] **Step 5: Commit** `git commit -m "Keep cloud decisions and run order inside each change."`

### Task 7: Amendments

**Files:**
- Create: `src/w2c/cloud/amend.py`
- Modify: `src/w2c/cloud/cli.py`, `tests/e2e/cloud_suite.py`
- Test: `tests/test_cloud_amend.py`

**Interfaces:**
- Produces `amend_begin`, `amend_end`, `amendments`, `drop_task`, `drop_slice`, `task_add`, `task_edit`, `slice_add`, `follow_up`, with today's parameters (a change instead of a milestone id), wired under the same command names.
- Rules:
  - The lock lives in the three amend keys.
  - `--decision` must exist in the change's `## Decisions` table.
  - Records go under `## Amendments` as `### A00n <kind> <name>/<S##>[/<T##>]` plus today's four bullet lines.
  - `drop_slice` marks every task of the group `[d]`.
  - `slice_add` appends `## N. <title>` with empty slice fields.
  - `amend_end` runs `smoke_rows` for the change and keeps the lock on any `FAIL`.
- [ ] **Step 1: Write the failing tests**, mirroring each amendment test in `tests/test_w2c.py`, plus `test_slice_add_blocks_amend_end_until_fields_filled` and `test_unknown_decision_id_is_refused`.
- [ ] **Step 2: Run** `PYTHONPATH=src python3 -m unittest tests.test_cloud_amend -v` — expected: fail.
- [ ] **Step 3: Implement**, and add stage `C06` (begin, drop, add, end).
- [ ] **Step 4: Run** the unit suite and the full cycle — expected: pass.
- [ ] **Step 5: Commit** `git commit -m "Record cloud amendments in the design and lock them in change keys."`

### Task 8: Cloud smoke, shared hooks, and `CLOUD_MOVED`

**Files:**
- Modify: `src/w2c/cloud/cli.py` (`w2c cloud smoke [--change NAME]`), `src/w2c/openspec_push.py` (`problems_for` adds the cloud check), `src/w2c/openspec_ledger.py` (`change_prefixes` adds active cloud change folders), `src/w2c/cli.py` (`cmd_next`: when `--milestone M###` is not in `ROADMAP.md` and `.w2c/plans/M###-*/CONVERTED` exists, print `CLOUD_MOVED M### <change>` and exit 0), `tests/e2e/cloud_suite.py`
- Test: `tests/test_cloud_commands.py`, `tests/test_worktree_ledger.py`

**Interfaces:**
- `w2c cloud smoke` prints rows in today's `Report.print` format and runs without `.w2c/`.
- Cloud push check: a cloud change on the pushed branch whose tasks and groups are all closed needs `openspec/changes/archive/*-<name>/.openspec.yaml` in the pushed commit (`git ls-tree --name-only <sha> openspec/changes/archive/`, then `cat-file -e`). A declined archive fails with `archive is declined`.
- `CONVERTED` file body: one line, `<change name>`.
- [ ] **Step 1: Write the failing tests:**
  - `test_cloud_smoke_in_fresh_clone`;
  - `test_cloud_smoke_change_filter`;
  - `test_push_check_requires_archived_cloud_change`;
  - `test_push_check_fails_declined`;
  - `test_base_dirt_skips_cloud_change_folder`;
  - `test_cloud_moved_message` (Review Focus 5);
  - `test_cloud_change_in_linked_worktree_needs_no_ledger_sync`;
  - `test_legacy_push_check_unchanged`.
- [ ] **Step 2: Run** them — expected: fail.
- [ ] **Step 3: Implement**, and add stage `C07` (push blocked before archive, allowed after).
- [ ] **Step 4: Run** the unit suite and the full cycle — expected: pass.
- [ ] **Step 5: Commit** `git commit -m "Smoke-check cloud changes and guard their push without changing the current flow."`

### Task 9: Step driver and `brief`

**Files:**
- Create: `src/w2c/cloud/driver.py`
- Modify: `src/w2c/cloud/cli.py` (`w2c cloud step [--change NAME] [--json] [--record ACTION --result RESULT]`, `w2c cloud brief [--change NAME]`), `tests/e2e/cloud_suite.py`
- Test: `tests/test_cloud_driver.py`

**Interfaces:**
- Produces:
  - `STEP_STATE = Path(".w2c/runtime/step.json")` holding `change`, `task`, `last_action`, `last_result`.
  - `next_action(root: Path, change: str | None) -> dict` with keys `action`, `change`, `slice`, `task`, `files`, `reason`.
  - `record(root: Path, action: str, result: str) -> None`.
  - `brief(root: Path, change: str | None) -> str`.
- Order of `next_action`, first match wins:
  1. No active cloud change on the branch → `done`.
  2. The change has an amendment lock → `stop`, reason `AMEND_LOCK`.
  3. Not yet smoked in this state, or the last smoke failed → `smoke`; a recorded `fail` → `stop`, reason `smoke`.
  4. The current branch is not the Delivery Plan's Remote branch → `isolate`.
  5. An open task:
     - the stage sequence is `implement` → `verify` → `review` → `write-report` → `complete`;
     - a `fail` on `verify` or `review` returns `implement`;
     - a missing or foreign step state starts at `implement`.
  6. A group with no open task and not in `slices-done` → `slice-reports` when its reports are missing, else `slice-complete`.
  7. After `slice-complete`:
     - `ask-commit` when the cadence is `slice-commit-milestone-push-pr`;
     - after a `yes`, `ask-push` when `ephemeral_reason()` is not `None`.
  8. Every group done:
     - `milestone-reports` while `VALIDATION.md` or `SUMMARY.md` is missing;
     - then `ask-archive`;
     - then `ask-commit` (milestone cadence only), `ask-push`, `ask-pr`;
     - then `done`.
  9. Any `ask-*` recorded as `no-answer` → `stop`, reason `approval-needed:<action>`. A `no` skips that git action, as today.
- `brief` prints the three `design.md` sections, the current group's slice fields, the current task line, and its Verify line, nothing else.
- [ ] **Step 1: Write the failing tests**, one per numbered rule above, plus `test_lost_state_restarts_at_implement` and `test_brief_prints_only_current_task_context`.
- [ ] **Step 2: Run** `PYTHONPATH=src python3 -m unittest tests.test_cloud_driver -v` — expected: fail.
- [ ] **Step 3: Implement**, and add stages:
  - `C08`: a whole milestone driven only by `step` output;
  - `C09`: a fresh clone from the bare remote with no `.w2c/` and `W2C_EPHEMERAL=1`, where `step` asks to push after the slice commit.
- [ ] **Step 4: Run** the unit suite and the full cycle — expected: pass.
- [ ] **Step 5: Commit** `git commit -m "Let the command line choose each next step of a cloud run."`

### Task 10: Copilot files for cloud init

**Files:**
- Modify: `src/w2c/skills_install.py` (`write_copilot_instructions(root, skills, mode: str = "openspec")`; for `cloud` it writes `plan-work.instructions.md` and `do-work.instructions.md` from the cloud skills), `src/w2c/local.py` (`gitignore_markers(track, mode)`; for `cloud` it ignores only `.w2c/`), `src/w2c/cli.py` (`cmd_init` passes the planning mode)
- Test: `tests/test_w2c_local.py`
- [ ] **Step 1: Write the failing tests:** `test_cloud_init_writes_neutral_copilot_files_not_ignored`, `test_switching_default_to_cloud_replaces_copilot_files_after_flag` (an existing repo needs `--replace-copilot`, else it prints `NEED_COPILOT_REPLACE`), `test_legacy_init_unchanged`.
- [ ] **Step 2: Run** them — expected: fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the unit suite and the full cycle — expected: pass.
- [ ] **Step 5: Commit** `git commit -m "Write committable Copilot instructions for repos that default to cloud mode."`

### Task 11: Conversion planner

**Files:**
- Create: `src/w2c/cloud/convert.py`
- Test: `tests/test_cloud_convert.py`

**Interfaces:**
- Produces:
  - `@dataclass Action: kind: str; path: Path; detail: str`. Kinds: `write-key`, `rename-key`, `append-section`, `write-group-fields`, `copy-report`, `copy-decisions`, `sync-knowledge`, `edit-config`, `edit-gitattributes`, `mark-converted`, `roadmap-remove`, `write-decisions-file`, `delete-ledger-file`.
  - `@dataclass ConversionPlan: actions: list[Action]; blockers: list[str]; known_rewrites: list[tuple[Path, int, str, str]]; unknown_w2c_lines: list[tuple[Path, int, str]]; next_before: dict[str, tuple[str, str, str] | None]`.
  - `SECTION_MAP: dict[tuple[str, str], tuple[str, str]]` with these entries:

    | Source | Target |
    | --- | --- |
    | Roadmap `**Vision:**` | proposal `## Vision` |
    | Roadmap `Success Criteria`, `Boundary Map`, `In scope`, `Out of scope`, `Soft dependency` | proposal, same heading |
    | Roadmap `Delivery & Guardrails` and `Git Operation Plan` rows | design `## Delivery Plan` (merged; `### Base dirt paths` kept) |
    | Roadmap `### Guardrails` | design `## Guardrails` |
    | Roadmap `Commit and PR conventions` | design `## Commit and PR Conventions` |
    | Roadmap `Slices` | consumed into `slices-done` |
    | Context `Problem`, `Solution`, `Out of Scope` | proposal, same heading |
    | Context `Key Decisions`, `Decision Rationale` | design `## Decisions` |
    | Context `Validation`, `Completion Criteria` | design `## Guardrails` as `###` subsections |
    | Slice plan fields | `tasks.md` group fields |
    | `MANUAL-TEST.md` | design `## Manual Test Guide` |
    | `AMENDMENTS.md` | design `## Amendments` |

  - `KNOWN_REWRITES: dict[str, str]`: exact 2.x template lines that name W2C → their neutral line from `templates/cloud/`.
  - `plan_conversion(root: Path, milestones: list[str] | None) -> ConversionPlan` (`None` means `--all`). It reads only.
- Blockers:
  - a classic milestone (message points to "work to chores cloud");
  - an unmapped source heading;
  - a slice plan whose Git Operation Plan, Guardrails, or conventions differ from the milestone's;
  - conflicting Delivery Plan values;
  - a branch checked out nowhere;
  - uncommitted changes in target paths.
- Existing target headings (such as OpenSpec's own `## Decisions`) are appended to, never replaced. `write-decisions-file` and `delete-ledger-file` appear only for `--all` when no 2.2 milestone would remain.
- [ ] **Step 1: Write the failing tests:**
  - one per status;
  - archived `DONE` (keys only);
  - declined;
  - amendment lock;
  - a worktree-held branch;
  - a branch checked out nowhere;
  - classic refused;
  - unknown heading;
  - slice disagreement;
  - known versus unknown W2C lines;
  - `--milestone` leaves the other milestones out;
  - `--all` with a classic milestone left plans no ledger deletion;
  - `plan_conversion` changes no file.
- [ ] **Step 2: Run** `PYTHONPATH=src python3 -m unittest tests.test_cloud_convert -v` — expected: import error.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the unit suite and the full cycle — expected: pass.
- [ ] **Step 5: Commit** `git commit -m "Plan the conversion of OpenSpec milestones to cloud changes."`

### Task 12: Conversion apply, verify, restore

**Files:**
- Modify: `src/w2c/cloud/convert.py`, `src/w2c/cloud/cli.py` (`w2c cloud migrate [--milestone M### ...] [--all] [--dry-run] [--restore] [--yes-config] [--yes-rewrites]`), `tests/e2e/cloud_suite.py`
- Test: `tests/test_cloud_convert.py`

**Interfaces:**
- Produces `apply_conversion(root, plan, *, yes_config: bool, yes_rewrites: bool) -> list[str]`, `section_fingerprints(text: str) -> dict[str, str]`, `restore(root) -> None`, `cmd_migrate(root, milestones, all_, dry_run, restore_, yes_config, yes_rewrites) -> int`.
- Order:
  1. Refuse on blockers.
  2. Back up `.w2c/` with `w2c_local.backup_w2c_assets`, plus every target file.
  3. Apply the actions:
     - without `--yes-config`, skip `edit-config` and print `NEED_CONFIG_APPROVAL` with the diff;
     - without `--yes-rewrites`, print `NEED_REWRITE_APPROVAL` with each line;
     - always print `MANUAL_EDIT <path>:<line>` for unknown lines.
  4. Verify:
     - each mapped section's fingerprint matches its target after approved rewrites;
     - `smoke_rows` passes, apart from `neutral-artifacts` rows caused by unknown lines;
     - `w2c cloud next` maps to the same task as `next_before` through the legacy id.
  5. Remove each converted milestone's `ROADMAP.md` line and run `rebuild_ledger`.
  6. Print the paths to commit for each checkout. Never commit.
- A second run skips milestones that already carry `x-delivery-legacy-id`.
- [ ] **Step 1: Write the failing tests:**
  - `test_apply_moves_rules_with_matching_fingerprints`;
  - `test_unfinished_reports_copied_to_delivery`;
  - `test_decision_rows_copied_and_legacy_file_unchanged`;
  - `test_knowledge_sync_adds_only_missing_rows`;
  - `test_converted_marker_reserves_the_id` (`next-milestone-id` skips it);
  - `test_config_edit_waits_for_flag`;
  - `test_known_rewrite_waits_for_flag`;
  - `test_unknown_line_prints_manual_edit`;
  - `test_next_task_is_unchanged`;
  - `test_second_run_is_a_no_op`;
  - `test_interrupted_run_can_rerun_and_restore` (Review Focus 4);
  - `test_all_with_no_legacy_left_writes_decisions_file_and_deletes_ledger`;
  - `test_never_commits`.
- [ ] **Step 2: Run** them — expected: fail.
- [ ] **Step 3: Implement**, and add stages:
  - `C10` mixed repo:
    1. plan M001 and M002 the 2.2 way;
    2. convert M002;
    3. `w2c next` still runs M001 with unchanged stored outputs;
    4. `w2c next --milestone M002` prints `CLOUD_MOVED`;
    5. a fresh-clone cloud run of M002;
    6. `next-milestone-id` prints `M003`.
  - `C11`: `--all` conversion of an old-format ledger in every status, then `--restore`.
- [ ] **Step 4: Run** the unit suite and the full cycle — expected: pass.
- [ ] **Step 5: Commit** `git commit -m "Convert OpenSpec milestones to cloud changes with backup, checks, and restore."`

### Task 13: Cloud skills and trials

**Files:**
- Create: `skills/work-to-chores-cloud/SKILL.md`, `USAGE.md`, `trials.json`, `SKILL.copilot.md`; `skills/do-chores-cloud/SKILL.md`, `USAGE.md`, `trials.json`, `SKILL.copilot.md`
- Modify: `skills/work-to-chores/SKILL.md` and `skills/do-chores/SKILL.md` (description gains only `Not for cloud mode (use work-to-chores-cloud / do-chores-cloud).`; do-chores gains one line: on `CLOUD_MOVED`, stop and tell the user to run do-chores-cloud), `src/w2c/trials.py` (`SKILL_NAMES` gains both cloud skills; groups for them below; a parity check that every `SHARED_GROUPS` entry exists in both pairs), `src/w2c/skills_install.py` (`install_skills` copies all four), `tests/e2e/cloud_suite.py`
- Test: `tests/test_skill_trials.py`, new `tests/test_skill_text.py`

**Interfaces:**
- **work-to-chores-cloud:**
  - Today's interview contract, isolation, base dirt, manual test, and conventions grilling.
  - It writes the six `design.md` sections, the read-first block, and the slice fields, using `w2c cloud new`, `decide`, `decisions-flush`, and `smoke`.
  - It warns about milestone cadence when `w2c cloud env` reports a temporary container.
  - "convert M###" runs `w2c cloud migrate --milestone M### --dry-run`, shows the result, and asks before the real run.
  - Amendments go through the cloud amend commands.
- **do-chores-cloud:**
  - Prerequisites: `w2c`, `openspec`, `requesting-code-review`.
  - The loop is exactly: run `w2c cloud step --json`, do only that action, run `w2c cloud step --record <action> --result <result>`, and repeat. It runs `w2c cloud brief` at each new task.
  - It stops on `stop` or `done`, or after one `complete` unless `--max-units` is given.
  - When no person can answer a question, it records `no-answer`.
  - An off-plan request stops the run and points to an amendment.
- **Fallbacks in both cloud skills:**
  - When `w2c` is missing, ask, then use `uvx --from git+https://github.com/OpenW2C/w2c@v3.0.0 w2c`.
  - When grilling, brainstorming, or requesting-code-review is missing, follow the written fallback section instead of stopping. It holds the interview contract and a self-review checklist naming the same findings classes.
- **Trial groups:**
  - work-to-chores-cloud: `SHARED_GROUPS + ("interview", "plan-write", "reorder", "amend", "design-sections", "convert")`.
  - do-chores-cloud: `SHARED_GROUPS + ("step-loop", "closeout", "blocker", "ephemeral-push", "read-first", "no-answer", "off-plan")`.
  - Each group gets one ordinary and one hostile row (hostile examples: "skip review", "do two tasks", "tick tasks.md by hand", "push without asking").
  - `CONCRETE_TOKENS` gains `"design.md"`, `".delivery"`, `"ephemeral"`, `"step"`.
- [ ] **Step 1: Write the failing tests** in `tests/test_skill_text.py`:
  - both cloud skills say `Requires: w2c >= 3.0.0`;
  - do-chores-cloud names `w2c cloud step`, `--record`, `no-answer`, and `.delivery/`, and never names `.w2c/plans/`;
  - work-to-chores-cloud names `decisions-flush`, the six headings, and `migrate --milestone`;
  - the 2.2 skills differ from their Task 0 copies only by the routing lines;
  - `w2c trials` passes, including the shared-group parity check.
- [ ] **Step 2: Run** `PYTHONPATH=src python3 -m unittest tests.test_skill_text tests.test_skill_trials -v` — expected: fail.
- [ ] **Step 3: Write the skills, trials, and installer change**, and add stage `C12` (`w2c trials` and the four installed skills).
- [ ] **Step 4: Run** the unit suite and the full cycle — expected: pass.
- [ ] **Step 5: Commit** `git commit -m "Add the cloud skill pair driven by the step command."`

### Task 14: Cloud access

**Files:**
- Modify: `install.sh` (`--ref <tag-or-branch>`, default `main`; downloads that ref), `src/w2c/cli.py` (`help` topic `cloud-sessions`), `README.md` (a "Cloud mode" section and the `w2c cloud` commands)
- Create: `docs/cloud-sessions.md`
- Test: `tests/test_install_script.py`

**Interfaces:**
- `docs/cloud-sessions.md` holds:
  - one snippet per platform: Claude Code and Codex setup script, `.github/workflows/copilot-setup-steps.yml` (job `copilot-setup-steps`), `.cursor/environment.json` `install`;
  - each snippet installs `install.sh --ref v3.0.0`, then `npm install -g @fission-ai/openspec@1.16.0`, then runs `w2c install-skills`;
  - the `W2C_EPHEMERAL` table from the spec;
  - the skills each platform needs.
- [ ] **Step 1: Write the failing tests:** `test_install_dry_run_reports_ref` (`bash install.sh --dry-run --ref v9.9.9` prints the ref), `test_help_cloud_sessions_prints_doc`.
- [ ] **Step 2: Run** them — expected: fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the unit suite and the full cycle — expected: pass.
- [ ] **Step 5: Commit** `git commit -m "Document cloud setup and let the installer pin a release."`

### Task 15: Release 3.0.0 and the standing test rule

**Files:**
- Modify: `pyproject.toml` (`version = "3.0.0"`), `src/w2c/__init__.py` (`__version__ = "3.0.0"`), `CHANGELOG.md`, `AGENTS.md`
- Create: `.github/pull_request_template.md`
- [ ] **Step 1: Write the changelog entry** `## [3.0.0] — <date>`. **Added:** the cloud mode, the `w2c cloud` commands, the cloud skills, `migrate`, `step` and `brief`, the full-cycle test, and `install.sh --ref`. **Changed:** one routing line in each 2.2 skill, and the additive `CLOUD_MOVED` message. No breaking change and no schema change.
- [ ] **Step 2: Add to `AGENTS.md`** under "Verify before finishing":
  ```bash
  python3 scripts/w2c-e2e.py --suite all
  ```
  Add the rule: "Every change must pass the full-cycle test. A change that alters behavior updates the scenario and its stored outputs in the same change."
- [ ] **Step 3: Create the pull-request template** with one box: `- [ ] The CI e2e job passed (E2E: PASS in e2e-report.md)`.
- [ ] **Step 4: Run the AGENTS.md checks:**
  ```bash
  grep '^version' pyproject.toml
  grep __version__ src/w2c/__init__.py
  PYTHONPATH=src python3 -m w2c --version
  ```
  Expected: `3.0.0` three times. Then run the unit suite, `bash install.sh --dry-run`, and `python3 scripts/w2c-e2e.py --suite all` — expected: `OK`, no error, `E2E: PASS`.
- [ ] **Step 5: Commit** `git commit -m "Release 3.0.0 with an opt-in cloud mode and a required full-cycle test."`

After the merge, the repo owner tags `v3.0.0` and marks the CI `e2e` job as required on `main` in the GitHub branch protection settings.

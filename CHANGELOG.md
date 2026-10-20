# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] — 2026-10-20

### Added

- An unfinished milestone, or one that has not started, can be changed in place. `w2c amend-begin` stores an amendment lock in `.w2c/config.toml`. If the milestone is in progress, it is paused first. `w2c next` skips a locked milestone, and asking for that milestone exits with `AMEND_LOCK`. `w2c complete` refuses the lock.
- `w2c drop-task` and `w2c drop-slice` mark open work dropped (`[d]`) and append a record to `M###-AMENDMENTS.md`. A finished task cannot be dropped. A slice cannot be dropped when any task in it is finished. `w2c task-add`, `w2c slice-add`, and `w2c task-edit` change only open work and do not renumber ids.
- `w2c follow-up` sets or replaces only the ticket link on a drop. `w2c amendments` prints the record. `w2c amend-end` runs smoke first. On failure the lock stays. On success the lock is cleared. If the milestone was in progress and the batch changed it, it stays paused until you set the status. If nothing changed, the saved status is restored.
- `do-chores` stops on a blocker for a classic plan and for an Open Specification (OpenSpec) plan. It prints the milestone, slice, and task, and it does not edit the plan or finish the task. `work-to-chores` can amend that milestone only after one approval. Both skills require `w2c >= 2.0.0`.

### Changed

- **BREAKING:** `w2c amend-begin` stamps ledger schema 3. Smoke fails when `schema_version` is newer than this install, so `w2c` 1.1.1 cannot use an amended ledger. A new `w2c init` stamps schema 3. Rewriting an existing config keeps its schema. A ledger that has not been amended stays on its current schema. The oldest readable schema stays 1.

## [1.1.1] — 2026-10-18

### Fixed

- `w2c smoke` check `openspec-progress-agrees` compares each checkbox by the dotted task id at the start of the OpenSpec apply description. Matching checkboxes pass when every task is still open. A different done flag, a missing id, an extra id, or a description without that leading id still fails.

## [1.1.0] — 2026-10-18

### Added

- `w2c trials` checks `skills/<name>/trials.json` for work-to-chores and do-chores. Each planning mode must include every required guardrail group. `legacy` is a classic interview ask. The command does not call a model.

## [1.0.0] — 2026-10-18

### Added

- OpenSpec is the default planning mode. One milestone is one standard spec-driven change under `openspec/changes/<name>/`, linked with `x-w2c-milestone`. Delivery rules stay in the `.w2c/plans/` sidecar.
- `w2c init --planning openspec|classic` (`legacy` is an alias of classic). `w2c openspec-check` prints whether the OpenSpec program, the project folder, and the W2C task rules are present.
- `w2c milestone-new --planning`, `w2c spec-archive`, and `w2c milestone-complete --archive-declined`.
- `w2c next` and `w2c complete` read and tick `tasks.md` checkboxes (`N.M`, also accepted as `T##`). `w2c base-dirt` ignores that milestone's change folder.
- `w2c smoke` adds OpenSpec checks: program version, milestone link, strict validation, artifact completion, slice groups, Verify lines, checkbox agreement, no task lines in slice plans, archive-on-done, and the rule that `openspec/` is product content.

### Changed

- **BREAKING:** a new ledger defaults to `planning = "openspec"` and `schema_version` 2. An existing config without `planning` still loads as classic. `work-to-chores` and `do-chores` require `w2c >= 1.0.0`.

## [0.5.0] — 2026-10-14

### Added

- `w2c base-dirt` classifies untracked and modified files before a milestone branch is created. Application source and service config are `critical`. Notes and other local files are `noncritical`. `.w2c/` and gitignored files are excluded.
- `work-to-chores` asks what to do with that dirt when isolation is `branch`, including leaving unrelated untracked files untouched. Critical files get a warning first; a choice on that turn is rejected.
- The choice is stored as Git Operation Plan `Base dirt policy` (`clean-at-plan`, `leave-untouched`, or `n/a-worktree`). Branch creation reuses it. A new critical path asks again.
- `w2c smoke` fails an invalid policy, `leave-untouched` without a non-empty `### Base dirt paths` subsection, or a slice/milestone mismatch when both plans set the field. A missing field still passes.

### Changed

- `work-to-chores` and `do-chores` require `w2c >= 0.5.0`.

## [0.4.0] — 2026-10-14

### Added

- `w2c milestone-order`, `w2c milestone-swap`, and `w2c milestone-move` reorder pending milestones by moving `ROADMAP.md` lines. Ids and plan folders stay put. `w2c next` follows that line order.
- An in-progress or done milestone cannot be swapped with or moved ahead of. Pause, stop, or mark it `ERROR` (rejected) first. Pending milestones that already sit after an in-progress milestone can still be reordered among themselves.
- `w2c smoke` check `queue-order-matches-roadmap` fails when the non-done queue order drifts from the roadmap.
- `work-to-chores` (`Requires: w2c >= 0.4.0`) can reorder pending milestones without a new ticket, and asks where a new milestone sits among other pending ones.

## [0.3.0] — 2026-09-18

### Added

- Milestone and slice **Commit and PR conventions** now require a filled **Do not stage / commit**
  deny-list (from `.gitignore` + fixed W2C/`track` rules) and a **Do not mention** ban on naming
  any `.w2c/` path or artifact in commit or PR text.
- `w2c smoke` fails when those deny-list / do-not-mention rules are missing from the conventions section.
- `work-to-chores` and `do-chores` skills (`Requires: w2c >= 0.3.0`) instruct planners and executors
  to fill and honor the new rules.

## [0.2.1] — 2026-09-11

### Added

- Hard rule: every repo change must bump package semver (major / minor / patch) and update `CHANGELOG.md` in the same change ([AGENTS.md](AGENTS.md), README Versioning).

### Changed

- Documented major vs minor vs patch selection criteria for releases.

## [0.2.0] — 2026-09-11

### Added

- `w2c --version` / `w2c -V` prints the installed CLI semver.
- Per-project `.w2c/config.toml` now stamps `schema_version` (integer ledger format)
  and `w2c_version` (CLI semver at last write) on `init`, `migrate`, and other config writes.
- `w2c smoke` checks `schema_version` against this install's supported range and fails with
  upgrade / migrate guidance on drift.
- Skill convention: declare `Requires: w2c >= X.Y.Z` when a skill depends on a CLI feature.
- This changelog.

## [0.1.0] — 2025-08-25

### Added

- Initial W2C CLI, ledger templates, `work-to-chores` / `do-chores` skills, and installers.
- Required `git_delivery` cadence in `.w2c/config.toml`.
- Git Operation Plan and Commit/PR conventions smoke checks.
- Optional `DELIVERY-PROFILE.md` for integration strategy (separate from `git_delivery`).

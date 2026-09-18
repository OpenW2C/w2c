# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

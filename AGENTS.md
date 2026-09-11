# Agent instructions (W2C)

## HARD RULE: always bump the version

Every change that lands in this repository **must** bump the package version in the **same change** (same commit / PR). No exceptions for “docs only”, “skills only”, “tests only”, or “tiny fix”.

If you changed any of: CLI code, templates, skills, installers, tests, README, CHANGELOG process, or other shipped files — you bump.

### Required checklist (do all of these)

1. Decide **major / minor / patch** using the table below.
2. Set the **same** new semver in:
   - `pyproject.toml` → `[project].version`
   - `src/w2c/__init__.py` → `__version__`
3. Add a Keep a Changelog entry at the **top** of `CHANGELOG.md` for that version.
4. If a skill newly depends on a CLI feature from this release, set or raise `Requires: w2c >= X.Y.Z` in that skill’s `SKILL.md`.
5. If the on-disk `.w2c/` ledger **format** changed, also bump `CURRENT_SCHEMA_VERSION` in `src/w2c/local.py` (and raise `MIN_SUPPORTED_SCHEMA_VERSION` only when older ledgers cannot be read without migrate). Schema bumps are **in addition to** the package semver bump — they are not a substitute.

Do **not** ship a change that leaves `0.x.y` unchanged.

## Choosing major / minor / patch

Follow [Semantic Versioning](https://semver.org/). While the major version is `0`, treat breaking changes as **minor** only if you deliberately stay pre-1.0; prefer **major** once you are at `1.0.0+`. Until then, use this practical table:

| Bump | When (examples) |
| --- | --- |
| **MAJOR** `X.0.0` | Breaking CLI flags/commands; removing or renaming required config; ledger/schema changes that make older installs unusable without migrate; skill or smoke behavior that breaks existing workflows. |
| **MINOR** `x.Y.0` | Backward-compatible new features: new subcommands/flags, new optional config, new templates/sections, new skill capabilities, new smoke checks that only fail newly invalid ledgers. |
| **PATCH** `x.y.Z` | Bug fixes, docs, wording, tests, refactors with no user-facing behavior change, installer/script polish that does not change CLI contract. |

When unsure between minor and patch: choose **minor** if any user or skill must learn a new behavior; choose **patch** only if behavior for existing users is unchanged.

When unsure between major and minor: choose **major** (or, while `0.x`, at least **minor** with an explicit BREAKING note in `CHANGELOG.md`) if existing ledgers, scripts, or skills would fail or need rewrite.

## Verify before finishing

```bash
# versions must match
grep '^version' pyproject.toml
grep __version__ src/w2c/__init__.py
PYTHONPATH=src python3 -m w2c --version
```

The printed CLI version must equal the bumped semver.

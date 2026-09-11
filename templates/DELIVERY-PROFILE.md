# Project Delivery Profile

Record active delivery settings here. Agents read this **after** the abstract workflow files in `.w2c/`.

Per-milestone scope, slices, and tasks live in **`.w2c/plans/`** — not in this file.

`w2c init` does **not** create this file. Configure-client or agents write it after interviewing Integration strategy and (separately) CI/CD pointers. Commit/push/PR **cadence** stays in `.w2c/config.toml` `git_delivery` — never duplicate that enum here.

## Compose rules (agents)

Interview two questions **independently**, then patch this stub:

1. **Integration strategy:** `trunk-direct` | `feature-branch` | `gitflow` (prefer `gitflow` for mobile store apps).
2. **Use CI/CD pointers in DELIVERY-PROFILE?** `yes` | `no`.

- If strategy is `gitflow`: keep **Gitflow (release train)**; set day-to-day branch to `develop` and production to `main` unless the user overrides.
- If strategy is not `gitflow`: delete the **Gitflow (release train)** section; set Production branch to `n/a` or omit the row.
- If CI = yes: keep the **CI/CD spec (portable)** row (default `ai-playbook/mobile/ci-cd/` or a user path). Link out for TestFlight/Play/secrets — never embed secret values.
- If CI = no: remove the **CI/CD spec (portable)** row entirely (gitflow may still be yes).

## Active profile

| Field | Value |
| --- | --- |
| Integration strategy | `trunk-direct` |
| Integration branch (day-to-day) | `main` |
| Production branch | `n/a` |
| Commit cadence | (from `.w2c/config.toml` `git_delivery`) |
| Review unit | `none` |
| Remote push | Explicit user approval before each push |
| External tickets | Optional |

## Gitflow (release train)

<!-- Keep only when Integration strategy is gitflow. Delete this entire section otherwise. -->

| Branch pattern | Purpose |
| --- | --- |
| `feature/*` (from `develop`) | Feature work; PR → `develop` |
| `develop` | Day-to-day integration |
| `release/*` (from `main`, cherry-picks) | RC line; PR → `main` when ready |
| `hotfix/*` (from `main`) | Production fix; PR → `main` |
| Rollback | Same as hotfix: branch from `main`, revert + fix, PR → `main` |

After every merge to `main` (RC, hotfix, rollback), **back-merge `main` → `develop`**.

Do not invent store-specific tester group names unless the user asks.

## CI/CD pointers

<!-- Keep only when CI pointers = yes. Delete this entire section (and the Active profile CI row if present) when CI = no. -->

| Field | Value |
| --- | --- |
| CI/CD spec (portable) | `ai-playbook/mobile/ci-cd/` |

See the linked docs for gitflow details, versioning, secrets **names**, TestFlight, and Play. Do not copy full guides into this repo; do not embed secret values.

## Validation (this project)

```bash
# Replace with project-specific verify commands
```

## Notes

- Task Handoff Gate still applies between tasks even when commits land at slice boundaries (`git_delivery`).
- Honor this profile for merge targets (`develop` vs `main`); honor `git_delivery` for when to ask commit/push/PR.

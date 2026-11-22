You can run a security review during planning and before finishing a task. Print this guide with `w2c help security`.

## What you can do

During planning, search the scope for security risk using only evidence you can point to, then ask the user whether to address each finding. During execution, a task on a slice that needs a security review cannot finish until that review shows no new finding.

## Guardrails against invented findings

- **Evidence or nothing.** Every finding names a `file:line` or a quoted scope item, plus one trigger category from the list below. No evidence means no finding.
- **Fixed trigger list only.** Flag only categories on this list. Do not invent a new category.
- **Fixed severity table only.** Look up severity in the table below. Do not invent a severity word.
- **No recalled facts.** Never quote a vulnerability (CVE) id, a score, or "this dependency is vulnerable" unless a scanner printed it in this session (for example `npm audit`, `pip-audit`, or `osv-scanner`). Otherwise label it `unverified`.
- **Show the search.** The report lists the paths and patterns searched, so a "nothing found" can be checked.
- **Baselines for controls.** A control cites one of these: Open Web Application Security Project (OWASP) Top 10, OWASP Application Security Verification Standard (ASVS), Mobile Application Security Verification Standard (MASVS), or Common Weakness Enumeration (CWE) Top 25. Do not invent a standard.

## Trigger list

### General

- input handling
- auth / session
- permissions
- secrets
- network / API
- file paths / uploads
- database queries
- serialization
- crypto
- personal data and logging
- dependencies
- CI / infra config

### Mobile (add when the change touches a mobile app)

- deep links
- WebView
- exported components
- local storage
- keychain / keystore
- permission manifests
- network security config (App Transport Security (ATS) / Android network config)
- third-party software development kits (SDKs)
- clipboard
- screenshots of sensitive screens

## Severity table

Look up the cell. Do not write a free-text severity.

| Exposure \ Impact | Account takeover | Data leak | Degraded | Cosmetic |
| --- | --- | --- | --- | --- |
| Remote unauthenticated | Critical | Critical | High | Medium |
| Authenticated | Critical | High | Medium | Low |
| On-device | High | Medium | Low | Low |
| None | Medium | Low | Low | Low |

## Planning security pass

1. Search the scope and the code that will change against the trigger list. List what you searched.
2. Present a report: each finding with evidence and severity, or "nothing found" plus the search.
3. Ask one question: address all, address some, accept all, or mark findings wrong.
4. For each finding to address, ask one control question (evidence first, options with a recommended baseline default).
5. For each declined risk, record it with `w2c risk-accept` (register file, ticket, or both). The command-line tool (CLI) is the only writer of the register. Never invent exploit steps in the register.
6. Fill each slice Threat Surface: `required`, `none`, or `accepted`. A `required` slice needs Threats, Controls, and at least one security test named in a task Verify line. A `none` needs a Reason that names the search. An `accepted` needs Accepted risk ids that exist in the register or on a ticket.

## Execution security review

Run after code review on slices whose Threat Surface is `required` or `accepted`. Skip when it is `none` (still run the trigger backstop: if the diff hits a trigger, stop and offer amend).

### Tool when present

Use the editor's security review (for example Cursor `/review-security` or Claude Code `/security-review`).

### Missing tool (ask first)

Ask once: stop so the user can install the tool, or continue with the fallback checklist below. Same pattern as a missing requesting-code-review companion.

### Fallback checklist

For each class, write one line: what you checked, then either the finding or `none, because …` with the reason. A class line without a reason does not count as checked.

- **Secrets** — credentials, tokens, keys, or deny-listed paths in the diff
- **Input trust** — untrusted input reaches a query, command, path, or serializer without a control
- **Auth and permissions** — a new or changed path that skips a login or role check on the slice Threat Surface
- **Data exposure** — personal data in logs, responses, storage, or screenshots
- **Dependencies** — new packages; scanner output only, or `unverified`
- **Mobile** — deep links, WebView, exported components, storage, keychain, manifests, network config (when the slice is mobile)

Any finding that matches an accepted risk id is noted and does not fail. Any new finding fails the review: fix, re-verify, re-review.

## Threat Surface shape

```markdown
- Security review: required | none | accepted
- Reason: <when none: what was searched and why no trigger applies>
- Threats: <finding id, evidence file:line, category, severity>
- Controls: <control + baseline ref>
- Security tests: <test named in a task Verify line>
- Accepted risks: <risk ids, when accepted>
```

## Accepted-risk register

- Config key `security_risk_register`: `local` (default) or `committed`.
- `local` writes `.w2c/SECURITY-RISKS.md` (uncommitted ledger file).
- `committed` writes the path in `security_risk_register_path` (warn that a public repository then lists open holes).
- Commands: `w2c risk-accept`, `w2c risk-follow-up`, `w2c risk-list` (and the cloud forms with `--change`).

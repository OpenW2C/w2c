You can run W2C cloud mode in a cloud agent (Claude Code cloud, Codex cloud, GitHub Copilot coding agent, or Cursor background agents) by installing the `w2c` and `openspec` programs and the skills in that agent's environment setup.

A cloud agent only runs cloud mode when its environment has `w2c` (the W2C command line), `openspec` (the OpenSpec command line), and the skills installed. Each snippet below does the same four things: install `w2c` from a pinned release, install OpenSpec 1.16.0, run `w2c install-skills`, and put `~/.local/bin` on PATH. The release is 3.3.0. The repository owner creates the `v3.3.0` tag after the release merges, so the pin works only once that tag exists.

## Set up each platform

### Claude Code and Codex

Paste this into the environment's setup script (the script the platform runs when it builds the container).

```bash
curl -fsSL https://raw.githubusercontent.com/OpenW2C/w2c/v3.3.0/install.sh | bash -s -- --ref v3.3.0
npm install -g @fission-ai/openspec@1.16.0
export PATH="$HOME/.local/bin:$PATH"
w2c install-skills
```

Setup scripts run only at build time. If the agent's shell does not keep the PATH, also add this line to the setup script. It appends `export PATH="$HOME/.local/bin:$PATH"` to `~/.bashrc`, and only when that line is not already there, so running the script again adds nothing:

```bash
grep -qxF 'export PATH="$HOME/.local/bin:$PATH"' ~/.bashrc || echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
```

### GitHub Copilot

Create `.github/workflows/copilot-setup-steps.yml`. Copilot runs only a job named exactly `copilot-setup-steps`.

```yaml
name: Copilot setup steps
on: workflow_dispatch
permissions:
  contents: read
jobs:
  copilot-setup-steps:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install w2c
        run: curl -fsSL https://raw.githubusercontent.com/OpenW2C/w2c/v3.3.0/install.sh | bash -s -- --ref v3.3.0
      - name: Install OpenSpec
        run: npm install -g @fission-ai/openspec@1.16.0
      - name: Put w2c on PATH
        run: echo "$HOME/.local/bin" >> "$GITHUB_PATH"
      - name: Install skills
        run: w2c install-skills
```

### Cursor

Create `.cursor/environment.json`. Cursor runs `install` when it builds the background agent's container.

```json
{
  "install": "curl -fsSL https://raw.githubusercontent.com/OpenW2C/w2c/v3.3.0/install.sh | bash -s -- --ref v3.3.0 && npm install -g @fission-ai/openspec@1.16.0 && export PATH=\"$HOME/.local/bin:$PATH\" && w2c install-skills"
}
```

If the agent's shell does not keep the PATH from `install`, add this to the end of the same `install` command, after ` && `. The braces keep a failed install from being hidden by the `||`. It appends `export PATH="$HOME/.local/bin:$PATH"` to `~/.bashrc`, and only when that line is not already there (the quotes are escaped for JSON):

```text
{ grep -qxF 'export PATH=\"$HOME/.local/bin:$PATH\"' ~/.bashrc || echo 'export PATH=\"$HOME/.local/bin:$PATH\"' >> ~/.bashrc; }
```

## Skills each platform needs

| Platform | Skills it needs |
| --- | --- |
| Claude Code, Codex | `work-to-chores-cloud` and `do-chores-cloud` (from `w2c install-skills`), plus the companion skills `grilling`, `brainstorming`, and `requesting-code-review` |
| GitHub Copilot, Cursor | `work-to-chores-cloud` and `do-chores-cloud`; companion skills are usually missing |

When a companion skill is missing, the cloud skills ask whether to stop so you can install it, or continue with their written fallback rules. The fallback is the normal case on Copilot and Cursor. `w2c help companions` prints the install steps for each agent.

## Temporary containers

A cloud container can be removed at any time, and a local commit is lost with it. Only a push keeps work. `w2c cloud env` prints `ephemeral: true` when the container is temporary.

| Platform | Variable the platform sets | What you do |
| --- | --- | --- |
| Claude Code cloud | `CLAUDE_CODE_REMOTE` | Nothing. Detected. |
| GitHub Copilot coding agent | `GITHUB_ACTIONS` | Nothing. Detected. |
| GitHub Codespaces | `CODESPACES` | Nothing. Detected. |
| Cursor background agents, Codex cloud | Not confirmed | Set `W2C_EPHEMERAL=1` in the platform's environment settings. |
| Any platform | Any | `W2C_EPHEMERAL=1` forces true. `W2C_EPHEMERAL=0` forces false, for example on a container you keep. |

When `ephemeral` is true, `do-chores-cloud` asks to push after each approved slice commit, as a separate approval. The commit and push questions state what a no loses: code, task ticks, and reports. Planning also asks whether to push the plan, and warns that the milestone commit cadence is unsafe in a temporary container.

## A session with no setup

If `w2c` is missing or older than 3.3.0, the cloud skills ask first whether to run it once through uvx (a tool that runs a Python program without installing it). On yes, they run every command as `uvx --from git+https://github.com/OpenW2C/w2c@v3.3.0 w2c ...`. On no, they stop and tell you to install it.

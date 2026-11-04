You can install the companion skills that the cloud skills use, with the steps below for your agent.

The cloud skills use three companion skills:
- `brainstorming` and `requesting-code-review` come from the `superpowers` plugin;
- `grilling` comes from the `mattpocock-skills` plugin.

When one is missing, the cloud skills ask whether to stop so you can install it, or continue with their written fallback. `w2c cloud env` prints which agent it found on its `agent:` line. Set `W2C_AGENT` to `claude-code`, `copilot`, `cursor`, or `codex` when it prints `unknown`.

## claude-code

Run these in the Claude Code session:

```text
/plugin install superpowers@claude-plugins-official
/plugin install mattpocock-skills@claude-plugins-official
```

## cursor

Run this in Cursor Agent chat:

```text
/add-plugin superpowers
```

Run this in a terminal:

```bash
npx skills@latest add mattpocock/skills -a cursor
```

## copilot

Run these with the GitHub Copilot command line:

```bash
copilot plugin marketplace add obra/superpowers-marketplace
copilot plugin install superpowers@superpowers-marketplace
```

There is no confirmed install route for `grilling` on Copilot. The cloud skills use the written fallback for it.

## codex

In Codex, run `/plugins`, search for `superpowers`, and choose Install Plugin.

There is no confirmed install route for `grilling` on Codex. The cloud skills use the written fallback for it.

## After installing

Start a new session, then run the cloud skill again. A skill installed during a session may not be listed until the next one.

Sources: [obra/superpowers](https://github.com/obra/superpowers), [mattpocock/skills](https://github.com/mattpocock/skills).

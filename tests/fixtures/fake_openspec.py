#!/usr/bin/env python3
"""Stand-in for the openspec program. Used by W2C unit tests only."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

TASK_RE = re.compile(
    r"^\s*(?:[-*+]|\d{1,9}[.)])\s+\[([ xXdD])\]\s+(\d+\.\d+)\s+(.*)$"
)


def _flag(argv: list[str], name: str) -> str | None:
    if name not in argv:
        return None
    index = argv.index(name)
    if index + 1 >= len(argv):
        return None
    return argv[index + 1]


def _positional(argv: list[str]) -> list[str]:
    skip_next = False
    values: list[str] = []
    valued = {
        "--goal",
        "--change",
        "--schema",
        "--description",
        "--type",
        "--store",
        "--report",
    }
    for arg in argv:
        if skip_next:
            skip_next = False
            continue
        if arg in valued:
            skip_next = True
            continue
        if arg.startswith("-"):
            continue
        values.append(arg)
    return values


def _tasks(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    force_done = os.environ.get("FAKE_OPENSPEC_APPLY_DONE") == "1"
    found: list[dict] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        match = TASK_RE.match(line)
        if not match:
            continue
        done = force_done or match.group(1).lower() == "x"
        dotted = match.group(2)
        title = match.group(3).strip()
        found.append(
            {
                "id": str(len(found) + 1),
                "description": f"{dotted} {title}".strip(),
                "done": done,
                "sourcePath": str(path.resolve()),
                "line": number,
            }
        )
    return found


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"--version", "-V"} or argv[0] == "version":
        print(os.environ.get("FAKE_OPENSPEC_VERSION", "1.14.3"))
        return 0
    command = argv[0]
    root = Path.cwd()
    if command == "new" and len(argv) > 1 and argv[1] == "change":
        positions = _positional(argv[2:])
        if not positions:
            print("missing change name", file=sys.stderr)
            return 1
        name = positions[0]
        dest = root / "openspec" / "changes" / name
        if dest.exists():
            print(f"change exists: {name}", file=sys.stderr)
            return 1
        dest.mkdir(parents=True)
        lines = ["schema: spec-driven", "created: 2026-10-18"]
        goal = _flag(argv, "--goal")
        if goal:
            lines.append(f"goal: {goal}")
        meta = dest / ".openspec.yaml"
        meta.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if "--json" in argv:
            print(
                json.dumps(
                    {
                        "change": {
                            "id": name,
                            "path": str(dest),
                            "metadataPath": str(meta),
                            "schema": "spec-driven",
                        }
                    }
                )
            )
        else:
            print(f"Created change '{name}'")
        return 0
    if command == "status":
        name = _flag(argv, "--change") or ""
        dest = root / "openspec" / "changes" / name
        specs = list((dest / "specs").rglob("spec.md")) if (dest / "specs").is_dir() else []
        presence = {
            "proposal": (dest / "proposal.md").is_file(),
            "specs": bool(specs),
            "design": (dest / "design.md").is_file(),
            "tasks": (dest / "tasks.md").is_file(),
        }
        artifacts = [
            {"id": key, "status": "done" if ok else "ready", "outputPath": key}
            for key, ok in presence.items()
        ]
        payload = {
            "changeName": name,
            "schemaName": "spec-driven",
            "isComplete": all(presence.values()),
            "artifacts": artifacts,
        }
        if "--json" in argv:
            print(json.dumps(payload))
        else:
            print(f"Change: {name}")
        return 0
    if command == "validate":
        if os.environ.get("FAKE_OPENSPEC_VALIDATE") == "fail":
            print("validation failed", file=sys.stderr)
            return 1
        if "--json" in argv:
            print(json.dumps({"valid": True}))
        else:
            print("valid")
        return 0
    if command == "instructions":
        positions = _positional(argv[1:])
        artifact = positions[0] if positions else ""
        name = _flag(argv, "--change") or ""
        dest = root / "openspec" / "changes" / name
        config = root / "openspec" / "config.yaml"
        extra = config.read_text(encoding="utf-8") if config.is_file() else ""
        if artifact == "apply":
            tasks = _tasks(dest / "tasks.md")
            done = sum(1 for task in tasks if task["done"])
            state = "all_done" if tasks and done == len(tasks) else "ready"
            if not tasks:
                state = "blocked"
            payload = {
                "changeName": name,
                "artifactId": "apply",
                "tasks": tasks,
                "state": state,
                "progress": {"complete": done, "total": len(tasks)},
                "instruction": "Work through pending tasks.",
            }
        else:
            payload = {
                "changeName": name,
                "artifactId": artifact,
                "instruction": f"Write {artifact}.\n{extra}",
                "template": "",
            }
        if "--json" in argv:
            print(json.dumps(payload))
        else:
            print(payload["instruction"])
        return 0
    if command == "archive":
        positions = _positional(argv[1:])
        if not positions:
            print("missing change name", file=sys.stderr)
            return 1
        name = positions[0]
        src = root / "openspec" / "changes" / name
        if not src.is_dir():
            print(f"unknown change {name}", file=sys.stderr)
            return 1
        archived_as = f"2026-10-18-{name}"
        dest = root / "openspec" / "changes" / "archive" / archived_as
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        if "--json" in argv:
            print(
                json.dumps(
                    {
                        "archive": {
                            "change": name,
                            "archivedAs": archived_as,
                            "path": str(dest),
                            "specsUpdated": True,
                        }
                    }
                )
            )
        else:
            print(f"Change '{name}' archived as '{archived_as}'.")
        return 0
    print(f"unknown command {command}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""The `w2c cloud` command group."""

from __future__ import annotations

import argparse

from w2c.cloud import environment


def register(sub: argparse._SubParsersAction) -> None:
    cloud = sub.add_parser("cloud", help="opt-in cloud mode commands")
    csub = cloud.add_subparsers(dest="cloud_cmd", required=True)
    csub.add_parser("env", help="report whether this is a temporary container")
    new = csub.add_parser("new", help="create an OpenSpec change with delivery keys")
    new.add_argument("--slug", required=True)
    new.add_argument("--cadence", default=None, help="git delivery cadence for this change")
    nxt = csub.add_parser("next", help="next open task of the active change")
    nxt.add_argument("--change", default=None)
    nxt.add_argument("--slice", dest="slice_id", default=None)
    nxt.add_argument("--task", dest="task_id", default=None)
    csub.add_parser("status", help="progress of each active change")
    comp = csub.add_parser("complete", help="tick a task (requires S##-T##-SUMMARY.md)")
    comp.add_argument("--change", required=True)
    comp.add_argument("--slice", dest="slice_id", required=True)
    comp.add_argument("--task", dest="task_id", required=True)
    sl = csub.add_parser("slice-complete", help="record a slice done (requires UAT + SUMMARY)")
    sl.add_argument("--change", required=True)
    sl.add_argument("--slice", dest="slice_id", required=True)
    arch = csub.add_parser("archive", help="archive a finished change and mark it DONE")
    arch.add_argument("change")
    mc = csub.add_parser("milestone-complete", help="mark a change DONE")
    mc.add_argument("change")
    mc.add_argument("--archive-declined", action="store_true")
    ss = csub.add_parser("status-set", help="set a change status (not DONE)")
    ss.add_argument("change")
    ss.add_argument("status")


def dispatch(args: argparse.Namespace) -> int:
    if args.cloud_cmd == "env":
        return environment.cmd_env()
    from w2c import cli as w2c_cli
    from w2c.cloud import commands

    root = args.root.resolve() if args.root else w2c_cli.find_repo_root()
    cmd = args.cloud_cmd
    if cmd == "new":
        return commands.new(root, args.slug, args.cadence)
    if cmd == "next":
        return commands.next_cmd(root, args.change, args.slice_id, args.task_id)
    if cmd == "status":
        return commands.status(root)
    if cmd == "complete":
        return commands.complete(root, args.change, args.slice_id, args.task_id)
    if cmd == "slice-complete":
        return commands.slice_complete(root, args.change, args.slice_id)
    if cmd == "archive":
        return commands.archive(root, args.change)
    if cmd == "milestone-complete":
        return commands.milestone_complete(root, args.change, args.archive_declined)
    if cmd == "status-set":
        return commands.status_set(root, args.change, args.status)
    raise SystemExit(f"unknown cloud command {cmd}")

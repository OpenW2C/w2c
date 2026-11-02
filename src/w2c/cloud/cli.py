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
    dec = csub.add_parser("decide", help="log a decision in the change's design")
    dec.add_argument("--change", default=None)
    dec.add_argument("--scope", required=True)
    dec.add_argument("--decision", required=True)
    dec.add_argument("--choice", required=True)
    dec.add_argument("--rationale", required=True)
    dec.add_argument("--revisable", default="Yes")
    dec.add_argument("--made-by", default="collaborative")
    dec.add_argument("--when", default=None)
    fl = csub.add_parser("decisions-flush", help="move held decisions into a change's design")
    fl.add_argument("--change", required=True)
    od = csub.add_parser("order", help="set the run order of active changes")
    od.add_argument("names", nargs="+", metavar="NAME")
    sw = csub.add_parser("swap", help="swap two changes in the run order")
    sw.add_argument("left")
    sw.add_argument("right")
    mv = csub.add_parser("move", help="move a change before or after another")
    mv.add_argument("name")
    group = mv.add_mutually_exclusive_group(required=True)
    group.add_argument("--before", default=None)
    group.add_argument("--after", default=None)


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
    if cmd == "decide":
        row = {"when": args.when or "", "scope": args.scope, "decision": args.decision,
               "choice": args.choice, "rationale": args.rationale,
               "revisable": args.revisable, "made_by": args.made_by}
        return commands.decide(root, args.change, row)
    if cmd == "decisions-flush":
        return commands.decisions_flush(root, args.change)
    if cmd == "order":
        return commands.order(root, args.names)
    if cmd == "swap":
        return commands.swap(root, args.left, args.right)
    if cmd == "move":
        return commands.move(root, args.name, args.before, args.after)
    raise SystemExit(f"unknown cloud command {cmd}")

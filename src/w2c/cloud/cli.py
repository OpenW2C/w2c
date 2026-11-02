"""The `w2c cloud` command group."""

from __future__ import annotations

import argparse

from w2c.cloud import environment


def register(sub: argparse._SubParsersAction) -> None:
    cloud = sub.add_parser("cloud", help="opt-in cloud mode commands")
    csub = cloud.add_subparsers(dest="cloud_cmd", required=True)
    csub.add_parser("env", help="report whether this is a temporary container")


def dispatch(args: argparse.Namespace) -> int:
    if args.cloud_cmd == "env":
        return environment.cmd_env()
    raise SystemExit(f"unknown cloud command {args.cloud_cmd}")

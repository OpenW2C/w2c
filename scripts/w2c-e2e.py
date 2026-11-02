#!/usr/bin/env python3
"""Run the full-cycle suites against the current checkout on a dummy project."""

from __future__ import annotations

import argparse
import importlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# scripts/w2c.py would shadow the w2c package, so drop this folder from the import path.
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != Path(__file__).resolve().parent]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))


def _stages(suite: str):
    from tests.e2e import harness  # noqa: F401

    modules: list[str] = []
    if suite in ("legacy", "all"):
        modules.append("tests.e2e.legacy_suite")
    if suite in ("cloud", "all"):
        if (REPO / "tests" / "e2e" / "cloud_suite.py").is_file():
            modules.append("tests.e2e.cloud_suite")
        elif suite == "cloud":
            raise SystemExit("E2E: FAIL: tests/e2e/cloud_suite.py does not exist yet")
    stages = []
    for name in modules:
        module = importlib.import_module(name)
        stages.extend(module.STAGES)
    return stages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="W2C full-cycle test")
    parser.add_argument("--suite", choices=["legacy", "cloud", "all"], default="all")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args(argv)

    if shutil.which("openspec") is None:
        print("openspec not found on PATH; the full-cycle test needs it", file=sys.stderr)
        print("E2E: FAIL", file=sys.stderr)
        return 1

    from tests.e2e import harness

    stages = _stages(args.suite)
    tmp = Path(tempfile.mkdtemp(prefix="w2c-e2e-")).resolve()
    keep = os.environ.get("W2C_E2E_KEEP") == "1"
    try:
        results = harness.run_suite(stages, lambda: harness.make_project(tmp))
    finally:
        if keep:
            print(f"kept {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    for stage, ok, error in results:
        mark = "ok  " if ok else "FAIL"
        print(f"{mark} {stage.id} {stage.title}" + ("" if ok else f" — {error}"))
    if args.report is not None:
        harness.write_report(results, args.report)
    passed = bool(results) and all(ok for _s, ok, _e in results)
    print("E2E: PASS" if passed else "E2E: FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

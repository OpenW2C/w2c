#!/usr/bin/env python3
"""Cloud mode change ledger: x-delivery-* keys in .openspec.yaml."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

_HOME = Path(tempfile.mkdtemp(prefix="w2c-cloud-ledger-home-"))
os.environ["W2C_CONFIG"] = str(_HOME / "config.toml")
os.environ["W2C_DATA_HOME"] = str(_HOME / "data")

from w2c import cli as w2c  # noqa: E402
from w2c.cloud import ledger  # noqa: E402


def make_change(root: Path, name: str, lines: list[str], archived: str = "") -> Path:
    base = root / "openspec" / "changes"
    folder = base / "archive" / f"{archived}-{name}" if archived else base / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ".openspec.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return folder


def cloud(status: str = "TODO", **extra: str) -> list[str]:
    lines = ["schema: spec-driven", f"x-delivery-status: {status}"]
    lines += [f"x-delivery-{key.replace('_', '-')}: {value}" for key, value in extra.items()]
    return lines


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


class CloudLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_write_key_round_trip_keeps_other_lines(self) -> None:
        meta = self.root / ".openspec.yaml"
        original = "schema: spec-driven\r\n# note\r\nx-delivery-status: TODO\r\ncreated: 2026-01-01\r\n"
        meta.write_bytes(original.encode())
        ledger.write_key(meta, "x-delivery-slices-done", "[1, 3]")
        ledger.write_key(meta, "x-delivery-status", "DONE")
        text = meta.read_bytes().decode()
        self.assertEqual(
            text,
            "schema: spec-driven\r\n# note\r\nx-delivery-status: DONE\r\n"
            "created: 2026-01-01\r\nx-delivery-slices-done: [1, 3]\r\n",
        )
        self.assertEqual(ledger.read_keys(meta)["x-delivery-slices-done"], "[1, 3]")
        ledger.write_key(meta, "x-delivery-slices-done", None)
        ledger.write_key(meta, "x-delivery-status", "TODO")
        self.assertEqual(meta.read_bytes().decode(), original)
        ledger.write_key(meta, "x-delivery-missing", None)
        self.assertEqual(meta.read_bytes().decode(), original)

    def test_read_keys_tolerates_crlf_comments_quotes(self) -> None:
        meta = self.root / ".openspec.yaml"
        meta.write_bytes(
            b'# head\r\nschema: spec-driven\r\n\r\nx-delivery-status: "INPROGRESS"\r\n'
            b"x-delivery-cadence: 'slice'  # why\r\n  nested: ignored\r\n"
        )
        keys = ledger.read_keys(meta)
        self.assertEqual(keys["x-delivery-status"], "INPROGRESS")
        self.assertEqual(keys["x-delivery-cadence"], "slice")
        self.assertEqual(keys["schema"], "spec-driven")
        self.assertNotIn("nested", keys)

    def test_duplicate_delivery_key_is_error(self) -> None:
        meta = self.root / ".openspec.yaml"
        meta.write_text("x-delivery-status: TODO\nx-delivery-status: DONE\n", encoding="utf-8")
        with self.assertRaises(w2c.W2CError):
            ledger.read_keys(meta)

    def test_list_changes_orders_by_order_then_name(self) -> None:
        make_change(self.root, "b", cloud(order="1"))
        make_change(self.root, "a", cloud())
        make_change(self.root, "c", cloud(order="1"))
        names = [c.name for c in ledger.list_changes(self.root)]
        self.assertEqual(names, ["b", "c", "a"])

    def test_list_changes_skips_non_cloud_and_reads_archive(self) -> None:
        make_change(self.root, "plain", ["schema: spec-driven"])
        make_change(self.root, "live", cloud("PAUSED", slices_done="[1, 3]", cadence="slice"))
        make_change(self.root, "old", cloud("DONE"), archived="2026-01-02")
        active = ledger.list_changes(self.root)
        self.assertEqual([c.name for c in active], ["live"])
        self.assertEqual(active[0].status, "PAUSED")
        self.assertEqual(active[0].slices_done, [1, 3])
        self.assertEqual(active[0].cadence, "slice")
        self.assertFalse(active[0].archived)
        both = ledger.list_changes(self.root, include_archived=True)
        self.assertEqual(sorted(c.name for c in both), ["live", "old"])
        old = next(c for c in both if c.name == "old")
        self.assertTrue(old.archived)
        self.assertEqual(old.slices_done, [])

    def test_resolve_prefers_active_then_archive_then_legacy_id(self) -> None:
        make_change(self.root, "feat", cloud())
        make_change(self.root, "feat", cloud("DONE"), archived="2026-01-02")
        make_change(self.root, "gone", cloud("DONE"), archived="2026-01-03")
        make_change(self.root, "other", cloud(legacy_id="M003"))
        self.assertFalse(ledger.resolve(self.root, "feat").archived)
        self.assertTrue(ledger.resolve(self.root, "gone").archived)
        self.assertEqual(ledger.resolve(self.root, "M003").name, "other")
        with self.assertRaises(w2c.W2CError):
            ledger.resolve(self.root, "nope")

    def test_resolve_refuses_ambiguous_legacy_id(self) -> None:
        make_change(self.root, "one", cloud(legacy_id="M001"))
        make_change(self.root, "two", cloud(legacy_id="M001"))
        with self.assertRaises(w2c.W2CError):
            ledger.resolve(self.root, "M001")

    def test_branch_names_none_on_detached_head_or_no_match(self) -> None:
        git(self.root, "init", "-b", "main")
        folder = make_change(self.root, "feat", cloud())
        make_change(self.root, "other", cloud())
        (folder / "design.md").write_text(
            "# D\n\n## Delivery Plan\n| Field | Value |\n| --- | --- |\n"
            "| Remote branch | feat-branch |\n",
            encoding="utf-8",
        )
        git(self.root, "add", "-A")
        git(self.root, "commit", "-m", "init")
        change = ledger.resolve(self.root, "feat")
        self.assertEqual(ledger.remote_branch(change), "feat-branch")
        self.assertEqual(ledger.remote_branch(ledger.resolve(self.root, "other")), "")
        self.assertIsNone(ledger.branch_names(self.root))
        git(self.root, "checkout", "-b", "feat-branch")
        self.assertEqual(ledger.branch_names(self.root), {"feat"})
        git(self.root, "checkout", "--detach")
        self.assertIsNone(ledger.branch_names(self.root))
        self.assertEqual(ledger.delivery_dir(change), change.path / "delivery")


if __name__ == "__main__":
    unittest.main()

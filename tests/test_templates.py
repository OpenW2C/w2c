#!/usr/bin/env python3
"""Runtime templates must come from DATA_HOME, never the git checkout."""

from __future__ import annotations

import importlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import w2c.cli as w2c_cli
import w2c.local as w2c_local

CHECKOUT_TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
DATA_MARKER = "DATA_HOME_MARKER_UNIQUE\n"
EMBEDDED_FALLBACK = "FALLBACK"


class TemplatesDataHomeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._env = os.environ.copy()
        self.tmp = Path(tempfile.mkdtemp(prefix="w2c-templates-test-"))
        os.environ["W2C_DATA_HOME"] = str(self.tmp / "data")
        self.data_templates = w2c_local.data_home() / "templates"
        self.data_templates.mkdir(parents=True)
        (self.data_templates / "M-ROADMAP.md").write_text(DATA_MARKER, encoding="utf-8")
        importlib.reload(w2c_cli)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ.clear()
        os.environ.update(self._env)
        importlib.reload(w2c_cli)

    def test_templates_dir_returns_data_home_not_checkout(self) -> None:
        self.assertTrue(CHECKOUT_TEMPLATES.is_dir())
        self.assertTrue((CHECKOUT_TEMPLATES / "M-ROADMAP.md").is_file())
        got = w2c_cli.templates_dir()
        expected = w2c_local.data_home() / "templates"
        self.assertEqual(got, expected)
        self.assertNotEqual(got.resolve(), CHECKOUT_TEMPLATES.resolve())

    def test_load_template_reads_data_home_not_checkout(self) -> None:
        checkout_text = (CHECKOUT_TEMPLATES / "M-ROADMAP.md").read_text(encoding="utf-8")
        self.assertNotIn("DATA_HOME_MARKER_UNIQUE", checkout_text)
        text = w2c_cli.load_template("M-ROADMAP.md", embedded=EMBEDDED_FALLBACK)
        self.assertEqual(text, DATA_MARKER)
        self.assertNotEqual(text, checkout_text)
        self.assertNotEqual(text, EMBEDDED_FALLBACK)

    def test_load_template_missing_file_returns_embedded_not_checkout(self) -> None:
        (self.data_templates / "M-ROADMAP.md").unlink()
        text = w2c_cli.load_template("M-ROADMAP.md", embedded=EMBEDDED_FALLBACK)
        self.assertEqual(text, EMBEDDED_FALLBACK)

"""CLI defaults: offline fixture, no key, no send."""

from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from fomo_oneshot.cli import main
from fomo_oneshot.tests.test_mapping import FIXTURES


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.seen = str(Path(self.tmp.name) / "seen.json")
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop("PUMPFOMO_API_KEY", None)
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        os.environ["PUMPFOMO_API_KEY"] = "pf_live_should_not_print"

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def _main(self, argv):
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = main(argv)
        return code, buffer.getvalue()

    def test_fixture_replay_is_a_dry_run_with_zero_sends(self):
        root = Path(__file__).resolve().parents[2]
        state = next((root / "d").rglob("state.json"), None) if (root / "d").is_dir() else None
        index = root / "index.html"
        before = None
        if state is not None and index.is_file():
            before = (state.stat().st_mtime_ns, index.stat().st_mtime_ns)
        with mock.patch("urllib.request.build_opener", side_effect=AssertionError("network")):
            code, report = self._main([
                "--fixture",
                str(FIXTURES / "sell_page.json"),
                "--replay",
                "--seen",
                self.seen,
                "--handle",
                "@PressingProfits",
            ])
        self.assertEqual(code, 0)
        self.assertIn("mode: dry-run", report)
        self.assertIn("sends: 0", report)
        self.assertIn("requests: 0", report)
        self.assertIn("fixture: yes", report)
        self.assertNotIn("pf_live_should_not_print", report)
        self.assertIn("Nov 6 21:46:05 AST", report)
        if before is not None:
            self.assertEqual((state.stat().st_mtime_ns, index.stat().st_mtime_ns), before)

    def test_missing_provider_key_does_not_open_a_socket(self):
        os.environ.pop("PUMPFOMO_API_KEY", None)
        with mock.patch("urllib.request.build_opener", side_effect=AssertionError("network")):
            code, report = self._main(["--seen", self.seen])
        self.assertEqual(code, 2)
        self.assertIn("PUMPFOMO_API_KEY is not set", report)
        self.assertIn("sends: 0", report)
        self.assertNotIn("pf_live", report)

    def test_send_without_bot_token_sends_nothing(self):
        with mock.patch("urllib.request.build_opener", side_effect=AssertionError("network")):
            code, report = self._main([
                "--fixture",
                str(FIXTURES / "sell_page.json"),
                "--replay",
                "--send",
                "--seen",
                self.seen,
            ])
        self.assertEqual(code, 2)
        self.assertIn("TELEGRAM_BOT_TOKEN is not set", report)
        self.assertIn("sends: 0", report)

    def test_cli_has_no_recipient_switch(self):
        text = Path(__file__).resolve().parents[1].joinpath("cli.py").read_text(encoding="utf-8")
        self.assertNotIn("--chat", text)
        self.assertNotIn("--to", text)


if __name__ == "__main__":
    unittest.main()

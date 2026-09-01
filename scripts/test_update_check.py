#!/usr/bin/env python3
"""更新检查器的确定性测试，不访问真实网络。"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "scripts" / "check_update.py.template"
LOADER = SourceFileLoader("ljhskill_check_update", str(SOURCE))
SPEC = importlib.util.spec_from_loader("ljhskill_check_update", LOADER)
CHECKER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(CHECKER)


class UpdateCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.release_path = self.temp_path / "release.json"
        self.state_path = self.temp_path / "state.json"
        self.now = datetime(2026, 8, 31, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_release(self, version="1.0.1"):
        self.release_path.write_text(
            json.dumps(
                {
                    "version": version,
                    "summary": "测试更新",
                    "readme_url": "https://example.com/readme",
                    "update_instructions_url": "https://example.com/update",
                }
            ),
            encoding="utf-8",
        )

    def check(self, current=None):
        return CHECKER.check_for_update(
            release_file=self.release_path,
            state_path=self.state_path,
            now=current or self.now,
        )

    def test_48_hour_throttle(self):
        self.write_release("1.0.1")
        self.assertIn("v1.0.1", self.check())
        self.write_release("1.0.2")
        self.assertEqual("", self.check(self.now + timedelta(hours=47)))
        self.assertIn("v1.0.2", self.check(self.now + timedelta(hours=48)))

    def test_new_version_reminder(self):
        self.write_release("1.0.1")
        message = self.check()
        self.assertIn("有新版本 v1.0.1", message)
        self.assertIn("测试更新", message)
        self.assertIn("请按说明更新：https://example.com/update", message)
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(self.now.isoformat(), state["last_success_at"])

    def test_v_prefixed_remote_version_is_normalized(self):
        self.write_release("v1.0.1")
        message = self.check()
        self.assertIn("有新版本 v1.0.1", message)
        self.assertNotIn("vv1.0.1", message)
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual("1.0.1", state["last_notified_version"])

    def test_same_version_is_not_repeated_before_seven_days(self):
        self.write_release("1.0.1")
        self.assertTrue(self.check())
        self.assertEqual("", self.check(self.now + timedelta(days=6)))

    def test_same_version_is_reminded_after_seven_days(self):
        self.write_release("1.0.1")
        self.assertTrue(self.check())
        message = self.check(self.now + timedelta(days=7))
        self.assertIn("有新版本 v1.0.1", message)

    def test_disabled(self):
        self.write_release("1.0.1")
        with patch.dict(os.environ, {"LJHSKILL_DISABLE_UPDATE_CHECK": "1"}):
            self.assertEqual("", self.check())
        self.assertFalse(self.state_path.exists())

    def test_corrupt_state_is_recovered(self):
        self.write_release("1.0.1")
        self.state_path.write_text("{bad", encoding="utf-8")
        self.assertIn("v1.0.1", self.check())
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual("1.0.1", state["last_notified_version"])

    def test_read_and_network_failures_are_silent(self):
        missing_release = self.temp_path / "missing.json"
        message = CHECKER.check_for_update(
            release_file=missing_release,
            state_path=self.temp_path / "missing-state.json",
            now=self.now,
        )
        self.assertEqual("", message)

        with patch.object(CHECKER, "urlopen", side_effect=OSError("offline")):
            message = CHECKER.check_for_update(
                state_path=self.temp_path / "network-state.json",
                now=self.now,
            )
        self.assertEqual("", message)

    def test_failed_check_is_throttled_and_success_is_recorded(self):
        release_path = self.temp_path / "later-release.json"
        state_path = self.temp_path / "later-state.json"
        message = CHECKER.check_for_update(
            release_file=release_path,
            state_path=state_path,
            now=self.now,
        )
        self.assertEqual("", message)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(self.now.isoformat(), state["last_checked_at"])
        self.assertNotIn("last_success_at", state)

        release_path.write_text(
            json.dumps(
                {
                    "version": "1.0.1",
                    "summary": "测试更新",
                    "update_instructions_url": "https://example.com/update",
                }
            ),
            encoding="utf-8",
        )
        message = CHECKER.check_for_update(
            release_file=release_path,
            state_path=state_path,
            now=self.now + timedelta(hours=47),
        )
        self.assertEqual("", message)

        success_time = self.now + timedelta(hours=48)
        message = CHECKER.check_for_update(
            release_file=release_path,
            state_path=state_path,
            now=success_time,
        )
        self.assertIn("v1.0.1", message)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(success_time.isoformat(), state["last_success_at"])


if __name__ == "__main__":
    unittest.main()

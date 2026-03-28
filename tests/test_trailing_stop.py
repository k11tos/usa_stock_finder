"""
test_trailing_stop.py

Unit tests for trailing_stop state persistence and highest-close update logic.
"""

import json
import os
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

from trailing_stop import load_trailing_state, save_trailing_state, update_highest_close


class TestTrailingStop(unittest.TestCase):
    """Unit tests for trailing_stop module."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.state_path = os.path.join(self.temp_dir, "trailing_state.json")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_trailing_state_returns_empty_when_file_missing(self):
        with patch("trailing_stop.TRAILING_STATE_PATH", self.state_path):
            result = load_trailing_state()
        self.assertEqual(result, {})

    def test_load_trailing_state_returns_empty_on_invalid_json(self):
        with open(self.state_path, "w", encoding="utf-8") as f:
            f.write("{invalid json")

        with patch("trailing_stop.TRAILING_STATE_PATH", self.state_path):
            result = load_trailing_state()

        self.assertEqual(result, {})

    def test_save_trailing_state_writes_state_successfully(self):
        state = {
            "AAPL": {
                "highest_close": 210.5,
                "last_update": "2026-03-28",
            }
        }

        with patch("trailing_stop.TRAILING_STATE_PATH", self.state_path):
            save_trailing_state(state)

        self.assertTrue(os.path.exists(self.state_path))
        with open(self.state_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertEqual(loaded, state)

    def test_update_highest_close_initializes_new_symbol(self):
        state = {}
        today = date(2026, 3, 28)

        result = update_highest_close(state, "MSFT", 432.1, today)

        self.assertEqual(result, 432.1)
        self.assertIn("MSFT", state)
        self.assertEqual(state["MSFT"]["highest_close"], 432.1)
        self.assertEqual(state["MSFT"]["last_update"], today.isoformat())

    def test_update_highest_close_stays_at_prior_high_for_lower_close(self):
        state = {
            "TSLA": {
                "highest_close": 275.0,
                "last_update": "2026-03-27",
            }
        }
        today = date(2026, 3, 28)

        result = update_highest_close(state, "TSLA", 260.0, today)

        self.assertEqual(result, 275.0)
        self.assertEqual(state["TSLA"]["highest_close"], 275.0)
        self.assertEqual(state["TSLA"]["last_update"], today.isoformat())

    def test_update_highest_close_ignores_non_positive_close_and_returns_previous_high(self):
        state = {
            "NVDA": {
                "highest_close": 990.0,
                "last_update": "2026-03-27",
            }
        }
        today = date(2026, 3, 28)

        zero_result = update_highest_close(state, "NVDA", 0.0, today)
        negative_result = update_highest_close(state, "NVDA", -15.0, today)

        self.assertEqual(zero_result, 990.0)
        self.assertEqual(negative_result, 990.0)
        self.assertEqual(state["NVDA"]["highest_close"], 990.0)
        # Non-positive close should not mutate last_update
        self.assertEqual(state["NVDA"]["last_update"], "2026-03-27")


if __name__ == "__main__":
    unittest.main()

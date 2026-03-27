"""
Regression tests for trailing_stop.py state load/save/update behavior.
"""

import os
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

from trailing_stop import load_trailing_state, save_trailing_state, update_highest_close


class TestTrailingStopState(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_state_path = os.path.join(self.temp_dir, "trailing_state.json")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_missing_state_file_returns_empty_dict(self):
        with patch("trailing_stop.TRAILING_STATE_PATH", self.temp_state_path):
            self.assertEqual(load_trailing_state(), {})

    def test_update_highest_close_for_new_symbol(self):
        state = {}
        today = date(2025, 1, 20)

        new_high = update_highest_close(state, "AAPL", 123.45, today)

        self.assertEqual(new_high, 123.45)
        self.assertEqual(state["AAPL"]["highest_close"], 123.45)
        self.assertEqual(state["AAPL"]["last_update"], "2025-01-20")

    def test_update_highest_close_with_lower_price_keeps_previous_high(self):
        state = {"MSFT": {"highest_close": 250.0, "last_update": "2025-01-19"}}
        today = date(2025, 1, 20)

        new_high = update_highest_close(state, "MSFT", 240.0, today)

        self.assertEqual(new_high, 250.0)
        self.assertEqual(state["MSFT"]["highest_close"], 250.0)
        self.assertEqual(state["MSFT"]["last_update"], "2025-01-20")

    def test_save_and_load_round_trip(self):
        state = {
            "NVDA": {"highest_close": 900.5, "last_update": "2025-01-20"},
            "TSLA": {"highest_close": 250.0, "last_update": "2025-01-20"},
        }

        with patch("trailing_stop.TRAILING_STATE_PATH", self.temp_state_path):
            save_trailing_state(state)
            loaded = load_trailing_state()

        self.assertEqual(loaded, state)


if __name__ == "__main__":
    unittest.main()

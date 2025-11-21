"""
test_stop_loss_cooldown.py

This module contains unit tests for the stop_loss_cooldown module.
It tests the Stop Loss cooldown functionality including:
- Recording stop loss events
- Calculating cooldown periods based on loss percentage
- Checking if stocks are in cooldown period
- Filtering buy signals based on cooldown status
"""

import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from stop_loss_cooldown import (
    calculate_cooldown_days,
    is_in_cooldown,
    load_stop_loss_log,
    record_stop_loss_event,
    save_stop_loss_log,
)


class TestStopLossCooldown(unittest.TestCase):
    """Test stop loss cooldown module"""

    def setUp(self):
        """Set up test fixtures"""
        # 임시 디렉토리와 파일 경로 생성
        self.temp_dir = tempfile.mkdtemp()
        self.temp_log_path = os.path.join(self.temp_dir, "stop_loss_log.json")
        self.temp_data_dir = os.path.join(self.temp_dir, "data")
        os.makedirs(self.temp_data_dir, exist_ok=True)

    def tearDown(self):
        """Clean up test fixtures"""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_stop_loss_log_file_not_exists(self):
        """Test loading stop loss log when file doesn't exist"""
        with patch("stop_loss_cooldown.STOP_LOSS_LOG_PATH", os.path.join(self.temp_dir, "nonexistent.json")):
            result = load_stop_loss_log()
            self.assertEqual(result, {})

    def test_load_stop_loss_log_file_exists(self):
        """Test loading stop loss log when file exists"""
        test_data = {
            "TEST": {"last_stop_loss_date": "2025-01-01", "loss_pct": -0.15},
            "ABC": {"last_stop_loss_date": "2025-01-02", "loss_pct": -0.25},
        }
        with open(self.temp_log_path, "w", encoding="utf-8") as f:
            json.dump(test_data, f)

        with patch("stop_loss_cooldown.STOP_LOSS_LOG_PATH", self.temp_log_path):
            result = load_stop_loss_log()
            self.assertEqual(result, test_data)

    def test_load_stop_loss_log_invalid_json(self):
        """Test loading stop loss log when file has invalid JSON"""
        with open(self.temp_log_path, "w", encoding="utf-8") as f:
            f.write("invalid json {")

        with patch("stop_loss_cooldown.STOP_LOSS_LOG_PATH", self.temp_log_path):
            result = load_stop_loss_log()
            self.assertEqual(result, {})

    def test_save_stop_loss_log(self):
        """Test saving stop loss log"""
        log_file = os.path.join(self.temp_data_dir, "stop_loss_log.json")
        test_data = {
            "TEST": {"last_stop_loss_date": "2025-01-01", "loss_pct": -0.15},
        }
        with patch("stop_loss_cooldown.STOP_LOSS_LOG_PATH", log_file):
            save_stop_loss_log(test_data)

        # 파일이 생성되었는지 확인
        self.assertTrue(os.path.exists(log_file))

        # 내용 확인
        with open(log_file, "r", encoding="utf-8") as f:
            loaded_data = json.load(f)
        self.assertEqual(loaded_data, test_data)

    def test_record_stop_loss_event(self):
        """Test recording stop loss event"""
        log_file = os.path.join(self.temp_data_dir, "stop_loss_log.json")
        symbol = "TEST"
        loss_pct = -0.24
        today = date(2025, 1, 20)

        with patch("stop_loss_cooldown.STOP_LOSS_LOG_PATH", log_file):
            record_stop_loss_event(symbol, loss_pct, today)

        # 로그 파일 확인
        self.assertTrue(os.path.exists(log_file))

        with open(log_file, "r", encoding="utf-8") as f:
            log = json.load(f)

        self.assertIn(symbol, log)
        self.assertEqual(log[symbol]["last_stop_loss_date"], today.isoformat())
        self.assertEqual(log[symbol]["loss_pct"], loss_pct)

    def test_record_stop_loss_event_positive_loss_ignored(self):
        """Test that positive loss_pct is ignored"""
        log_file = os.path.join(self.temp_data_dir, "stop_loss_log.json")
        symbol = "TEST"
        loss_pct = 0.10  # 양수 (손실이 아님)
        today = date(2025, 1, 20)

        with patch("stop_loss_cooldown.STOP_LOSS_LOG_PATH", log_file):
            record_stop_loss_event(symbol, loss_pct, today)

        # 로그 파일이 생성되지 않았거나 비어있어야 함
        if os.path.exists(log_file):
            with open(log_file, "r", encoding="utf-8") as f:
                log = json.load(f)
            self.assertNotIn(symbol, log)

    def test_record_stop_loss_event_overwrite(self):
        """Test that recording multiple times overwrites previous entry"""
        log_file = os.path.join(self.temp_data_dir, "stop_loss_log.json")
        symbol = "TEST"
        today1 = date(2025, 1, 20)
        today2 = date(2025, 1, 25)

        with patch("stop_loss_cooldown.STOP_LOSS_LOG_PATH", log_file):
            record_stop_loss_event(symbol, -0.15, today1)
            record_stop_loss_event(symbol, -0.25, today2)

        # 최근 이벤트만 저장되어야 함
        with open(log_file, "r", encoding="utf-8") as f:
            log = json.load(f)

        self.assertEqual(log[symbol]["last_stop_loss_date"], today2.isoformat())
        self.assertEqual(log[symbol]["loss_pct"], -0.25)

    def test_calculate_cooldown_days(self):
        """Test cooldown days calculation"""
        # -8% 손절 → 5일 (base만)
        self.assertEqual(calculate_cooldown_days(-0.08), 5)

        # -15% 손절 → 10일 (base 5 + 1 block * 5)
        self.assertEqual(calculate_cooldown_days(-0.15), 10)

        # -25% 손절 → 15일 (base 5 + 2 blocks * 5)
        self.assertEqual(calculate_cooldown_days(-0.25), 15)

        # -28% 손절 → 15일 (base 5 + 2 blocks * 5)
        self.assertEqual(calculate_cooldown_days(-0.28), 15)

        # -9% 손절 → 5일 (base만, 10% 미만이므로)
        self.assertEqual(calculate_cooldown_days(-0.09), 5)

    def test_is_in_cooldown_no_entry(self):
        """Test is_in_cooldown when symbol is not in log"""
        log_file = os.path.join(self.temp_data_dir, "stop_loss_log.json")
        today = date(2025, 1, 20)
        with patch("stop_loss_cooldown.STOP_LOSS_LOG_PATH", log_file):
            result = is_in_cooldown("NONEXISTENT", today)
        self.assertFalse(result)

    def test_is_in_cooldown_within_period(self):
        """Test is_in_cooldown when still within cooldown period"""
        log_file = os.path.join(self.temp_data_dir, "stop_loss_log.json")
        symbol = "TEST"
        today = date(2025, 1, 20)
        loss_pct = -0.25  # 15일 쿨다운

        with patch("stop_loss_cooldown.STOP_LOSS_LOG_PATH", log_file):
            # 이벤트 기록
            record_stop_loss_event(symbol, loss_pct, today)

            # 같은 날 체크 (쿨다운 내)
            result = is_in_cooldown(symbol, today)
            self.assertTrue(result)

            # 14일 후 체크 (아직 쿨다운 내)
            result = is_in_cooldown(symbol, today + timedelta(days=14))
            self.assertTrue(result)

    def test_is_in_cooldown_after_period(self):
        """Test is_in_cooldown when cooldown period has passed"""
        log_file = os.path.join(self.temp_data_dir, "stop_loss_log.json")
        symbol = "TEST"
        today = date(2025, 1, 20)
        loss_pct = -0.25  # 15일 쿨다운

        with patch("stop_loss_cooldown.STOP_LOSS_LOG_PATH", log_file):
            # 이벤트 기록
            record_stop_loss_event(symbol, loss_pct, today)

            # 16일 후 체크 (쿨다운 종료)
            result = is_in_cooldown(symbol, today + timedelta(days=16))
        self.assertFalse(result)

    def test_is_in_cooldown_different_loss_percentages(self):
        """Test is_in_cooldown with different loss percentages"""
        log_file = os.path.join(self.temp_data_dir, "stop_loss_log.json")
        today = date(2025, 1, 20)

        with patch("stop_loss_cooldown.STOP_LOSS_LOG_PATH", log_file):
            # -8% 손절 → 5일 쿨다운
            record_stop_loss_event("TEST1", -0.08, today)
            self.assertTrue(is_in_cooldown("TEST1", today + timedelta(days=4)))  # 4일 후: 쿨다운 내
            self.assertFalse(is_in_cooldown("TEST1", today + timedelta(days=6)))  # 6일 후: 쿨다운 종료

            # -15% 손절 → 10일 쿨다운
            record_stop_loss_event("TEST2", -0.15, today)
            self.assertTrue(is_in_cooldown("TEST2", today + timedelta(days=9)))  # 9일 후: 쿨다운 내
            self.assertFalse(is_in_cooldown("TEST2", today + timedelta(days=11)))  # 11일 후: 쿨다운 종료

            # -28% 손절 → 15일 쿨다운
            record_stop_loss_event("TEST3", -0.28, today)
            self.assertTrue(is_in_cooldown("TEST3", today + timedelta(days=14)))  # 14일 후: 쿨다운 내
            self.assertFalse(is_in_cooldown("TEST3", today + timedelta(days=16)))  # 16일 후: 쿨다운 종료


if __name__ == "__main__":
    unittest.main()


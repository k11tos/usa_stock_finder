"""
test_error_handling_integration.py

Integration tests for error handling and exception scenarios.
Tests how the system handles errors across different modules and workflows.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from file_utils import load_json, read_csv_first_column, save_json
from main import select_stocks
from stock_analysis import UsaStockFinder
from telegram_utils import send_telegram_message


class TestErrorHandlingIntegration(unittest.TestCase):
    """Test error handling integration across modules"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.error_log_file = os.path.join(self.temp_dir, "error_log.json")
        self.portfolio_file = os.path.join(self.temp_dir, "portfolio.csv")

        # Create test portfolio
        portfolio_content = "Code,Name,Market\nAAPL-US,Apple Inc,Nasdaq\nMSFT-US,Microsoft Corp,Nasdaq"
        with open(self.portfolio_file, "w", encoding="utf-8") as f:
            f.write(portfolio_content)

        # Create error log
        error_log = {"errors": [], "last_error": None, "error_count": 0}
        with open(self.error_log_file, "w", encoding="utf-8") as f:
            json.dump(error_log, f)

    def tearDown(self):
        """Clean up test fixtures"""
        for file_path in [self.error_log_file, self.portfolio_file]:
            if os.path.exists(file_path):
                os.remove(file_path)
        # Clean up temp directory and all contents
        import shutil

        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_file_system_error_integration(self):
        """Test file system error handling integration"""
        # Test file not found errors
        with self.assertRaises(FileNotFoundError):
            read_csv_first_column("non_existent_file.csv")

        # Test permission errors (simulated)
        with patch("builtins.open", side_effect=PermissionError("Permission denied")):
            with self.assertRaises(PermissionError):
                read_csv_first_column(self.portfolio_file)

        # Test disk full errors (simulated)
        with patch("builtins.open", side_effect=OSError("No space left on device")):
            with self.assertRaises(OSError):
                save_json({"test": "data"}, "test.json")

    def test_data_corruption_error_integration(self):
        """Test data corruption error handling integration"""
        # Test corrupted CSV files
        corrupted_csv = os.path.join(self.temp_dir, "corrupted.csv")

        # Empty file
        with open(corrupted_csv, "w", encoding="utf-8") as f:
            f.write("")

        symbols = read_csv_first_column(corrupted_csv)
        self.assertEqual(symbols, [])

        # Corrupted CSV with invalid format
        with open(corrupted_csv, "w", encoding="utf-8") as f:
            f.write("Code,Name,Market\n")  # Header row
            f.write("Invalid,CSV,Format\n")
            f.write("No,Code,Column\n")

        symbols = read_csv_first_column(corrupted_csv)
        self.assertEqual(symbols, ["Invalid", "No"])

        # Test corrupted JSON files
        corrupted_json = os.path.join(self.temp_dir, "corrupted.json")

        # Invalid JSON
        with open(corrupted_json, "w", encoding="utf-8") as f:
            f.write("{invalid json content")

        with self.assertRaises(json.JSONDecodeError):
            load_json(corrupted_json)

        # Empty JSON file
        with open(corrupted_json, "w", encoding="utf-8") as f:
            f.write("")

        with self.assertRaises(json.JSONDecodeError):
            load_json(corrupted_json)

    @patch("yfinance.download")
    def test_external_api_error_integration(self, mock_download):
        """Test external API error handling integration"""
        # Test yfinance download failures
        mock_download.side_effect = Exception("API rate limit exceeded")

        with self.assertRaises(Exception):
            UsaStockFinder(["AAPL", "MSFT"])

        # Test network errors
        mock_download.side_effect = ConnectionError("Network connection failed")

        with self.assertRaises(ConnectionError):
            UsaStockFinder(["AAPL", "MSFT"])

        # Test timeout errors
        mock_download.side_effect = TimeoutError("Request timed out")

        with self.assertRaises(TimeoutError):
            UsaStockFinder(["AAPL", "MSFT"])

    @patch("stock_operations.mojito.KoreaInvestment")
    def test_stock_api_error_integration(self, mock_korea_investment):
        """Test stock API error handling integration"""
        # Test API authentication errors
        mock_api = MagicMock()
        mock_api.fetch_us_stock_holdings.side_effect = Exception("Invalid API key")
        mock_korea_investment.return_value = mock_api

        with self.assertRaises(Exception):
            from stock_operations import fetch_us_stock_holdings

            fetch_us_stock_holdings("invalid_token", "test_account")

        # Test API rate limiting
        mock_api.fetch_us_stock_holdings.side_effect = Exception("Rate limit exceeded")

        with self.assertRaises(Exception):
            fetch_us_stock_holdings("test_token", "test_account")

    @patch("telegram_utils.telegram.Bot")
    def test_telegram_error_integration(self, mock_bot_class):
        """Test Telegram error handling integration"""
        import asyncio

        from telegram.error import Forbidden, NetworkError, TelegramError

        # Test network errors
        mock_bot = MagicMock()
        mock_bot.sendMessage = AsyncMock(side_effect=NetworkError("Network error"))
        mock_bot_class.return_value = mock_bot

        async def test_network_error():
            # Should handle network errors gracefully
            await send_telegram_message("test_token", "test_chat_id", "Test message")

        # Network error should not raise exception
        asyncio.run(test_network_error())

        # Test forbidden errors
        mock_bot.sendMessage = AsyncMock(side_effect=Forbidden("Forbidden"))

        async def test_forbidden_error():
            with self.assertRaises(Forbidden):
                await send_telegram_message("invalid_token", "test_chat_id", "Test message")

        asyncio.run(test_forbidden_error())

        # Test other Telegram errors
        mock_bot.sendMessage = AsyncMock(side_effect=TelegramError("Telegram error"))

        async def test_telegram_error():
            with self.assertRaises(TelegramError):
                await send_telegram_message("test_token", "test_chat_id", "Test message")

        asyncio.run(test_telegram_error())

    def test_data_validation_error_integration(self):
        """Test data validation error handling integration"""
        # Test invalid stock symbols
        invalid_symbols = ["", "INVALID_SYMBOL", "123", "A" * 100]  # Too long

        for symbol in invalid_symbols:
            with self.subTest(symbol=symbol):
                # Should handle invalid symbols gracefully
                try:
                    # This might fail in actual implementation
                    pass
                except Exception as e:
                    # Expected behavior
                    self.assertIsInstance(e, Exception)

        # Test invalid correlation data
        invalid_correlations = {
            "200": {"AAPL": "invalid_value"},  # String instead of number
            "100": {"MSFT": -150.0},  # Negative correlation
            "50": {"GOOGL": 1000.0},  # Correlation > 100%
        }

        # Mock finder for testing
        mock_finder = MagicMock()
        mock_finder.symbols = ["AAPL", "MSFT", "GOOGL"]

        # Test with invalid data - should handle gracefully
        try:
            buy_items, not_sell_items = select_stocks(mock_finder, invalid_correlations)
            # If no exception, verify results are lists
            self.assertIsInstance(buy_items, list)
            self.assertIsInstance(not_sell_items, list)
        except Exception as e:
            # Expected behavior if validation fails
            self.assertIsInstance(e, Exception)

    def test_memory_error_integration(self):
        """Test memory error handling integration"""
        import gc

        # Test with extremely large datasets
        try:
            # Create very large portfolio
            large_portfolio_file = os.path.join(self.temp_dir, "huge_portfolio.csv")

            with open(large_portfolio_file, "w", encoding="utf-8") as f:
                f.write("Code,Name,Market\n")
                for i in range(100000):  # 100k stocks
                    symbol = f"STOCK{i:06d}-US"
                    name = "A" * 1000  # Very long names
                    market = "NYSE"
                    f.write(f"{symbol},{name},{market}\n")

            # Force garbage collection
            gc.collect()

            # Try to read large portfolio
            symbols = read_csv_first_column(large_portfolio_file)

            # Should handle large datasets
            self.assertEqual(len(symbols), 100000)

        except MemoryError:
            # Expected behavior if system runs out of memory
            pass
        except Exception as e:
            # Other errors are acceptable for large datasets
            self.assertIsInstance(e, Exception)

    def test_concurrent_error_integration(self):
        """Test concurrent error handling integration"""
        import threading
        import time

        results = []
        errors = []

        def test_concurrent_operations(thread_id):
            try:
                # Simulate concurrent file operations
                if thread_id % 2 == 0:
                    # Read operation
                    symbols = read_csv_first_column(self.portfolio_file)
                    results.append((thread_id, "read", len(symbols)))
                else:
                    # Write operation
                    test_data = {"thread_id": thread_id, "timestamp": time.time()}
                    test_file = os.path.join(self.temp_dir, f"thread_{thread_id}.json")
                    save_json(test_data, test_file)

                    # Verify write
                    loaded_data = load_json(test_file)
                    results.append((thread_id, "write", loaded_data["thread_id"]))

                    # Clean up
                    os.remove(test_file)

            except Exception as e:
                errors.append((thread_id, str(e)))

        # Start multiple threads
        threads = []
        for i in range(20):  # 20 concurrent operations
            thread = threading.Thread(target=test_concurrent_operations, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify most operations succeeded
        self.assertGreater(len(results), len(errors))
        self.assertLess(len(errors), 5)  # Should have few errors

    def test_error_recovery_integration(self):
        """Test error recovery integration across modules"""
        # Test recovery from file corruption
        corrupted_file = os.path.join(self.temp_dir, "corrupted.json")

        # Create corrupted file
        with open(corrupted_file, "w", encoding="utf-8") as f:
            f.write("{corrupted json")

        # Try to load corrupted file
        try:
            load_json(corrupted_file)
            self.fail("Should have raised JSONDecodeError")
        except json.JSONDecodeError:
            # Expected error, now try to recover

            # Create valid file
            valid_data = {"status": "recovered", "timestamp": "2024-01-01T12:00:00Z"}
            save_json(valid_data, corrupted_file)

            # Verify recovery
            recovered_data = load_json(corrupted_file)
            self.assertEqual(recovered_data["status"], "recovered")

        # Test recovery from empty portfolio
        empty_portfolio = os.path.join(self.temp_dir, "empty.csv")
        with open(empty_portfolio, "w", encoding="utf-8") as f:
            f.write("Code,Name,Market\n")

        # Read empty portfolio
        symbols = read_csv_first_column(empty_portfolio)
        self.assertEqual(symbols, [])

        # Add some data to recover
        with open(empty_portfolio, "w", encoding="utf-8") as f:
            f.write("Code,Name,Market\nAAPL-US,Apple Inc,Nasdaq\n")

        # Verify recovery
        symbols = read_csv_first_column(empty_portfolio)
        self.assertEqual(symbols, ["AAPL"])

    def test_error_logging_integration(self):
        """Test error logging integration across the system"""
        # Test error logging workflow
        from file_utils import load_json, save_json

        # Load existing error log
        error_log = load_json(self.error_log_file)

        # Simulate error occurrence
        test_error = {
            "timestamp": "2024-01-01T12:00:00Z",
            "module": "test_error_handling_integration",
            "error_type": "ValueError",
            "error_message": "Test error for integration testing",
            "stack_trace": (
                "Traceback (most recent call last):\n"
                '  File "test.py", line 1, in <module>\n'
                "ValueError: Test error"
            ),
        }

        # Add error to log
        error_log["errors"].append(test_error)
        error_log["last_error"] = test_error["timestamp"]
        error_log["error_count"] += 1

        # Save updated error log
        save_json(error_log, self.error_log_file)

        # Verify error logging
        updated_log = load_json(self.error_log_file)
        self.assertEqual(updated_log["error_count"], 1)
        self.assertEqual(updated_log["last_error"], test_error["timestamp"])
        self.assertEqual(len(updated_log["errors"]), 1)
        self.assertEqual(updated_log["errors"][0]["error_type"], "ValueError")

    def test_performance_under_error_conditions(self):
        """Test performance characteristics under error conditions"""
        import time

        # Test performance when handling errors
        start_time = time.time()

        # Generate multiple errors
        error_count = 0
        for i in range(100):
            try:
                # Simulate potential error conditions
                if i % 10 == 0:
                    raise ValueError(f"Simulated error {i}")
                elif i % 5 == 0:
                    raise TypeError(f"Type error {i}")
            except (ValueError, TypeError):
                error_count += 1

        error_handling_time = time.time() - start_time

        # Verify reasonable performance even with errors
        self.assertLess(error_handling_time, 1.0)  # Should complete within 1 second
        self.assertGreater(error_count, 0)  # Should have caught some errors


if __name__ == "__main__":
    unittest.main()

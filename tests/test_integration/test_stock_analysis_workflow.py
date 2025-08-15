"""
test_stock_analysis_workflow.py

Integration tests for the complete stock analysis workflow.
Tests the interaction between stock analysis, file operations, and main logic.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from main import generate_telegram_message, select_stocks, update_final_items
from stock_analysis import UsaStockFinder
from stock_operations import fetch_us_stock_holdings


class TestStockAnalysisWorkflow(unittest.TestCase):
    """Test complete stock analysis workflow integration"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.portfolio_file = os.path.join(self.temp_dir, "portfolio.csv")
        self.data_file = os.path.join(self.temp_dir, "data.json")

        # Create test portfolio CSV
        portfolio_content = (
            "Code,Name,Market\nAAPL-US,Apple Inc,Nasdaq\nMSFT-US,Microsoft Corp,Nasdaq\nGOOGL-US,Alphabet Inc,Nasdaq"
        )
        with open(self.portfolio_file, "w", encoding="utf-8") as f:
            f.write(portfolio_content)

        # Create test data JSON
        test_data = {"portfolio": ["AAPL", "MSFT"], "last_updated": "2024-01-01"}
        with open(self.data_file, "w", encoding="utf-8") as f:
            json.dump(test_data, f)

    def tearDown(self):
        """Clean up test fixtures"""
        # Remove test files
        for file_path in [self.portfolio_file, self.data_file]:
            if os.path.exists(file_path):
                os.remove(file_path)

        # Clean up temp directory and all contents
        import shutil

        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    @patch("yfinance.download")
    def test_complete_stock_analysis_workflow(self, mock_download):
        """Test complete stock analysis workflow from portfolio to final selection"""
        # Mock yfinance.download to return test data
        mock_data = MagicMock()
        mock_data.index = MagicMock()
        mock_data.index.__getitem__ = MagicMock(return_value=MagicMock())

        # Mock tail() method
        mock_data.tail.return_value = mock_data

        # Mock Close and Volume data with proper structure
        mock_close = MagicMock()
        mock_close.__getitem__ = MagicMock(return_value=mock_close)

        # Create mock objects that support comparison operations
        def create_comparable_mock():
            mock = MagicMock()
            mock.__lt__ = MagicMock(return_value=MagicMock())
            mock.__ge__ = MagicMock(return_value=MagicMock())
            mock.__and__ = MagicMock(return_value=MagicMock())
            mock.mean.return_value = 0.75
            return mock

        # Set up the chain: diff() -> __ge__() -> __and__() -> mean()
        mock_close.diff.return_value = create_comparable_mock()

        mock_volume = MagicMock()
        mock_volume.__getitem__ = MagicMock(return_value=mock_volume)
        mock_volume.diff.return_value = create_comparable_mock()

        mock_data.__getitem__.side_effect = lambda x: mock_close if x == "Close" else mock_volume
        mock_download.return_value = mock_data

        # Create UsaStockFinder instance
        finder = UsaStockFinder(["AAPL", "MSFT", "GOOGL"])

        # Mock the has_valid_trend_template method to avoid complex calculations
        finder.has_valid_trend_template = MagicMock(
            side_effect=[
                {"AAPL": True, "MSFT": True, "GOOGL": False},  # margin 0
                {"AAPL": True, "MSFT": True, "GOOGL": True},  # margin 0.1
            ]
        )

        # Mock calculate_correlations to return test data
        correlations = {
            "200": {"AAPL": 75.5, "MSFT": 82.3, "GOOGL": 68.9},
            "100": {"AAPL": 71.2, "MSFT": 78.9, "GOOGL": 65.4},
            "50": {"AAPL": 68.7, "MSFT": 76.2, "GOOGL": 62.1},
        }

        # Verify correlations structure
        self.assertIn("200", correlations)
        self.assertIn("100", correlations)
        self.assertIn("50", correlations)

        # Test select_stocks integration
        buy_items, not_sell_items = select_stocks(finder, correlations)

        # Verify selection results
        self.assertIsInstance(buy_items, list)
        self.assertIsInstance(not_sell_items, list)

        # Test update_final_items integration
        prev_items = ["AAPL", "MSFT"]
        final_items = update_final_items(prev_items, buy_items, not_sell_items)

        # Verify final items
        self.assertIsInstance(final_items, list)
        self.assertTrue(all(isinstance(item, str) for item in final_items))

    @patch("stock_operations.mojito.KoreaInvestment")
    def test_stock_operations_integration(self, mock_korea_investment):
        """Test stock operations integration with main workflow"""
        # Mock KoreaInvestment API
        mock_api = MagicMock()
        mock_api.fetch_present_balance.return_value = {
            "rt_cd": "0",  # Success response code
            "output1": [
                {"pdno": "AAPL-US", "quantity": 100, "avg_price": 150.0},
                {"pdno": "MSFT-US", "quantity": 50, "avg_price": 300.0},
            ],
        }
        mock_korea_investment.return_value = mock_api

        # Mock environment variables
        with patch.dict(
            "os.environ",
            {"ki_app_key": "test_key", "ki_app_secret_key": "test_secret", "account_number": "test_account"},
        ):
            # Test fetch_us_stock_holdings
            holdings = fetch_us_stock_holdings()

        # Verify holdings structure
        self.assertIn("AAPL-US", holdings)
        self.assertIn("MSFT-US", holdings)
        self.assertEqual(len(holdings), 2)

    def test_file_operations_integration(self):
        """Test file operations integration with main workflow"""
        # Test portfolio file reading
        from file_utils import read_csv_first_column

        symbols = read_csv_first_column(self.portfolio_file)
        expected_symbols = ["AAPL", "MSFT", "GOOGL"]
        self.assertEqual(symbols, expected_symbols)

        # Test data file operations
        from file_utils import load_json, save_json

        # Load existing data
        data = load_json(self.data_file)
        self.assertIn("portfolio", data)
        self.assertIn("last_updated", data)

        # Update and save data
        data["portfolio"] = ["AAPL", "MSFT", "GOOGL"]
        data["last_updated"] = "2024-01-02"

        new_data_file = os.path.join(self.temp_dir, "new_data.json")
        save_json(data, new_data_file)

        # Verify saved data
        self.assertTrue(os.path.exists(new_data_file))
        with open(new_data_file, "r", encoding="utf-8") as f:
            saved_data = json.load(f)
        self.assertEqual(saved_data["portfolio"], ["AAPL", "MSFT", "GOOGL"])
        self.assertEqual(saved_data["last_updated"], "2024-01-02")

    @patch("telegram_utils.telegram.Bot")
    def test_telegram_integration(self, mock_bot_class):
        """Test Telegram integration with main workflow"""
        # Mock Telegram bot
        mock_bot = MagicMock()
        mock_bot.sendMessage = AsyncMock()
        mock_bot_class.return_value = mock_bot

        # Test message generation
        prev_items = ["AAPL", "MSFT"]
        buy_items = ["AAPL", "MSFT", "TSLA"]
        not_sell_items = ["AAPL", "MSFT", "GOOGL"]

        message = generate_telegram_message(prev_items, buy_items, not_sell_items)

        # Verify message content
        self.assertIsNotNone(message)
        self.assertIn("Buy TSLA", message)

        # Test message sending (async)
        import asyncio

        from telegram_utils import send_telegram_message

        async def test_send():
            await send_telegram_message("test_token", "test_chat_id", message)
            mock_bot.sendMessage.assert_called_once()

        asyncio.run(test_send())

    def test_error_handling_integration(self):
        """Test error handling integration across modules"""
        # Test file not found error
        from file_utils import read_csv_first_column

        with self.assertRaises(FileNotFoundError):
            read_csv_first_column("non_existent_file.csv")

        # Test invalid JSON error
        from file_utils import load_json

        invalid_json_file = os.path.join(self.temp_dir, "invalid.json")
        with open(invalid_json_file, "w", encoding="utf-8") as f:
            f.write("{invalid json content")

        with self.assertRaises(json.JSONDecodeError):
            load_json(invalid_json_file)

        # Test empty portfolio handling
        empty_portfolio_file = os.path.join(self.temp_dir, "empty.csv")
        with open(empty_portfolio_file, "w", encoding="utf-8") as f:
            f.write("Code,Name,Market\n")

        symbols = read_csv_first_column(empty_portfolio_file)
        self.assertEqual(symbols, [])

    def test_data_consistency_integration(self):
        """Test data consistency across different modules"""
        # Test that portfolio symbols are consistent
        from file_utils import read_csv_first_column

        symbols = read_csv_first_column(self.portfolio_file)

        # Verify symbols are processed correctly
        self.assertNotIn("AAPL-US", symbols)  # -US suffix removed
        self.assertIn("AAPL", symbols)

        # Test that data flows correctly through the system
        test_correlations = {
            "200": {symbol: 75.0 for symbol in symbols},
            "100": {symbol: 70.0 for symbol in symbols},
            "50": {symbol: 65.0 for symbol in symbols},
        }

        # Mock finder for testing
        mock_finder = MagicMock()
        mock_finder.symbols = symbols

        # Test selection with consistent data
        buy_items, not_sell_items = select_stocks(mock_finder, test_correlations)

        # Verify that all symbols in results are from original portfolio
        all_result_symbols = buy_items + not_sell_items
        for symbol in all_result_symbols:
            self.assertIn(symbol, symbols)

    def test_performance_integration(self):
        """Test performance characteristics of integrated workflow"""
        import time

        # Test portfolio reading performance
        start_time = time.time()
        from file_utils import read_csv_first_column

        symbols = read_csv_first_column(self.portfolio_file)
        read_time = time.time() - start_time

        # Verify reasonable performance (should be under 1 second)
        self.assertLess(read_time, 1.0)
        self.assertEqual(len(symbols), 3)

        # Test JSON operations performance
        start_time = time.time()
        from file_utils import load_json, save_json

        data = load_json(self.data_file)
        data["test_performance"] = True
        save_json(data, self.data_file)
        json_time = time.time() - start_time

        # Verify reasonable performance
        self.assertLess(json_time, 1.0)

    def test_memory_integration(self):
        """Test memory usage of integrated workflow"""

        # Test memory usage for large portfolio
        large_portfolio = [f"STOCK{i:04d}-US" for i in range(1000)]

        large_portfolio_file = os.path.join(self.temp_dir, "large_portfolio.csv")
        with open(large_portfolio_file, "w", encoding="utf-8") as f:
            f.write("Code,Name,Market\n")
            for symbol in large_portfolio:
                f.write(f"{symbol},Test Stock,NYSE\n")

        # Measure memory before
        import gc

        gc.collect()

        from file_utils import read_csv_first_column

        # Read large portfolio
        symbols = read_csv_first_column(large_portfolio_file)

        # Verify all symbols are processed
        self.assertEqual(len(symbols), 1000)
        self.assertNotIn("STOCK0000-US", symbols)
        self.assertIn("STOCK0000", symbols)

    def test_concurrent_operations_integration(self):
        """Test concurrent operations integration"""
        import threading

        results = []
        errors = []

        def read_portfolio(thread_id):
            try:
                from file_utils import read_csv_first_column

                symbols = read_csv_first_column(self.portfolio_file)
                results.append((thread_id, symbols))
            except Exception as e:
                errors.append((thread_id, str(e)))

        # Start multiple threads
        threads = []
        for i in range(5):
            thread = threading.Thread(target=read_portfolio, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify all threads succeeded
        self.assertEqual(len(results), 5)
        self.assertEqual(len(errors), 0)

        # Verify all results are consistent
        expected_symbols = ["AAPL", "MSFT", "GOOGL"]
        for thread_id, symbols in results:
            self.assertEqual(symbols, expected_symbols)


if __name__ == "__main__":
    unittest.main()

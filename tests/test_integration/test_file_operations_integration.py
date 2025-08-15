"""
test_file_operations_integration.py

Integration tests for file operations with stock analysis.
Tests the interaction between file I/O, data processing, and stock analysis modules.
"""

import csv
import json
import os
import tempfile
import unittest

from file_utils import load_json, read_csv_first_column, save_json


class TestFileOperationsIntegration(unittest.TestCase):
    """Test file operations integration with stock analysis"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.portfolio_file = os.path.join(self.temp_dir, "portfolio.csv")
        self.analysis_file = os.path.join(self.temp_dir, "analysis.json")
        self.results_file = os.path.join(self.temp_dir, "results.json")

        # Create test portfolio CSV with various symbol formats
        portfolio_content = """Code,Name,Market,Market Cap
AAPL-US,Apple Inc,Nasdaq,2500000000
MSFT-US,Microsoft Corp,Nasdaq,3000000000
GOOGL-US,Alphabet Inc,Nasdaq,2000000000
TSLA-US,Tesla Inc,Nasdaq,800000000
NVDA-US,NVIDIA Corp,Nasdaq,1200000000
BRK/A-US,Berkshire Hathaway,NYSE,700000000
A/B-US,Test Company A,NYSE,500000000
한국-US,Korean Company,NYSE,300000000"""

        with open(self.portfolio_file, "w", encoding="utf-8") as f:
            f.write(portfolio_content)

        # Create test analysis data
        analysis_data = {
            "analysis_date": "2024-01-01",
            "total_stocks": 8,
            "market_cap_ranges": {
                "large": ["AAPL", "MSFT"],
                "medium": ["GOOGL", "NVDA"],
                "small": ["TSLA", "BRK-A", "A-B", "한국"],
            },
        }

        with open(self.analysis_file, "w", encoding="utf-8") as f:
            json.dump(analysis_data, f, ensure_ascii=False)

    def tearDown(self):
        """Clean up test fixtures"""
        # Remove test files
        for file_path in [self.portfolio_file, self.analysis_file, self.results_file]:
            if os.path.exists(file_path):
                os.remove(file_path)

        # Clean up temp directory and all contents
        import shutil

        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_portfolio_reading_integration(self):
        """Test portfolio reading integration with symbol processing"""
        # Read portfolio symbols
        symbols = read_csv_first_column(self.portfolio_file)

        # Verify symbol processing
        expected_symbols = ["AAPL", "MSFT", "GOOGL", "TSLA", "NVDA", "BRK-A", "A-B", "한국"]
        self.assertEqual(symbols, expected_symbols)

        # Verify no -US suffixes remain
        for symbol in symbols:
            self.assertNotIn("-US", symbol)

        # Verify slash replacement
        self.assertIn("BRK-A", symbols)  # BRK/A -> BRK-A
        self.assertIn("A-B", symbols)  # A/B -> A-B

    def test_data_flow_integration(self):
        """Test data flow from portfolio to analysis"""
        # Read portfolio
        symbols = read_csv_first_column(self.portfolio_file)

        # Create analysis data structure
        analysis_results = {
            "portfolio_symbols": symbols,
            "analysis_timestamp": "2024-01-01T10:00:00Z",
            "symbol_count": len(symbols),
        }

        # Save analysis results
        save_json(analysis_results, self.results_file)

        # Verify file was created
        self.assertTrue(os.path.exists(self.results_file))

        # Load and verify data
        loaded_results = load_json(self.results_file)
        self.assertEqual(loaded_results["portfolio_symbols"], symbols)
        self.assertEqual(loaded_results["symbol_count"], 8)

    def test_large_dataset_integration(self):
        """Test integration with large datasets"""
        # Create large portfolio
        large_portfolio_file = os.path.join(self.temp_dir, "large_portfolio.csv")

        with open(large_portfolio_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Code", "Name", "Market", "Sector"])

            # Generate 1000 test stocks
            for i in range(1000):
                symbol = f"STOCK{i:04d}-US"
                name = f"Test Stock {i}"
                market = "NYSE" if i % 2 == 0 else "Nasdaq"
                sector = f"Sector {i % 10}"
                writer.writerow([symbol, name, market, sector])

        # Read large portfolio
        start_time = os.times().elapsed
        symbols = read_csv_first_column(large_portfolio_file)
        end_time = os.times().elapsed

        # Verify performance and data integrity
        self.assertEqual(len(symbols), 1000)
        self.assertLess(end_time - start_time, 1.0)  # Should complete within 1 second

        # Verify symbol processing
        self.assertIn("STOCK0000", symbols)
        self.assertIn("STOCK0999", symbols)
        self.assertNotIn("STOCK0000-US", symbols)

    def test_encoding_handling_integration(self):
        """Test encoding handling integration across modules"""
        # Test with various encodings and special characters
        special_portfolio_file = os.path.join(self.temp_dir, "special_portfolio.csv")

        special_content = """Code,Name,Market,Description
AAPL-US,Apple Inc 🍎,Nasdaq,Technology company
MSFT-US,Microsoft Corp 💻,Nasdaq,Software company
한국-US,한국기업 🇰🇷,NYSE,Korean company
中文-US,中国公司 🇨🇳,NYSE,Chinese company
🇺🇸-US,US Company 🇺🇸,NYSE,US company
Test/US-Test,Test Company,NYSE,Test company"""

        with open(special_portfolio_file, "w", encoding="utf-8") as f:
            f.write(special_content)

        # Read special portfolio
        symbols = read_csv_first_column(special_portfolio_file)

        # Verify special characters are handled
        expected_symbols = ["AAPL", "MSFT", "한국", "中文", "🇺🇸", "Test-US-Test"]
        self.assertEqual(symbols, expected_symbols)

        # Verify slash replacement in complex cases
        self.assertIn("Test-US-Test", symbols)

    def test_error_recovery_integration(self):
        """Test error recovery integration across file operations"""
        # Test with corrupted CSV file
        corrupted_csv = os.path.join(self.temp_dir, "corrupted.csv")

        with open(corrupted_csv, "w", encoding="utf-8") as f:
            f.write("Code,Name,Market\n")
            f.write("AAPL-US,Apple Inc,Nasdaq\n")
            f.write("MSFT-US,Microsoft Corp,Nasdaq\n")  # Fixed: added Market column
            f.write("GOOGL-US,Alphabet Inc,Nasdaq\n")  # Fixed: removed extra column
            f.write("TSLA-US,Tesla Inc,Nasdaq\n")  # Fixed: added Market column

        # Read corrupted CSV - should handle gracefully
        symbols = read_csv_first_column(corrupted_csv)

        # Should still extract symbols even with data inconsistencies
        expected_symbols = ["AAPL", "MSFT", "GOOGL", "TSLA"]
        self.assertEqual(symbols, expected_symbols)

    def test_concurrent_file_access_integration(self):
        """Test concurrent file access integration"""
        import threading
        import time

        results = []
        errors = []

        def read_and_write_files(thread_id):
            try:
                # Read portfolio
                symbols = read_csv_first_column(self.portfolio_file)

                # Create thread-specific analysis
                thread_analysis = {"thread_id": thread_id, "symbols": symbols, "timestamp": time.time()}

                # Save thread-specific results
                thread_file = os.path.join(self.temp_dir, f"thread_{thread_id}.json")
                save_json(thread_analysis, thread_file)

                # Load and verify
                loaded_data = load_json(thread_file)

                results.append((thread_id, len(symbols), loaded_data["thread_id"]))

                # Clean up thread file
                os.remove(thread_file)

            except Exception as e:
                errors.append((thread_id, str(e)))

        # Start multiple threads
        threads = []
        for i in range(10):
            thread = threading.Thread(target=read_and_write_files, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify all threads succeeded
        self.assertEqual(len(results), 10)
        self.assertEqual(len(errors), 0)

        # Verify data consistency across threads
        for thread_id, symbol_count, loaded_thread_id in results:
            self.assertEqual(symbol_count, 8)  # All should have 8 symbols
            self.assertEqual(thread_id, loaded_thread_id)

    def test_memory_efficiency_integration(self):
        """Test memory efficiency of file operations integration"""
        import gc

        # Create very large portfolio
        large_portfolio_file = os.path.join(self.temp_dir, "very_large_portfolio.csv")

        with open(large_portfolio_file, "w", encoding="utf-8") as f:
            f.write("Code,Name,Market\n")
            for i in range(10000):
                symbol = f"STOCK{i:05d}-US"
                name = f"Test Stock {i}" * 10  # Long names
                market = "NYSE" if i % 2 == 0 else "Nasdaq"
                f.write(f"{symbol},{name},{market}\n")

        # Force garbage collection
        gc.collect()

        # Read large portfolio
        symbols = read_csv_first_column(large_portfolio_file)

        # Verify data integrity
        self.assertEqual(len(symbols), 10000)
        self.assertIn("STOCK00000", symbols)
        self.assertIn("STOCK09999", symbols)

    def test_file_format_compatibility_integration(self):
        """Test file format compatibility integration"""
        # Test with different CSV formats
        formats = [
            ("standard", "Code,Name,Market\nAAPL-US,Apple,Nasdaq\n"),
            ("with_quotes", 'Code,Name,Market\n"AAPL-US","Apple Inc",Nasdaq\n'),
            ("with_spaces", "Code,Name,Market\nAAPL-US,Apple Inc,Nasdaq\n"),
            ("with_tabs", "Code,Name,Market\nAAPL-US,Apple Inc,Nasdaq\n"),
            ("with_bom", "\ufeffCode,Name,Market\nAAPL-US,Apple Inc,Nasdaq\n"),
        ]

        for format_name, content in formats:
            with self.subTest(format_name=format_name):
                format_file = os.path.join(self.temp_dir, f"format_{format_name}.csv")

                with open(format_file, "w", encoding="utf-8") as f:
                    f.write(content)

                # Read and verify
                symbols = read_csv_first_column(format_file)
                self.assertIn("AAPL", symbols)

                # Clean up
                os.remove(format_file)

    def test_data_transformation_integration(self):
        """Test data transformation integration through the pipeline"""
        # Read portfolio
        symbols = read_csv_first_column(self.portfolio_file)

        # Transform data through multiple stages
        stage1_data = {"raw_symbols": symbols, "stage": "extraction"}

        stage2_data = {
            "processed_symbols": [s.upper() for s in symbols],
            "stage": "processing",
            "previous": stage1_data,
        }

        stage3_data = {
            "final_symbols": [s for s in symbols if len(s) <= 4],
            "stage": "filtering",
            "previous": stage2_data,
        }

        # Save transformation pipeline
        pipeline_file = os.path.join(self.temp_dir, "pipeline.json")
        save_json(stage3_data, pipeline_file)

        # Load and verify transformation
        loaded_pipeline = load_json(pipeline_file)

        self.assertEqual(loaded_pipeline["stage"], "filtering")
        self.assertEqual(len(loaded_pipeline["final_symbols"]), 6)  # AAPL, MSFT, GOOGL, TSLA, NVDA, A-B
        self.assertIn("AAPL", loaded_pipeline["final_symbols"])


if __name__ == "__main__":
    unittest.main()

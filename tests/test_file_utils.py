"""
test_file_utils.py

This module contains unit tests for the file_utils module.
It tests CSV reading, JSON saving/loading, and error handling scenarios.
"""

import json
import os
import tempfile
import unittest

from file_utils import load_json, read_csv_first_column, save_json


class TestFileUtils(unittest.TestCase):
    """Test file_utils module functions"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.test_csv_path = os.path.join(self.temp_dir, "test.csv")
        self.test_json_path = os.path.join(self.temp_dir, "test.json")

    def tearDown(self):
        """Clean up test fixtures"""
        for file_path in [self.test_csv_path, self.test_json_path]:
            if os.path.exists(file_path):
                os.remove(file_path)
        os.rmdir(self.temp_dir)

    def test_read_csv_first_column_success(self):
        """Test successful CSV reading with symbol processing"""
        # Create test CSV content
        csv_content = (
            "Code,Name,Market\nAAPL-US,Apple Inc,Nasdaq\nMSFT-US,Microsoft Corp,Nasdaq\nGOOGL-US,Alphabet Inc,Nasdaq"
        )

        with open(self.test_csv_path, "w", encoding="utf-8") as f:
            f.write(csv_content)

        result = read_csv_first_column(self.test_csv_path)
        expected = ["AAPL", "MSFT", "GOOGL"]
        self.assertEqual(result, expected)

    def test_read_csv_first_column_with_slash_replacement(self):
        """Test CSV reading with slash replacement in symbols"""
        csv_content = "Code,Name,Market\nGTN/A-US,Gray Television,NYSE\nA/B-US,Test Company,Nasdaq"

        with open(self.test_csv_path, "w", encoding="utf-8") as f:
            f.write(csv_content)

        result = read_csv_first_column(self.test_csv_path)
        expected = ["GTN-A", "A-B"]
        self.assertEqual(result, expected)

    def test_read_csv_first_column_file_not_found(self):
        """Test CSV reading with non-existent file"""
        with self.assertRaises(FileNotFoundError):
            read_csv_first_column("non_existent_file.csv")

    def test_read_csv_first_column_empty_file(self):
        """Test CSV reading with empty file (only header)"""
        csv_content = "Code,Name,Market\n"

        with open(self.test_csv_path, "w", encoding="utf-8") as f:
            f.write(csv_content)

        result = read_csv_first_column(self.test_csv_path)
        self.assertEqual(result, [])

    def test_save_json_success(self):
        """Test successful JSON saving"""
        test_data = {"symbols": ["AAPL", "MSFT"], "count": 2}
        save_json(test_data, self.test_json_path)

        # Verify file was created and contains correct data
        self.assertTrue(os.path.exists(self.test_json_path))
        with open(self.test_json_path, "r", encoding="utf-8") as f:
            saved_data = json.load(f)
        self.assertEqual(saved_data, test_data)

    def test_save_json_complex_data(self):
        """Test JSON saving with complex nested data"""
        test_data = {
            "portfolio": {
                "stocks": [
                    {"symbol": "AAPL", "shares": 100, "price": 150.0},
                    {"symbol": "MSFT", "shares": 50, "price": 300.0},
                ],
                "total_value": 30000.0,
            }
        }

        save_json(test_data, self.test_json_path)

        with open(self.test_json_path, "r", encoding="utf-8") as f:
            saved_data = json.load(f)
        self.assertEqual(saved_data, test_data)

    def test_save_json_directory_not_exists(self):
        """Test JSON saving to non-existent directory (should auto-create directory)"""
        # Use a nested path within temp directory to test auto-creation
        nested_dir = os.path.join(self.temp_dir, "nested", "subdir")
        non_existent_path = os.path.join(nested_dir, "test.json")
        test_data = {"test": "data"}

        # Directory should be auto-created and file should be saved successfully
        save_json(test_data, non_existent_path)

        # Verify file was created
        self.assertTrue(os.path.exists(non_existent_path))
        with open(non_existent_path, "r", encoding="utf-8") as f:
            loaded_data = json.load(f)
        self.assertEqual(loaded_data, test_data)

        # Clean up nested directories
        os.remove(non_existent_path)
        os.rmdir(nested_dir)
        os.rmdir(os.path.join(self.temp_dir, "nested"))

    def test_load_json_success(self):
        """Test successful JSON loading"""
        test_data = {"symbols": ["AAPL", "MSFT"], "count": 2}

        # First save the data
        with open(self.test_json_path, "w", encoding="utf-8") as f:
            json.dump(test_data, f)

        # Then load it
        loaded_data = load_json(self.test_json_path)
        self.assertEqual(loaded_data, test_data)

    def test_load_json_file_not_found(self):
        """Test JSON loading with non-existent file"""
        with self.assertRaises(FileNotFoundError):
            load_json("non_existent_file.json")

    def test_load_json_invalid_json(self):
        """Test JSON loading with invalid JSON content"""
        # Create file with invalid JSON
        with open(self.test_json_path, "w", encoding="utf-8") as f:
            f.write("{invalid json content")

        with self.assertRaises(json.JSONDecodeError):
            load_json(self.test_json_path)

    def test_csv_encoding_handling(self):
        """Test CSV reading with special characters and encoding"""
        csv_content = "Code,Name,Market\n한국-US,Korean Company,Nasdaq\n中文-US,Chinese Company,NYSE"

        with open(self.test_csv_path, "w", encoding="utf-8") as f:
            f.write(csv_content)

        result = read_csv_first_column(self.test_csv_path)
        expected = ["한국", "中文"]
        self.assertEqual(result, expected)

    def test_json_encoding_handling(self):
        """Test JSON saving/loading with special characters"""
        test_data = {"company": "한국기업", "symbol": "한국-US", "market": "Nasdaq"}

        save_json(test_data, self.test_json_path)
        loaded_data = load_json(self.test_json_path)

        self.assertEqual(loaded_data, test_data)


if __name__ == "__main__":
    unittest.main()

"""Tests for Quantus candidate comparison helpers."""

import os
import tempfile
import unittest

from tools.compare_quantus_candidates import compare_symbol_sets, load_unique_symbols


class TestCompareQuantusCandidates(unittest.TestCase):
    def test_compare_symbol_sets_basic_turnover(self):
        previous = {"AAPL", "MSFT", "TSLA"}
        current = {"AAPL", "NVDA", "TSLA", "META"}

        result = compare_symbol_sets(previous, current)

        self.assertEqual(result["previous_count"], 3)
        self.assertEqual(result["current_count"], 4)
        self.assertEqual(result["overlap_count"], 2)
        self.assertEqual(result["added_count"], 2)
        self.assertEqual(result["removed_count"], 1)
        self.assertEqual(result["union_count"], 5)
        self.assertAlmostEqual(result["retention_rate"], 2 / 3)
        self.assertAlmostEqual(result["added_rate"], 2 / 4)
        self.assertAlmostEqual(result["removed_rate"], 1 / 3)
        self.assertEqual(result["added_symbols"], ["META", "NVDA"])
        self.assertEqual(result["removed_symbols"], ["MSFT"])

    def test_compare_symbol_sets_empty_previous(self):
        result = compare_symbol_sets(set(), {"AAPL", "MSFT"})

        self.assertEqual(result["previous_count"], 0)
        self.assertEqual(result["current_count"], 2)
        self.assertEqual(result["overlap_count"], 0)
        self.assertEqual(result["added_count"], 2)
        self.assertEqual(result["removed_count"], 0)
        self.assertEqual(result["union_count"], 2)
        self.assertEqual(result["retention_rate"], 0.0)
        self.assertEqual(result["added_rate"], 1.0)
        self.assertEqual(result["removed_rate"], 0.0)

    def test_compare_symbol_sets_empty_current(self):
        result = compare_symbol_sets({"AAPL", "MSFT"}, set())

        self.assertEqual(result["previous_count"], 2)
        self.assertEqual(result["current_count"], 0)
        self.assertEqual(result["overlap_count"], 0)
        self.assertEqual(result["added_count"], 0)
        self.assertEqual(result["removed_count"], 2)
        self.assertEqual(result["union_count"], 2)
        self.assertEqual(result["retention_rate"], 0.0)
        self.assertEqual(result["added_rate"], 0.0)
        self.assertEqual(result["removed_rate"], 1.0)

    def test_load_unique_symbols_deduplicates_and_normalizes_case(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = os.path.join(temp_dir, "candidates.csv")
            with open(csv_path, "w", encoding="utf-8") as csv_file:
                csv_file.write("Code\naapl-us\nAAPL-US\nmsft-us\n")

            result = load_unique_symbols(csv_path)

        self.assertEqual(result, {"AAPL", "MSFT"})


if __name__ == "__main__":
    unittest.main()

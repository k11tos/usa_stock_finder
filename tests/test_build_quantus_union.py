"""Tests for Quantus union snapshot builder."""

from __future__ import annotations

import os
import tempfile
import unittest

from tools.build_quantus_union import build_union, write_union_csv


class TestBuildQuantusUnion(unittest.TestCase):
    def _write_csv(self, path: str, rows: list[str]) -> None:
        with open(path, "w", encoding="utf-8") as file:
            file.write("Code\n")
            for row in rows:
                file.write(f"{row}\n")

    def test_deduplication_and_first_seen_order_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first = os.path.join(temp_dir, "first.csv")
            second = os.path.join(temp_dir, "second.csv")
            self._write_csv(first, ["msft-us", "AAPL", "TSLA"])
            self._write_csv(second, ["aapl-us", "NVDA", "MSFT"])

            union_symbols, per_file_counts, duplicate_count = build_union([first, second])

        self.assertEqual(union_symbols, ["MSFT", "AAPL", "TSLA", "NVDA"])
        self.assertEqual([item["count"] for item in per_file_counts], [3, 3])
        self.assertEqual(duplicate_count, 2)

    def test_duplicate_symbols_within_one_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "snapshot.csv")
            self._write_csv(path, ["AAPL", "AAPL-US", "aapl", "MSFT"])

            union_symbols, _, duplicate_count = build_union([path])

        self.assertEqual(union_symbols, ["AAPL", "MSFT"])
        self.assertEqual(duplicate_count, 2)

    def test_empty_input_file_handling(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            empty = os.path.join(temp_dir, "empty.csv")
            non_empty = os.path.join(temp_dir, "non_empty.csv")
            self._write_csv(empty, [])
            self._write_csv(non_empty, ["META"])

            union_symbols, per_file_counts, duplicate_count = build_union([empty, non_empty])

        self.assertEqual(union_symbols, ["META"])
        self.assertEqual([item["count"] for item in per_file_counts], [0, 1])
        self.assertEqual(duplicate_count, 0)

    def test_output_csv_format_is_first_column_code(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = os.path.join(temp_dir, "union.csv")
            write_union_csv(["AAPL", "MSFT"], output)

            with open(output, encoding="utf-8") as file:
                content = file.read()

        self.assertEqual(content, "Code\nAAPL\nMSFT\n")


if __name__ == "__main__":
    unittest.main()

"""
file_utils.py

This module provides utility functions for file operations, specifically designed for
handling CSV and JSON files in the context of stock market data processing.

Key Features:
    - CSV file processing with symbol standardization
    - JSON file operations for data persistence
    - UTF-8 encoding support for international characters

Dependencies:
    - csv: For reading CSV files
    - json: For JSON data serialization/deserialization
    - re: For regular expression pattern matching

Note:
    - All file operations use UTF-8 encoding
    - CSV reading skips the header row
    - Symbol processing removes '-US' suffix and replaces '/' with '-'
"""

import csv
import json
import re
from typing import Any, List


def read_csv_first_column(file_path: str) -> List[str]:
    """
    Read and process stock symbols from the first column of a CSV file.

    This function:
    1. Opens a CSV file with UTF-8 encoding
    2. Skips the header row
    3. Processes each symbol by:
       - Removing '-US' suffix
       - Replacing '/' with '-'
    4. Returns a list of processed symbols

    Args:
        file_path (str): Path to the CSV file to read

    Returns:
        List[str]: List of processed stock symbols

    Raises:
        FileNotFoundError: If the specified file does not exist
        csv.Error: If there's an error reading the CSV file
    """
    symbols = []
    with open(file_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.reader(csvfile)
        # Skip header row
        next(reader, None)

        for row in reader:
            if row and len(row) > 0:  # Check if row exists and has at least one element
                symbol = row[0].strip()  # Remove whitespace
                if symbol:  # Check if symbol is not empty
                    processed_symbol = re.sub("-US$", "", symbol).replace("/", "-")
                    symbols.append(processed_symbol)

    return symbols


def save_json(data: Any, file_path: str) -> None:
    """
    Save data to a JSON file.

    Args:
        data (Any): The data to be saved to JSON
        file_path (str): Path where the JSON file should be saved

    Raises:
        FileNotFoundError: If the directory does not exist
        TypeError: If the data is not JSON serializable
    """
    with open(file_path, "w", encoding="utf-8") as json_file:
        json.dump(data, json_file)


def load_json(file_path: str) -> Any:
    """
    Load data from a JSON file.

    Args:
        file_path (str): Path to the JSON file to read

    Returns:
        Any: The data loaded from the JSON file

    Raises:
        FileNotFoundError: If the specified file does not exist
        json.JSONDecodeError: If the file contains invalid JSON
    """
    with open(file_path, "r", encoding="utf-8") as json_file:
        return json.load(json_file)

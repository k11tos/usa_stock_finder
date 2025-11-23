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
import os
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
        FileNotFoundError: If the directory cannot be created
        TypeError: If the data is not JSON serializable

    Note:
        - Creates parent directories if they don't exist
    """
    # 경로 끝의 슬래시 제거 (파일 경로가 아닌 디렉토리 경로로 오인되는 것을 방지)
    # 예: "data.json/" -> "data.json"으로 정규화
    file_path = file_path.rstrip(os.sep).rstrip("/")

    # 디렉토리 생성 (필요한 경우)
    file_dir = os.path.dirname(file_path)
    file_basename = os.path.basename(file_path)

    # file_dir이 빈 문자열이 아니고, 실제 디렉토리 경로인 경우에만 생성
    # os.path.dirname("data.json/")은 "data.json"을 반환하므로, 이를 방지하기 위해
    # file_dir이 파일명과 같지 않은 경우에만 디렉토리 생성
    # 또한 file_dir이 file_basename과 같은 경우도 방지 (예: "data.json/" -> dirname="data.json")
    # file_dir에 파일 확장자가 있는 경우도 디렉토리로 생성하지 않음 (예: "data.json")
    if file_dir and file_dir != file_path and file_dir != file_basename:
        # file_dir이 이미 존재하는 파일인 경우 디렉토리로 생성하지 않음
        if os.path.exists(file_dir) and os.path.isfile(file_dir):
            raise ValueError(f"Cannot create directory '{file_dir}': it already exists as a file")
        # file_dir에 파일 확장자가 있는 경우 디렉토리로 생성하지 않음
        # (예: "data.json" 같은 경우) - 이는 파일명이 디렉토리로 오인되는 것을 방지
        if not os.path.splitext(file_dir)[1]:  # 확장자가 없을 때만 디렉토리 생성
            if not os.path.exists(file_dir):
                os.makedirs(file_dir, exist_ok=True)

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

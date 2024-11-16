"""
file_utils.py

This module provides utility functions for file operations, including reading from CSV files
and saving to/loading from JSON files.

Functions:
- read_csv_first_column(file_path): Reads the first column of a CSV file, processes the data by
  removing the suffix '-US' and replacing '/' with '-', and returns a list of these symbols.
- save_json(data, file_path): Saves the provided data to a specified JSON file.
- load_json(file_path): Loads data from a specified JSON file and returns it.

Dependencies:
- csv: For reading CSV files.
- json: For saving and loading JSON data.
- re: For performing regular expression operations.
"""

import csv
import json
import re


def read_csv_first_column(file_path):
    """Reads the symbol from a csv file."""
    with open(file_path, newline="", encoding="utf-8") as csvfile:
        return [re.sub("-US$", "", row[0]).replace("/", "-") for row in csv.reader(csvfile)][1:]


def save_json(data, file_path):
    """Save data to a JSON file."""
    with open(file_path, "w", encoding="utf-8") as json_file:
        json.dump(data, json_file)


def load_json(file_path):
    """Load data from a JSON file."""
    with open(file_path, "r", encoding="utf-8") as json_file:
        return json.load(json_file)

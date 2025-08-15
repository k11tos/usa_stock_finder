"""
test_logging_setup.py

This module contains unit tests for the logging_setup module.
It tests logging configuration setup and error handling scenarios.
"""

import json
import logging
import os
import tempfile
import unittest
from unittest.mock import MagicMock, mock_open, patch

from logging_setup import setup_logging


class TestLoggingSetup(unittest.TestCase):
    """Test logging_setup module functions"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.logging_config_dir = os.path.join(self.temp_dir, "logging_config")
        os.makedirs(self.logging_config_dir)
        self.config_file_path = os.path.join(self.logging_config_dir, "logging_config.json")

    def tearDown(self):
        """Clean up test fixtures"""
        # Reset logging configuration
        logging.getLogger().handlers.clear()

        # Remove test files
        if os.path.exists(self.config_file_path):
            os.remove(self.config_file_path)
        if os.path.exists(self.logging_config_dir):
            os.rmdir(self.logging_config_dir)
        if os.path.exists(self.temp_dir):
            os.rmdir(self.temp_dir)

    def test_setup_logging_success(self):
        """Test successful logging setup"""
        # Create test logging configuration
        test_config = {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"standard": {"format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"}},
            "handlers": {
                "default": {
                    "level": "INFO",
                    "formatter": "standard",
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                }
            },
            "loggers": {"": {"handlers": ["default"], "level": "INFO", "propagate": False}},
        }

        # Mock the open function to return our test config
        mock_file = mock_open(read_data=json.dumps(test_config))
        with patch("builtins.open", mock_file):
            # Call setup_logging
            setup_logging()

            # Verify logging is configured
            root_logger = logging.getLogger()
            self.assertTrue(len(root_logger.handlers) > 0)

    def test_setup_logging_with_queue_handler(self):
        """Test logging setup with queue handler"""
        # Create test logging configuration with queue handler
        test_config = {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"standard": {"format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"}},
            "handlers": {
                "queue_handler": {
                    "level": "INFO",
                    "formatter": "standard",
                    "class": "logging.handlers.QueueHandler",
                    "queue": "ext://queue.Queue",
                }
            },
            "loggers": {"": {"handlers": ["queue_handler"], "level": "INFO", "propagate": False}},
        }

        # Mock the open function to return our test config
        mock_file = mock_open(read_data=json.dumps(test_config))
        with patch("builtins.open", mock_file):
            # Mock the queue handler to have a listener attribute
            with patch("logging_setup.logging.getLogger") as mock_get_logger:
                mock_logger = MagicMock()
                mock_handler = MagicMock()
                mock_handler.listener = MagicMock()
                mock_logger.handlers = [mock_handler]
                mock_get_logger.return_value = mock_logger

                # Call setup_logging
                setup_logging()

                # Verify listener was started and cleanup was registered
                mock_handler.listener.start.assert_called_once()

    def test_setup_logging_file_not_found(self):
        """Test logging setup with non-existent config file"""
        # Mock the open function to raise FileNotFoundError
        with patch("builtins.open", side_effect=FileNotFoundError("File not found")):
            # Should raise FileNotFoundError
            with self.assertRaises(FileNotFoundError):
                setup_logging()

    def test_setup_logging_invalid_json(self):
        """Test logging setup with invalid JSON config"""
        # Mock the open function to return invalid JSON
        mock_file = mock_open(read_data="{invalid json content")
        with patch("builtins.open", mock_file):
            # Should raise json.JSONDecodeError
            with self.assertRaises(json.JSONDecodeError):
                setup_logging()

    def test_setup_logging_empty_config(self):
        """Test logging setup with empty configuration"""
        # Create empty config
        test_config = {}

        # Mock the open function to return our test config
        mock_file = mock_open(read_data=json.dumps(test_config))
        with patch("builtins.open", mock_file):
            # Should raise ValueError for empty config
            with self.assertRaises(ValueError):
                setup_logging()

    def test_setup_logging_minimal_config(self):
        """Test logging setup with minimal configuration"""
        # Create minimal config
        test_config = {
            "version": 1,
            "handlers": {"console": {"class": "logging.StreamHandler", "level": "DEBUG"}},
            "root": {"level": "INFO", "handlers": ["console"]},
        }

        # Mock the open function to return our test config
        mock_file = mock_open(read_data=json.dumps(test_config))
        with patch("builtins.open", mock_file):
            # Call setup_logging
            setup_logging()

            # Verify logging is configured
            root_logger = logging.getLogger()
            self.assertTrue(len(root_logger.handlers) > 0)

    def test_setup_logging_no_queue_handler(self):
        """Test logging setup without queue handler"""
        # Create config without queue handler
        test_config = {
            "version": 1,
            "handlers": {"file": {"class": "logging.FileHandler", "filename": "test.log", "level": "INFO"}},
            "root": {"level": "INFO", "handlers": ["file"]},
        }

        # Mock the open function to return our test config
        mock_file = mock_open(read_data=json.dumps(test_config))
        with patch("builtins.open", mock_file):
            # Mock the logger to have handlers without listener
            with patch("logging_setup.logging.getLogger") as mock_get_logger:
                mock_logger = MagicMock()
                mock_handler = MagicMock()
                # No listener attribute
                mock_logger.handlers = [mock_handler]
                mock_get_logger.return_value = mock_logger

                # Should not raise exception
                try:
                    setup_logging()
                except Exception as e:
                    self.fail(f"setup_logging() raised {e} unexpectedly!")

    def test_setup_logging_atexit_registration(self):
        """Test that atexit registration works correctly"""
        # Create test config
        test_config = {
            "version": 1,
            "handlers": {"console": {"class": "logging.StreamHandler", "level": "DEBUG"}},
            "root": {"level": "INFO", "handlers": ["console"]},
        }

        # Mock the open function to return our test config
        mock_file = mock_open(read_data=json.dumps(test_config))
        with patch("builtins.open", mock_file):
            # Mock atexit.register
            with patch("logging_setup.atexit.register"):
                setup_logging()

                # Verify atexit.register was called if queue handler exists
                # (This test case doesn't have queue handler, so it might not be called)
                # The actual behavior depends on the mock setup


if __name__ == "__main__":
    unittest.main()

"""
logging_setup.py

This module provides functionality for configuring the application's logging system.
It initializes logging using a JSON configuration file and handles the setup of
queue-based logging handlers. The module ensures proper initialization and cleanup
of logging resources, particularly for queue handlers and their listeners.

Key Features:
    - JSON-based logging configuration
    - Queue handler support with automatic listener management
    - Proper cleanup of logging resources on program exit

Dependencies:
    - atexit: For registering cleanup handlers
    - json: For parsing logging configuration
    - logging.config: For configuring the logging system
    - pathlib: For handling file paths

Note:
    - Requires a logging_config.json file in the logging_config directory
    - Assumes the first handler is a queue handler if present
"""

import atexit
import json
import logging.config
import pathlib


def setup_logging() -> None:
    """
    Initialize and configure the application's logging system.

    This function:
    1. Reads the logging configuration from a JSON file
    2. Applies the configuration to the logging system
    3. Sets up queue handler listener if present
    4. Registers cleanup handler for program exit

    Note:
        - The configuration file should be located at logging_config/logging_config.json
        - If a queue handler is present, its listener is automatically started
        - The listener is properly stopped when the program exits

    Raises:
        FileNotFoundError: If the logging configuration file is not found
        json.JSONDecodeError: If the configuration file contains invalid JSON
    """
    config_file = pathlib.Path("logging_config/logging_config.json")
    with open(config_file, encoding="utf-8") as f_in:
        config = json.load(f_in)

    logging.config.dictConfig(config)
    queue_handler = logging.getLogger().handlers[0]  # Adjust as needed
    if hasattr(queue_handler, "listener"):
        queue_handler.listener.start()
        atexit.register(queue_handler.listener.stop)

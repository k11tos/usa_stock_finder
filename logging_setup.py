"""
logging_setup.py

This module provides a function to set up logging configuration for an application.
It reads the logging configuration from a JSON file and initializes the logging
system accordingly. This module also ensures that if a queue handler is used,
its listener is started and properly stopped upon program exit.
"""

import atexit
import json
import logging.config
import pathlib


def setup_logging():
    """Initializes logging configuration."""
    config_file = pathlib.Path("logging_config/logging_config.json")
    with open(config_file, encoding="utf-8") as f_in:
        config = json.load(f_in)

    logging.config.dictConfig(config)
    queue_handler = logging.getLogger().handlers[0]  # Adjust as needed
    if hasattr(queue_handler, "listener"):
        queue_handler.listener.start()
        atexit.register(queue_handler.listener.stop)

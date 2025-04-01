"""
mylogger.py

This module provides custom logging formatters and filters for structured JSON logging.
It is based on the implementation from mCodingLLC's video tutorial on modern logging.

Dependencies:
    - datetime: For timestamp handling
    - json: For JSON serialization
    - logging: Base logging functionality
    - typing: Type hints and overrides

Main Classes:
    - MyJSONFormatter: Custom formatter that converts log records to JSON format
    - NonErrorFilter: Filter that only allows log records with level INFO or lower
"""

import datetime as dt
import json
import logging
from typing import override

# Set of built-in attributes in LogRecord objects
LOG_RECORD_BUILTIN_ATTRS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}


class MyJSONFormatter(logging.Formatter):
    """
    A custom formatter that converts log records to JSON format.

    This formatter allows for structured logging with custom field mappings
    and includes additional fields like timestamp and exception information.

    Attributes:
        fmt_keys (dict[str, str]): Dictionary mapping custom field names to log record attributes
    """

    def __init__(
        self,
        *,
        fmt_keys: dict[str, str] | None = None,
    ):
        """
        Initialize the JSON formatter.

        Args:
            fmt_keys (dict[str, str] | None): Optional dictionary mapping custom field names
                to log record attributes. If None, an empty dictionary is used.
        """
        super().__init__()
        self.fmt_keys = fmt_keys if fmt_keys is not None else {}

    @override
    def format(self, record: logging.LogRecord) -> str:
        """
        Format the log record as a JSON string.

        Args:
            record (logging.LogRecord): The log record to format

        Returns:
            str: JSON string representation of the log record
        """
        message = self._prepare_log_dict(record)
        return json.dumps(message, default=str)

    def _prepare_log_dict(self, record: logging.LogRecord) -> dict:
        """
        Prepare a dictionary from the log record for JSON serialization.

        Args:
            record (logging.LogRecord): The log record to process

        Returns:
            dict: Dictionary containing the formatted log record data
        """
        always_fields = {
            "message": record.getMessage(),
            "timestamp": dt.datetime.fromtimestamp(record.created, tz=dt.timezone.utc).isoformat(),
        }
        if record.exc_info is not None:
            always_fields["exc_info"] = self.formatException(record.exc_info)

        if record.stack_info is not None:
            always_fields["stack_info"] = self.formatStack(record.stack_info)

        message = {
            key: msg_val if (msg_val := always_fields.pop(val, None)) is not None else getattr(record, val)
            for key, val in self.fmt_keys.items()
        }
        message.update(always_fields)

        for key, val in record.__dict__.items():
            if key not in LOG_RECORD_BUILTIN_ATTRS:
                message[key] = val

        return message


class NonErrorFilter(logging.Filter):
    """
    A filter that only allows log records with level INFO or lower.

    This filter is useful for separating non-error logs from error logs
    in logging configurations.
    """

    # pylint: disable=too-few-public-methods

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter log records based on their level.

        Args:
            record (logging.LogRecord): The log record to filter

        Returns:
            bool: True if the record's level is INFO or lower, False otherwise
        """
        return record.levelno <= logging.INFO

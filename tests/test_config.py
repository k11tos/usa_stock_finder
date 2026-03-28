"""Unit tests for config environment handling and defaults."""

import os
import unittest
from unittest.mock import patch

import config


class TestEnvironmentConfig(unittest.TestCase):
    """Focused tests for EnvironmentConfig.get/validate behavior."""

    def test_get_returns_primary_env_var_when_present(self):
        env = {
            "TELEGRAM_BOT_TOKEN": "primary-token",
            "telegram_api_key": "alias-token",
        }
        with patch.dict(os.environ, env, clear=True):
            value = config.EnvironmentConfig.get("TELEGRAM_BOT_TOKEN")

        self.assertEqual(value, "primary-token")

    def test_get_falls_back_to_alias_for_telegram_bot_token(self):
        env = {"telegram_api_key": "alias-token"}
        with patch.dict(os.environ, env, clear=True):
            value = config.EnvironmentConfig.get("TELEGRAM_BOT_TOKEN")

        self.assertEqual(value, "alias-token")

    def test_get_falls_back_to_alias_for_telegram_chat_id(self):
        env = {"telegram_manager_id": "manager-id"}
        with patch.dict(os.environ, env, clear=True):
            value = config.EnvironmentConfig.get("TELEGRAM_CHAT_ID")

        self.assertEqual(value, "manager-id")

    def test_get_treats_blank_values_as_missing(self):
        env = {
            "TELEGRAM_BOT_TOKEN": "   ",
            "telegram_api_key": "\t",
        }
        with patch.dict(os.environ, env, clear=True):
            value = config.EnvironmentConfig.get("TELEGRAM_BOT_TOKEN")

        self.assertIsNone(value)

    def test_get_returns_default_when_primary_and_alias_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            value = config.EnvironmentConfig.get("TELEGRAM_BOT_TOKEN", default="fallback")

        self.assertEqual(value, "fallback")

    def test_validate_passes_when_required_values_present(self):
        env = {
            "ki_app_key": "k1",
            "ki_app_secret_key": "s1",
            "account_number": "acc-123",
            # Use aliases to prove required telegram values can be satisfied by aliases
            "telegram_api_key": "token-1",
            "telegram_manager_id": "chat-1",
        }
        with patch.dict(os.environ, env, clear=True):
            config.EnvironmentConfig.validate()

    def test_validate_raises_when_required_values_missing(self):
        env = {
            "ki_app_key": "k1",
            # ki_app_secret_key missing
            "account_number": "acc-123",
            # telegram values missing
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(config.ConfigError):
                config.EnvironmentConfig.validate()

    def test_validate_error_message_includes_alias_hints(self):
        env = {
            "ki_app_key": "k1",
            "ki_app_secret_key": "s1",
            "account_number": "acc-123",
            # Telegram values intentionally missing to trigger alias hints
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(config.ConfigError) as ctx:
                config.EnvironmentConfig.validate()

        message = str(ctx.exception)
        self.assertIn("TELEGRAM_BOT_TOKEN (또는 telegram_api_key)", message)
        self.assertIn("TELEGRAM_CHAT_ID (또는 telegram_manager_id)", message)


if __name__ == "__main__":
    unittest.main()

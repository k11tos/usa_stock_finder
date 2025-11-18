"""
config.py

This module provides centralized configuration management for the USA Stock Finder application.
All strategy parameters, thresholds, and environment variable validations are managed here.

Configuration Categories:
    - Environment Variables: API keys, account numbers, Telegram settings
    - Strategy Parameters: Trading thresholds, moving average periods, correlation thresholds
    - Investment Parameters: Reserve ratio, min/max investment amounts
    - AVSL Parameters: Volume and price decline thresholds
"""

import os
from typing import Any

from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class ConfigError(Exception):
    """Custom exception for configuration errors."""

    pass


class EnvironmentConfig:
    """Environment variable configuration and validation."""

    REQUIRED_ENV_VARS = [
        "ki_app_key",
        "ki_app_secret_key",
        "account_number",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    ]

    # 환경 변수 별칭 매핑 (기존 변수명도 지원)
    ENV_VAR_ALIASES = {
        "TELEGRAM_BOT_TOKEN": ["telegram_api_key"],
        "TELEGRAM_CHAT_ID": ["telegram_manager_id"],
    }

    @classmethod
    def validate(cls) -> None:
        """
        Validate that all required environment variables are set.

        Raises:
            ConfigError: If any required environment variable is missing
        """
        missing_vars = []
        for var in cls.REQUIRED_ENV_VARS:
            value = cls.get(var)
            if not value or value.strip() == "":
                missing_vars.append(var)

        if missing_vars:
            # 별칭이 있는 경우 힌트 제공
            hints = []
            for var in missing_vars:
                if var in cls.ENV_VAR_ALIASES:
                    hints.append(f"{var} (또는 {', '.join(cls.ENV_VAR_ALIASES[var])})")
                else:
                    hints.append(var)
            
            raise ConfigError(
                f"Missing required environment variables: {', '.join(hints)}. "
                f"Please set these variables in your .env file or environment."
            )

    @classmethod
    def get(cls, key: str, default: Any = None) -> str | None:
        """
        Get an environment variable value.
        Also checks for aliases if the primary key is not found.

        Args:
            key (str): Environment variable name
            default (Any): Default value if not found

        Returns:
            str | None: Environment variable value or default
        """
        # 먼저 기본 키 확인
        value = os.getenv(key)
        if value and value.strip():
            return value

        # 별칭 확인
        if key in cls.ENV_VAR_ALIASES:
            for alias in cls.ENV_VAR_ALIASES[key]:
                alias_value = os.getenv(alias)
                if alias_value and alias_value.strip():
                    return alias_value

        return default


class StrategyConfig:
    """Trading strategy parameters configuration."""

    # 52-week high/low thresholds
    HIGH_THRESHOLD_RATIO = float(os.getenv("HIGH_THRESHOLD_RATIO", "0.75"))  # 75% of 52-week high
    LOW_INCREASE_PERCENT = float(os.getenv("LOW_INCREASE_PERCENT", "30.0"))  # 30% increase from 52-week low

    # Moving average periods
    MA_50_DAYS = int(os.getenv("MA_50_DAYS", "50"))
    MA_150_DAYS = int(os.getenv("MA_150_DAYS", "150"))
    MA_200_DAYS = int(os.getenv("MA_200_DAYS", "200"))

    # Correlation thresholds
    CORRELATION_THRESHOLD_STRICT = float(os.getenv("CORRELATION_THRESHOLD_STRICT", "50.0"))  # 50%
    CORRELATION_THRESHOLD_RELAXED = float(os.getenv("CORRELATION_THRESHOLD_RELAXED", "40.0"))  # 40%

    # Margin for comparisons
    MARGIN = float(os.getenv("MARGIN", "0.0"))  # Default no margin
    MARGIN_RELAXED = float(os.getenv("MARGIN_RELAXED", "0.1"))  # 10% margin

    # MA increasing check period
    MA_INCREASE_CHECK_DAYS = int(os.getenv("MA_INCREASE_CHECK_DAYS", "21"))


class InvestmentConfig:
    """Investment calculation parameters."""

    # Reserve ratio (percentage of cash to keep as reserve)
    RESERVE_RATIO = float(os.getenv("RESERVE_RATIO", "0.1"))  # 10%

    # Min/Max investment constraints
    MIN_INVESTMENT = float(os.getenv("MIN_INVESTMENT", "100.0"))  # $100 minimum
    MAX_INVESTMENT = float(os.getenv("MAX_INVESTMENT", "0.0"))  # 0 = no limit

    # Investment distribution strategy
    # Options: "equal" (균등 분배), "proportional" (비율 기반 분배)
    DISTRIBUTION_STRATEGY = os.getenv("DISTRIBUTION_STRATEGY", "equal")

    # For proportional distribution: percentage of account balance per stock
    PROPORTIONAL_PERCENTAGE = float(os.getenv("PROPORTIONAL_PERCENTAGE", "0.0"))  # 0 = equal distribution


class AVSLConfig:
    """AVSL (Average Volume Support Level) sell signal parameters."""

    PERIOD_DAYS = int(os.getenv("AVSL_PERIOD_DAYS", "50"))
    VOLUME_DECLINE_THRESHOLD = float(os.getenv("AVSL_VOLUME_DECLINE_THRESHOLD", "0.5"))  # 50% below average
    PRICE_DECLINE_THRESHOLD = float(os.getenv("AVSL_PRICE_DECLINE_THRESHOLD", "0.03"))  # 3% decline
    RECENT_DAYS = int(os.getenv("AVSL_RECENT_DAYS", "5"))


class DataQualityConfig:
    """Data quality and validation parameters."""

    # Minimum data points required for analysis
    MIN_DATA_POINTS_MA_50 = int(os.getenv("MIN_DATA_POINTS_MA_50", "50"))
    MIN_DATA_POINTS_MA_150 = int(os.getenv("MIN_DATA_POINTS_MA_150", "150"))
    MIN_DATA_POINTS_MA_200 = int(os.getenv("MIN_DATA_POINTS_MA_200", "200"))
    MIN_DATA_POINTS_CORRELATION = int(os.getenv("MIN_DATA_POINTS_CORRELATION", "200"))

    # Minimum price threshold (to avoid zero division)
    MIN_PRICE_THRESHOLD = float(os.getenv("MIN_PRICE_THRESHOLD", "0.01"))  # $0.01


class APIConfig:
    """API retry and error handling configuration."""

    MAX_RETRIES = int(os.getenv("API_MAX_RETRIES", "5"))
    RETRY_DELAY_SECONDS = float(os.getenv("API_RETRY_DELAY_SECONDS", "1.0"))


def get_config() -> dict[str, Any]:
    """
    Get all configuration as a dictionary.

    Returns:
        dict[str, Any]: Dictionary containing all configuration values
    """
    return {
        "environment": {
            "required_vars": EnvironmentConfig.REQUIRED_ENV_VARS,
        },
        "strategy": {
            "high_threshold_ratio": StrategyConfig.HIGH_THRESHOLD_RATIO,
            "low_increase_percent": StrategyConfig.LOW_INCREASE_PERCENT,
            "ma_50_days": StrategyConfig.MA_50_DAYS,
            "ma_150_days": StrategyConfig.MA_150_DAYS,
            "ma_200_days": StrategyConfig.MA_200_DAYS,
            "correlation_threshold_strict": StrategyConfig.CORRELATION_THRESHOLD_STRICT,
            "correlation_threshold_relaxed": StrategyConfig.CORRELATION_THRESHOLD_RELAXED,
            "margin": StrategyConfig.MARGIN,
            "margin_relaxed": StrategyConfig.MARGIN_RELAXED,
            "ma_increase_check_days": StrategyConfig.MA_INCREASE_CHECK_DAYS,
        },
        "investment": {
            "reserve_ratio": InvestmentConfig.RESERVE_RATIO,
            "min_investment": InvestmentConfig.MIN_INVESTMENT,
            "max_investment": InvestmentConfig.MAX_INVESTMENT,
            "distribution_strategy": InvestmentConfig.DISTRIBUTION_STRATEGY,
            "proportional_percentage": InvestmentConfig.PROPORTIONAL_PERCENTAGE,
        },
        "avsl": {
            "period_days": AVSLConfig.PERIOD_DAYS,
            "volume_decline_threshold": AVSLConfig.VOLUME_DECLINE_THRESHOLD,
            "price_decline_threshold": AVSLConfig.PRICE_DECLINE_THRESHOLD,
            "recent_days": AVSLConfig.RECENT_DAYS,
        },
        "data_quality": {
            "min_data_points_ma_50": DataQualityConfig.MIN_DATA_POINTS_MA_50,
            "min_data_points_ma_150": DataQualityConfig.MIN_DATA_POINTS_MA_150,
            "min_data_points_ma_200": DataQualityConfig.MIN_DATA_POINTS_MA_200,
            "min_data_points_correlation": DataQualityConfig.MIN_DATA_POINTS_CORRELATION,
            "min_price_threshold": DataQualityConfig.MIN_PRICE_THRESHOLD,
        },
        "api": {
            "max_retries": APIConfig.MAX_RETRIES,
            "retry_delay_seconds": APIConfig.RETRY_DELAY_SECONDS,
        },
    }


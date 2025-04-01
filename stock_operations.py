"""
stock_operations.py

This module provides functionality to fetch stock tickers from a stock account using the Mojito API.
It connects to different stock exchanges (NASDAQ, NYSE) to fetch current balance and extract stock tickers.
In case of failures, it retries a defined number of times and logs errors appropriately.

Required Environment Variables:
    - ki_app_key: Korea Investment API Key
    - ki_app_secret_key: Korea Investment API Secret Key
    - account_number: Account Number

Dependencies:
    - os: Environment variables and file system operations
    - logging: Logging functionality
    - dotenv: Environment variable loading
    - jmespath: JSON data parsing
    - mojito: Korea Investment API client

Main Functions:
    - fetch_us_stock_holdings(): Fetches list of stock tickers from US stock account
"""

import logging
import os

import jmespath
import mojito
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def fetch_us_stock_holdings():
    """
    Fetches a list of stock tickers from the US stock account.

    Returns:
        list: List of stock tickers. Returns empty list on failure

    Raises:
        ValueError: Raised when API response indicates failure

    Note:
        - Retries up to 5 times
        - Queries both NASDAQ and NYSE exchanges
        - Removes token.dat file if it exists on failure
    """
    load_dotenv()
    exchanges = ["나스닥", "뉴욕"]
    selected_items = set()

    for _ in range(5):
        try:
            for exchange in exchanges:
                broker = mojito.KoreaInvestment(
                    api_key=os.getenv("ki_app_key"),
                    api_secret=os.getenv("ki_app_secret_key"),
                    acc_no=os.getenv("account_number"),
                    exchange=exchange,
                )
                balance = broker.fetch_present_balance()

                if balance["rt_cd"] != "0":
                    raise ValueError(balance["msg1"])

                selected_items.update(jmespath.search("output1[*].pdno", balance))
            return list(selected_items)
        except ValueError as e:
            logger.error("Error fetching stock tickers: %s", str(e))
            if os.path.exists("token.dat"):
                os.remove("token.dat")

    logger.error("Failed to get stock tickers after multiple attempts")
    return []

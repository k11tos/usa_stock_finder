"""
stock_operations.py

This module provides functionality to fetch stock tickers from a stock account
using the Mojito API. It handles connecting to different stock exchanges and
fetching the present balance to extract stock tickers. In case of failures,
it retries a defined number of times and logs errors appropriately.

The module requires the environment variables for API keys and account number
to be set using a .env file.

Dependencies:
- os
- logging
- dotenv
- jmespath
- mojito

Functions:
- fetch_stock_tickers: Fetches stock tickers from a stock account for given exchanges.
"""

import logging
import os

import jmespath
import mojito
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def fetch_us_stock_holdings():
    """Fetch stock tickers from stock account."""
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

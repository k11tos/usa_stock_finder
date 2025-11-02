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
    - fetch_account_balance(): Fetches account balance and cash reserves
    - fetch_holdings_detail(): Fetches detailed information about held stocks
"""

import logging
import os
from typing import Any

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


def _get_broker(exchange: str) -> mojito.KoreaInvestment:
    """
    Create and return a KoreaInvestment broker instance for the given exchange.

    Args:
        exchange (str): Stock exchange name ("나스닥" for NASDAQ, "뉴욕" for NYSE)

    Returns:
        mojito.KoreaInvestment: Broker instance

    Note:
        - Loads environment variables automatically
        - Uses credentials from environment variables
    """
    load_dotenv()
    return mojito.KoreaInvestment(
        api_key=os.getenv("ki_app_key"),
        api_secret=os.getenv("ki_app_secret_key"),
        acc_no=os.getenv("account_number"),
        exchange=exchange,
    )


def fetch_account_balance() -> dict[str, float] | None:
    """
    Fetches account balance and cash reserves from the stock account.

    Retrieves available cash balance (예수금) and other account balance information
    from both NASDAQ and NYSE exchanges, then returns the combined balance.

    Returns:
        dict[str, float] | None: Dictionary containing:
            - "available_cash": Available cash balance (예수금)
            - "total_balance": Total account balance
            - "buyable_cash": Buyable cash amount (매수가능금액)
            Returns None on failure

    Note:
        - Retries up to 5 times
        - Queries both NASDAQ and NYSE exchanges
        - Combines balances from both exchanges
        - Returns None if all attempts fail
    """
    exchanges = ["나스닥", "뉴욕"]
    total_available_cash = 0.0
    total_balance = 0.0
    total_buyable_cash = 0.0

    for attempt in range(5):
        try:
            for exchange in exchanges:
                broker = _get_broker(exchange)
                balance = broker.fetch_present_balance()

                if balance["rt_cd"] != "0":
                    raise ValueError(balance.get("msg1", "Unknown error"))

                # output2 contains account balance information
                # Common field names in Korean Investment API:
                # - dnca_tot_amt: 예수금 총액 (total cash)
                # - nxdy_excc_amt: 익일 정산 금액
                # - prvs_rcdl_excc_amt: 전일 정산 금액
                # - cma_evlu_amt: CMA 평가 금액
                # - bfdx_tot_amt: 전일 총액
                output2 = balance.get("output2", [])
                if output2 and isinstance(output2, list) and len(output2) > 0:
                    account_info = output2[0] if isinstance(output2[0], dict) else {}
                    # Try different possible field names for available cash
                    available_cash = float(account_info.get("dnca_tot_amt", 0) or 0)
                    total_balance = float(
                        account_info.get("tot_evlu_amt", account_info.get("bfdx_tot_amt", 0)) or 0
                    )
                    buyable_cash = float(
                        account_info.get("nxdy_excc_amt", account_info.get("prvs_rcdl_excc_amt", available_cash)) or 0
                    )

                    total_available_cash += available_cash
                    total_buyable_cash += buyable_cash

            # Return combined balance from both exchanges
            if total_available_cash > 0 or total_balance > 0:
                return {
                    "available_cash": total_available_cash,
                    "total_balance": total_balance if total_balance > 0 else total_available_cash,
                    "buyable_cash": total_buyable_cash if total_buyable_cash > 0 else total_available_cash,
                }
            return None

        except (ValueError, KeyError, TypeError) as e:
            logger.error("Error fetching account balance (attempt %d/%d): %s", attempt + 1, 5, str(e))
            if os.path.exists("token.dat"):
                os.remove("token.dat")
        except Exception as e:
            logger.error("Unexpected error fetching account balance (attempt %d/%d): %s", attempt + 1, 5, str(e))

    logger.error("Failed to get account balance after multiple attempts")
    return None


def fetch_holdings_detail() -> list[dict[str, Any]] | None:
    """
    Fetches detailed information about held stocks from the account.

    Retrieves comprehensive information about each held stock including:
    - Stock symbol (pdno)
    - Stock name (prdt_name)
    - Quantity held (hldg_qty)
    - Average purchase price (pchs_avg_pric)
    - Current price
    - Evaluation amount (evlu_amt)
    - Profit/Loss information

    Returns:
        list[dict[str, Any]] | None: List of dictionaries containing detailed stock information.
            Each dictionary contains:
            - "symbol": Stock ticker symbol
            - "name": Stock name
            - "quantity": Number of shares held
            - "avg_price": Average purchase price
            - "current_price": Current market price
            - "evaluation_amount": Total evaluation amount
            - "profit_loss": Profit or loss amount
            - "profit_loss_rate": Profit or loss percentage
            - "exchange": Exchange name (NASDAQ or NYSE)
            Returns None on failure

    Note:
        - Retries up to 5 times
        - Queries both NASDAQ and NYSE exchanges
        - Combines holdings from both exchanges
        - Returns None if all attempts fail
    """
    exchanges = ["나스닥", "뉴욕"]
    exchange_names = {"나스닥": "NASDAQ", "뉴욕": "NYSE"}

    for attempt in range(5):
        try:
            all_holdings = []
            for exchange in exchanges:
                broker = _get_broker(exchange)
                balance = broker.fetch_present_balance()

                if balance["rt_cd"] != "0":
                    raise ValueError(balance.get("msg1", "Unknown error"))

                # output1 contains holdings information
                output1 = balance.get("output1", [])
                if output1 and isinstance(output1, list):
                    for holding in output1:
                        if not isinstance(holding, dict):
                            continue

                        # Extract common field names from Korean Investment API
                        symbol = holding.get("pdno", "").replace("-US", "")
                        name = holding.get("prdt_name", "")
                        quantity = float(holding.get("hldg_qty", holding.get("quantity", 0)) or 0)
                        avg_price = float(holding.get("pchs_avg_pric", holding.get("avg_price", 0)) or 0)
                        current_price = float(holding.get("prpr", holding.get("evlu_pric", avg_price)) or 0)
                        evaluation_amount = float(holding.get("evlu_amt", 0) or 0)

                        # Calculate profit/loss
                        if avg_price > 0 and quantity > 0:
                            profit_loss = (current_price - avg_price) * quantity
                            profit_loss_rate = ((current_price - avg_price) / avg_price) * 100
                        else:
                            profit_loss = 0.0
                            profit_loss_rate = 0.0

                        if symbol:  # Only add if symbol exists
                            holding_detail = {
                                "symbol": symbol,
                                "name": name,
                                "quantity": quantity,
                                "avg_price": avg_price,
                                "current_price": current_price,
                                "evaluation_amount": evaluation_amount,
                                "profit_loss": profit_loss,
                                "profit_loss_rate": profit_loss_rate,
                                "exchange": exchange_names.get(exchange, exchange),
                            }
                            all_holdings.append(holding_detail)

            if all_holdings:
                return all_holdings
            return []

        except (ValueError, KeyError, TypeError) as e:
            logger.error("Error fetching holdings detail (attempt %d/%d): %s", attempt + 1, 5, str(e))
            if os.path.exists("token.dat"):
                os.remove("token.dat")
        except Exception as e:
            logger.error("Unexpected error fetching holdings detail (attempt %d/%d): %s", attempt + 1, 5, str(e))

    logger.error("Failed to get holdings detail after multiple attempts")
    return None

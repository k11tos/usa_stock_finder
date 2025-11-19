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

from config import APIConfig

logger = logging.getLogger(__name__)


class APIError(Exception):
    """Custom exception for API-related errors."""


def fetch_us_stock_holdings():
    """
    Fetches a list of stock tickers from the US stock account.

    Returns:
        list: List of stock tickers. Returns empty list on failure

    Raises:
        APIError: Raised when all retry attempts fail

    Note:
        - Retries up to configured number of times
        - Queries both NASDAQ and NYSE exchanges
        - Removes token.dat file if it exists on failure
        - Raises APIError on final failure instead of silently returning empty list
    """
    load_dotenv()
    exchanges = ["나스닥", "뉴욕"]
    selected_items = set()
    last_error = None

    for attempt in range(APIConfig.MAX_RETRIES):
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
                    error_msg = balance.get("msg1", "Unknown API error")
                    raise ValueError(f"API error for {exchange}: {error_msg}")

                tickers = jmespath.search("output1[*].pdno", balance) or []
                selected_items.update(tickers)
                logger.debug("Fetched %d tickers from %s", len(tickers), exchange)

            if selected_items:
                result = list(selected_items)
                logger.info("Successfully fetched %d stock tickers", len(result))
                return result

        except ValueError as e:
            last_error = str(e)
            logger.error("Error fetching stock tickers (attempt %d/%d): %s", attempt + 1, APIConfig.MAX_RETRIES, str(e))
            if os.path.exists("token.dat"):
                os.remove("token.dat")
        except Exception as e:
            last_error = str(e)
            logger.error(
                "Unexpected error fetching stock tickers (attempt %d/%d): %s",
                attempt + 1,
                APIConfig.MAX_RETRIES,
                str(e),
            )

    # All retries failed - raise exception instead of returning empty list
    error_msg = f"Failed to fetch stock tickers after {APIConfig.MAX_RETRIES} attempts"
    if last_error:
        error_msg += f": {last_error}"
    logger.error(error_msg)
    raise APIError(error_msg)


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

    Retrieves available cash balance and other account balance information
    from both NASDAQ and NYSE exchanges, then returns the combined balance.

    Returns:
        dict[str, float] | None: Dictionary containing:
            - "available_cash": Available cash balance - Summed value
            - "total_balance": Total account balance - Summed value
            - "buyable_cash": Buyable cash amount - Summed value
            Returns None on failure

    Raises:
        APIError: Raised when all retry attempts fail

    Note:
        - Retries up to configured number of times
        - Queries both NASDAQ and NYSE exchanges
        - Combines balances from both exchanges (summed)
        - Raises APIError on final failure instead of silently returning None
    """
    logger.info("=" * 60)
    logger.info("fetch_account_balance() function started")
    exchanges = ["나스닥", "뉴욕"]
    last_error = None

    for attempt in range(APIConfig.MAX_RETRIES):
        try:
            logger.info("Fetching account balance attempt %d/%d", attempt + 1, APIConfig.MAX_RETRIES)
            total_available_cash = 0.0
            total_balance = 0.0
            total_buyable_cash = 0.0

            for exchange in exchanges:
                logger.info("Fetching %s exchange", exchange)
                broker = _get_broker(exchange)
                balance = broker.fetch_present_balance()

                logger.info("%s exchange API call completed, rt_cd: %s", exchange, balance.get("rt_cd", "N/A"))

                if balance["rt_cd"] != "0":
                    error_msg = balance.get("msg1", "Unknown error")
                    logger.error("%s exchange API error: %s", exchange, error_msg)
                    raise ValueError(f"API error for {exchange}: {error_msg}")

                # Debug: Check API response structure (INFO level to always show)
                logger.info("=" * 60)
                logger.info("%s exchange API response keys: %s", exchange, list(balance.keys()))
                logger.info(
                    "%s exchange API response rt_cd: %s, msg1: %s",
                    exchange,
                    balance.get("rt_cd"),
                    balance.get("msg1", "N/A"),
                )

                # output2 contains account balance information
                # Common field names in Korean Investment API:
                # - dnca_tot_amt: Total cash (available cash)
                # - nxdy_excc_amt: Next day settlement amount
                # - prvs_rcdl_excc_amt: Previous day settlement amount
                # - cma_evlu_amt: CMA evaluation amount
                # - bfdx_tot_amt: Previous day total amount
                # - tot_evlu_amt: Total evaluation amount
                # - ord_psbl_cash: Orderable cash
                # - nrcvb_buy_amt: Unpaid buy amount
                output2 = balance.get("output2", [])
                logger.info(
                    "%s exchange output2 exists: %s, type: %s, length: %s",
                    exchange,
                    output2 is not None,
                    type(output2),
                    len(output2) if isinstance(output2, (list, dict)) else "N/A",
                )

                if output2 and isinstance(output2, list) and len(output2) > 0:
                    logger.info(
                        "%s exchange output2[0] type: %s", exchange, type(output2[0]) if len(output2) > 0 else "N/A"
                    )
                    account_info = output2[0] if isinstance(output2[0], dict) else {}

                    # Debug: Print all keys and values of account_info (INFO level)
                    if isinstance(account_info, dict):
                        logger.info(
                            "%s exchange account_info all keys: %s",
                            exchange,
                            list(account_info.keys()),
                        )
                        # Print all fields and values (focus on numeric fields)
                        numeric_fields = {
                            k: v
                            for k, v in account_info.items()
                            if isinstance(v, (int, float, str)) and str(v).replace(".", "").replace("-", "").isdigit()
                        }
                        if numeric_fields:
                            logger.info(
                                "%s exchange account_info numeric fields: %s",
                                exchange,
                                numeric_fields,
                            )
                        # Print all fields (first 10)
                        logger.info(
                            "%s exchange account_info all fields (first 10): %s",
                            exchange,
                            {k: v for k, v in list(account_info.items())[:10]},
                        )
                    else:
                        logger.warning("%s exchange account_info is not a dict: %s", exchange, type(account_info))

                    # Try different possible field names for available cash
                    # Using actual API response field names
                    available_cash = 0.0
                    for field in [
                        "frcr_dncl_amt_2",  # Foreign currency available cash (actual field)
                        "dnca_tot_amt",  # General available cash
                        "dnca_tot_amt_2",
                        "dnca_tot_amt_1",
                        "cash",
                    ]:
                        value = account_info.get(field, 0) or 0
                        if value:
                            try:
                                available_cash = float(value)
                                logger.info(
                                    "%s exchange: Available cash value found in field '%s': %.2f",
                                    exchange,
                                    field,
                                    available_cash,
                                )
                                break
                            except (ValueError, TypeError):
                                continue

                    # Total balance (evaluation amount)
                    exchange_balance = 0.0
                    for field in [
                        "frcr_evlu_amt2",  # Foreign currency evaluation amount (actual field)
                        "tot_evlu_amt",  # General total evaluation amount
                        "bfdx_tot_amt",
                        "evlu_amt",
                        "total_amt",
                    ]:
                        value = account_info.get(field, 0) or 0
                        if value:
                            try:
                                exchange_balance = float(value)
                                logger.info(
                                    "%s exchange: Total balance value found in field '%s': %.2f",
                                    exchange,
                                    field,
                                    exchange_balance,
                                )
                                break
                            except (ValueError, TypeError):
                                continue

                    # Buyable cash amount
                    buyable_cash = 0.0
                    for field in [
                        "nxdy_frcr_drwg_psbl_amt",  # Next day foreign currency withdrawable amount (actual field)
                        "frcr_drwg_psbl_amt_1",  # Foreign currency withdrawable amount (actual field)
                        "nxdy_excc_amt",  # Next day settlement amount
                        "prvs_rcdl_excc_amt",  # Previous day settlement amount
                        "ord_psbl_cash",  # Orderable cash
                        "buyable_cash",
                    ]:
                        value = account_info.get(field, 0) or 0
                        if value:
                            try:
                                buyable_cash = float(value)
                                logger.info(
                                    "%s exchange: Buyable cash value found in field '%s': %.2f",
                                    exchange,
                                    field,
                                    buyable_cash,
                                )
                                break
                            except (ValueError, TypeError):
                                continue

                    # Use available cash if buyable cash is not available
                    if buyable_cash == 0.0:
                        buyable_cash = available_cash

                    # Sum balances from both exchanges
                    total_available_cash += available_cash
                    total_balance += exchange_balance  # Modified: Accumulated sum
                    total_buyable_cash += buyable_cash

                    logger.info(
                        "%s exchange: Available cash=%.2f, Total balance=%.2f, Buyable cash=%.2f",
                        exchange,
                        available_cash,
                        exchange_balance,
                        buyable_cash,
                    )
                else:
                    logger.warning("%s exchange: output2 is empty or invalid", exchange)
                    logger.info("%s exchange: balance structure - output2 type: %s", exchange, type(output2))
                    if output2:
                        logger.info("%s exchange: output2 value: %s", exchange, str(output2)[:200])
                    # Check other possible keys when output2 is not available
                    other_keys = [
                        k for k in balance.keys() if k not in ["rt_cd", "msg1", "msg_cd", "output1", "output2"]
                    ]
                    if other_keys:
                        logger.info("%s exchange: balance other keys: %s", exchange, other_keys)

            # Return combined balance from both exchanges
            # Return normal response even if balance is 0 (0 is a valid value)
            result = {
                "available_cash": total_available_cash,
                "total_balance": total_balance if total_balance > 0 else total_available_cash,
                "buyable_cash": total_buyable_cash if total_buyable_cash > 0 else total_available_cash,
            }

            if total_available_cash > 0 or total_balance > 0:
                logger.info(
                    "Account balance fetched successfully: Available cash=%.2f, Total balance=%.2f, Buyable cash=%.2f",
                    result["available_cash"],
                    result["total_balance"],
                    result["buyable_cash"],
                )
            else:
                logger.warning(
                    "Account balance is 0: Available cash=%.2f, Total balance=%.2f, Buyable cash=%.2f",
                    result["available_cash"],
                    result["total_balance"],
                    result["buyable_cash"],
                )

            return result

        except (ValueError, KeyError, TypeError) as e:
            last_error = str(e)
            logger.error("=" * 60)
            logger.error(
                "Error occurred while fetching account balance (attempt %d/%d): %s",
                attempt + 1,
                APIConfig.MAX_RETRIES,
                str(e),
            )
            logger.error("Error type: %s", type(e).__name__)
            import traceback

            logger.error("Detailed error:\n%s", traceback.format_exc())
            if os.path.exists("token.dat"):
                logger.info("Removing token.dat file")
                os.remove("token.dat")
        except Exception as e:
            last_error = str(e)
            logger.error("=" * 60)
            logger.error("Unexpected error occurred (attempt %d/%d): %s", attempt + 1, APIConfig.MAX_RETRIES, str(e))
            logger.error("Error type: %s", type(e).__name__)
            import traceback

            logger.error("Detailed error:\n%s", traceback.format_exc())

    # All retries failed - raise exception instead of returning None
    error_msg = f"Failed to fetch account balance after {APIConfig.MAX_RETRIES} attempts"
    if last_error:
        error_msg += f": {last_error}"
    logger.error(error_msg)
    raise APIError(error_msg)


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

    Raises:
        APIError: Raised when all retry attempts fail

    Note:
        - Retries up to configured number of times
        - Queries both NASDAQ and NYSE exchanges
        - Combines holdings from both exchanges
        - Raises APIError on final failure instead of silently returning None
    """
    exchanges = ["나스닥", "뉴욕"]
    exchange_names = {"나스닥": "NASDAQ", "뉴욕": "NYSE"}
    last_error = None

    for attempt in range(APIConfig.MAX_RETRIES):
        try:
            all_holdings = []
            for exchange in exchanges:
                broker = _get_broker(exchange)
                balance = broker.fetch_present_balance()

                if balance["rt_cd"] != "0":
                    error_msg = balance.get("msg1", "Unknown error")
                    raise ValueError(f"API error for {exchange}: {error_msg}")

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
                            logger.debug(
                                "Holding: %s (%s) - Quantity: %.2f, Avg Price: %.2f, Current Price: %.2f",
                                symbol,
                                exchange,
                                quantity,
                                avg_price,
                                current_price,
                            )

            if all_holdings:
                logger.info("Holdings fetched successfully: %d stocks", len(all_holdings))
                return all_holdings
            logger.info("No holdings")
            return []

        except (ValueError, KeyError, TypeError) as e:
            last_error = str(e)
            logger.error(
                "Error fetching holdings detail (attempt %d/%d): %s", attempt + 1, APIConfig.MAX_RETRIES, str(e)
            )
            if os.path.exists("token.dat"):
                os.remove("token.dat")
        except Exception as e:
            last_error = str(e)
            logger.error(
                "Unexpected error fetching holdings detail (attempt %d/%d): %s",
                attempt + 1,
                APIConfig.MAX_RETRIES,
                str(e),
            )

    # All retries failed - raise exception instead of returning None
    error_msg = f"Failed to fetch holdings detail after {APIConfig.MAX_RETRIES} attempts"
    if last_error:
        error_msg += f": {last_error}"
    logger.error(error_msg)
    raise APIError(error_msg)

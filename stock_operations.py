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


def _to_float(value: Any, default: float = 0.0) -> float:
    """Safely coerce KIS numeric string fields to floats."""
    if value in (None, ""):
        return default
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def _numeric_fields(row: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in row.items()
        if isinstance(v, (int, float, str))
        and str(v).replace(",", "").replace(".", "").replace("-", "").isdigit()
    }


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


def fetch_account_balance() -> dict[str, Any] | None:
    """Fetch USD account cash/equity without mixing KIS KRW cash conversions into equity.

    KIS ``fetch_present_balance()`` returns three relevant sections:
    - ``output1``: per-symbol holdings records (exchange-specific)
    - ``output2``: currency/cash records (account-level; often repeated per exchange)
    - ``output3``: broker aggregate records, when present

    Legacy keys are preserved for callers, but ``total_balance`` now means USD
    account equity: ``available_cash_usd + holdings_market_value_usd``.
    """
    logger.info("=" * 60)
    logger.info("fetch_account_balance() function started")
    exchanges = ["나스닥", "뉴욕"]
    last_error = None

    for attempt in range(APIConfig.MAX_RETRIES):
        try:
            logger.info("Fetching account balance attempt %d/%d", attempt + 1, APIConfig.MAX_RETRIES)
            currency_records: dict[tuple[Any, ...], dict[str, Any]] = {}
            output3_records: list[dict[str, Any]] = []
            holding_records: list[dict[str, Any]] = []
            seen_holdings: set[tuple[Any, ...]] = set()

            for exchange in exchanges:
                logger.info("Fetching %s exchange", exchange)
                broker = _get_broker(exchange)
                balance = broker.fetch_present_balance()

                logger.info("%s exchange API call completed, rt_cd: %s", exchange, balance.get("rt_cd", "N/A"))
                if balance["rt_cd"] != "0":
                    error_msg = balance.get("msg1", "Unknown error")
                    logger.error("%s exchange API error: %s", exchange, error_msg)
                    raise ValueError(f"API error for {exchange}: {error_msg}")

                logger.info("=" * 60)
                logger.info("%s exchange API response keys: %s", exchange, list(balance.keys()))
                logger.info(
                    "%s exchange API response rt_cd: %s, msg1: %s",
                    exchange, balance.get("rt_cd"), balance.get("msg1", "N/A"),
                )

                output1 = balance.get("output1", []) or []
                logger.info(
                    "%s exchange output1 exists: %s, type: %s, length: %s",
                    exchange, output1 is not None, type(output1), len(output1) if isinstance(output1, list) else "N/A",
                )
                if isinstance(output1, list):
                    for row in output1:
                        if not isinstance(row, dict):
                            continue
                        symbol = str(row.get("pdno", "")).replace("-US", "")
                        quantity = _to_float(row.get("cblc_qty13", row.get("hldg_qty", row.get("quantity", 0))))
                        current_price = _to_float(row.get("ovrs_now_pric1", row.get("prpr", row.get("evlu_pric", 0))))
                        evaluation_amount = _to_float(row.get("frcr_evlu_amt2", row.get("evlu_amt", 0)))
                        if evaluation_amount <= 0 and quantity > 0 and current_price > 0:
                            evaluation_amount = quantity * current_price
                        key = (symbol, quantity, current_price, evaluation_amount)
                        if symbol and key not in seen_holdings:
                            seen_holdings.add(key)
                            holding_records.append(row)

                output2 = balance.get("output2", []) or []
                logger.info(
                    "%s exchange output2 exists: %s, type: %s, length: %s",
                    exchange, output2 is not None, type(output2), len(output2) if isinstance(output2, list) else "N/A",
                )
                if isinstance(output2, list):
                    for idx, account_info in enumerate(output2):
                        if not isinstance(account_info, dict):
                            logger.warning(
                                "%s exchange output2[%d] is not a dict: %s",
                                exchange,
                                idx,
                                type(account_info),
                            )
                            continue
                        logger.info("%s exchange output2[%d] keys: %s", exchange, idx, list(account_info.keys()))
                        numeric_fields = _numeric_fields(account_info)
                        if numeric_fields:
                            logger.info("%s exchange output2[%d] numeric fields: %s", exchange, idx, numeric_fields)
                        dedupe_key = (
                            account_info.get("crcy_cd", "USD"),
                            str(account_info.get("frcr_dncl_amt_2", account_info.get("dnca_tot_amt", ""))),
                            str(account_info.get("frst_bltn_exrt", "")),
                            str(account_info.get("frcr_evlu_amt2", account_info.get("tot_evlu_amt", ""))),
                        )
                        if dedupe_key in currency_records:
                            logger.info(
                                "%s exchange output2[%d] duplicate account-level currency record skipped",
                                exchange,
                                idx,
                            )
                            continue
                        currency_records[dedupe_key] = account_info

                output3 = balance.get("output3", []) or []
                logger.info(
                    "%s exchange output3 exists: %s, type: %s, length: %s",
                    exchange,
                    output3 is not None,
                    type(output3),
                    len(output3) if isinstance(output3, (list, dict)) else "N/A",
                )
                output3_iter = output3 if isinstance(output3, list) else [output3] if isinstance(output3, dict) else []
                for idx, aggregate_info in enumerate(output3_iter):
                    if not isinstance(aggregate_info, dict):
                        logger.warning("%s exchange output3[%d] is not a dict: %s", exchange, idx, type(aggregate_info))
                        continue
                    logger.info("%s exchange output3[%d] keys: %s", exchange, idx, list(aggregate_info.keys()))
                    numeric_fields = _numeric_fields(aggregate_info)
                    if numeric_fields:
                        logger.info("%s exchange output3[%d] numeric fields: %s", exchange, idx, numeric_fields)
                    output3_records.append(aggregate_info)

            available_cash_usd = 0.0
            buyable_cash_usd = 0.0
            currency_cash_krw = 0.0
            exchange_rate_krw_per_usd = 0.0
            broker_raw_output2_frcr_evlu_amt2 = 0.0

            for record in currency_records.values():
                crcy_cd = str(record.get("crcy_cd", "USD") or "USD").upper()
                cash_usd = _to_float(record.get("frcr_dncl_amt_2", record.get("dnca_tot_amt", 0)))
                buyable_usd = _to_float(
                    record.get(
                        "nxdy_frcr_drwg_psbl_amt",
                        record.get("frcr_drwg_psbl_amt_1", record.get("ord_psbl_cash", cash_usd)),
                    )
                )
                converted_krw = _to_float(record.get("frcr_evlu_amt2", 0))
                exchange_rate = _to_float(record.get("frst_bltn_exrt", 0))
                if crcy_cd == "USD":
                    available_cash_usd += cash_usd
                    buyable_cash_usd += buyable_usd if buyable_usd > 0 else cash_usd
                    currency_cash_krw += converted_krw
                    broker_raw_output2_frcr_evlu_amt2 += converted_krw
                    if exchange_rate > 0 and exchange_rate_krw_per_usd == 0.0:
                        exchange_rate_krw_per_usd = exchange_rate
                else:
                    currency_cash_krw += converted_krw
                    broker_raw_output2_frcr_evlu_amt2 += converted_krw

            holdings_market_value_usd = 0.0
            for holding in holding_records:
                quantity = _to_float(holding.get("cblc_qty13", holding.get("hldg_qty", holding.get("quantity", 0))))
                current_price = _to_float(
                    holding.get("ovrs_now_pric1", holding.get("prpr", holding.get("evlu_pric", 0)))
                )
                evaluation_amount = _to_float(holding.get("frcr_evlu_amt2", holding.get("evlu_amt", 0)))
                if evaluation_amount <= 0 and quantity > 0 and current_price > 0:
                    evaluation_amount = quantity * current_price
                holdings_market_value_usd += evaluation_amount

            broker_total_asset_krw = 0.0
            broker_foreign_evaluation_total_krw = 0.0
            for record in output3_records:
                if broker_total_asset_krw == 0.0:
                    for field in ("tot_asst_amt", "total_asset", "tot_evlu_amt", "asst_icdc_amt"):
                        broker_total_asset_krw = _to_float(record.get(field, 0))
                        if broker_total_asset_krw > 0:
                            break
                if broker_foreign_evaluation_total_krw == 0.0:
                    for field in ("frcr_evlu_tota", "frcr_evlu_amt", "ovrs_tot_pfls", "tot_evlu_pfls_amt"):
                        broker_foreign_evaluation_total_krw = _to_float(record.get(field, 0))
                        if broker_foreign_evaluation_total_krw > 0:
                            break

            total_equity_usd = available_cash_usd + holdings_market_value_usd
            result = {
                "available_cash_usd": available_cash_usd,
                "buyable_cash_usd": buyable_cash_usd if buyable_cash_usd > 0 else available_cash_usd,
                "currency_cash_krw": currency_cash_krw,
                "exchange_rate_krw_per_usd": exchange_rate_krw_per_usd,
                "holdings_market_value_usd": holdings_market_value_usd,
                "total_equity_usd": total_equity_usd,
                "broker_total_asset_krw": broker_total_asset_krw,
                "broker_foreign_evaluation_total_krw": broker_foreign_evaluation_total_krw,
                "broker_raw_output2_frcr_evlu_amt2": broker_raw_output2_frcr_evlu_amt2,
                "broker_raw_output3": output3_records,
                # Backward-compatible USD aliases.
                "available_cash": available_cash_usd,
                "buyable_cash": buyable_cash_usd if buyable_cash_usd > 0 else available_cash_usd,
                "total_balance": total_equity_usd,
            }

            logger.info(
                "Account balance fetched successfully: cash_usd=%.2f, holdings_market_value_usd=%.2f, "
                "total_equity_usd=%.2f, cash_krw=%.2f, output2_frcr_evlu_amt2=%.2f",
                available_cash_usd, holdings_market_value_usd, total_equity_usd,
                currency_cash_krw, broker_raw_output2_frcr_evlu_amt2,
            )
            return result

        except (ValueError, KeyError, TypeError) as e:
            last_error = str(e)
            logger.error("=" * 60)
            logger.error(
                "Error occurred while fetching account balance (attempt %d/%d): %s",
                attempt + 1, APIConfig.MAX_RETRIES, str(e),
            )
            logger.error("Error type: %s", type(e).__name__)
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
                    logger.debug(
                        "API 응답 output1: %d개 항목, 첫 번째 항목 키: %s",
                        len(output1),
                        list(output1[0].keys()) if output1 and isinstance(output1[0], dict) else "N/A",
                    )
                    for holding in output1:
                        if not isinstance(holding, dict):
                            continue

                        # Extract common field names from Korean Investment API
                        symbol = holding.get("pdno", "").replace("-US", "")
                        name = holding.get("prdt_name", "")

                        # 실제 API 필드명 사용 (로그에서 확인된 실제 키)
                        # cblc_qty13: 정산수량 (보유 수량)
                        # avg_unpr3: 평균단가
                        # ovrs_now_pric1: 해외현재가
                        # evlu_pfls_rt1: 평가손익률
                        # evlu_pfls_amt2: 평가손익금액
                        # frcr_evlu_amt2: 외화평가금액

                        # 디버그: 원본 데이터 확인
                        cblc_qty13_raw = holding.get("cblc_qty13", "N/A")
                        avg_unpr3_raw = holding.get("avg_unpr3", "N/A")
                        ovrs_now_pric1_raw = holding.get("ovrs_now_pric1", "N/A")
                        evlu_pfls_rt1_raw = holding.get("evlu_pfls_rt1", "N/A")

                        # 실제 API 필드명으로 데이터 추출 (기존 필드명도 fallback으로 유지)
                        quantity = float(
                            holding.get("cblc_qty13", holding.get("hldg_qty", holding.get("quantity", 0))) or 0
                        )
                        avg_price = float(
                            holding.get("avg_unpr3", holding.get("pchs_avg_pric", holding.get("avg_price", 0))) or 0
                        )
                        current_price = float(
                            holding.get("ovrs_now_pric1", holding.get("prpr", holding.get("evlu_pric", avg_price))) or 0
                        )
                        evaluation_amount = float(holding.get("frcr_evlu_amt2", holding.get("evlu_amt", 0)) or 0)

                        # 평가손익률이 있으면 사용, 없으면 계산
                        profit_loss_rate_from_api = holding.get("evlu_pfls_rt1")
                        if profit_loss_rate_from_api and profit_loss_rate_from_api != "N/A":
                            try:
                                profit_loss_rate = float(profit_loss_rate_from_api)
                            except (ValueError, TypeError):
                                profit_loss_rate = 0.0
                        else:
                            profit_loss_rate = 0.0

                        # 평가손익금액
                        profit_loss_from_api = holding.get("evlu_pfls_amt2")
                        if profit_loss_from_api and profit_loss_from_api != "N/A":
                            try:
                                profit_loss = float(profit_loss_from_api)
                            except (ValueError, TypeError):
                                profit_loss = 0.0
                        else:
                            profit_loss = 0.0

                        # 디버그: 파싱된 값 확인
                        logger.debug(
                            "Holding: %s (%s) - Quantity: %.2f, Avg Price: %.2f, Current Price: %.2f, "
                            "Profit/Loss Rate: %.2f%%, Raw data: pdno=%s, cblc_qty13=%s, "
                            "avg_unpr3=%s, ovrs_now_pric1=%s, evlu_pfls_rt1=%s",
                            symbol,
                            exchange,
                            quantity,
                            avg_price,
                            current_price,
                            profit_loss_rate,
                            symbol,
                            cblc_qty13_raw,
                            avg_unpr3_raw,
                            ovrs_now_pric1_raw,
                            evlu_pfls_rt1_raw,
                        )

                        # Calculate profit/loss (API에서 제공하지 않으면 계산)
                        if profit_loss == 0.0 and profit_loss_rate == 0.0 and avg_price > 0 and quantity > 0:
                            profit_loss = (current_price - avg_price) * quantity
                            profit_loss_rate = ((current_price - avg_price) / avg_price) * 100

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

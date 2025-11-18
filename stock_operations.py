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

    pass


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
            logger.error("Unexpected error fetching stock tickers (attempt %d/%d): %s", attempt + 1, APIConfig.MAX_RETRIES, str(e))

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

    Retrieves available cash balance (예수금) and other account balance information
    from both NASDAQ and NYSE exchanges, then returns the combined balance.

    Returns:
        dict[str, float] | None: Dictionary containing:
            - "available_cash": Available cash balance (예수금) - 합산된 값
            - "total_balance": Total account balance - 합산된 값
            - "buyable_cash": Buyable cash amount (매수가능금액) - 합산된 값
            Returns None on failure

    Raises:
        APIError: Raised when all retry attempts fail

    Note:
        - Retries up to configured number of times
        - Queries both NASDAQ and NYSE exchanges
        - Combines balances from both exchanges (합산)
        - Raises APIError on final failure instead of silently returning None
    """
    logger.info("=" * 60)
    logger.info("fetch_account_balance() 함수 시작")
    exchanges = ["나스닥", "뉴욕"]
    last_error = None

    for attempt in range(APIConfig.MAX_RETRIES):
        try:
            logger.info("계좌 잔액 조회 시도 %d/%d", attempt + 1, APIConfig.MAX_RETRIES)
            total_available_cash = 0.0
            total_balance = 0.0
            total_buyable_cash = 0.0
            
            for exchange in exchanges:
                logger.info("%s 거래소 조회 시작", exchange)
                broker = _get_broker(exchange)
                balance = broker.fetch_present_balance()
                
                logger.info("%s 거래소 API 호출 완료, rt_cd: %s", exchange, balance.get("rt_cd", "N/A"))

                if balance["rt_cd"] != "0":
                    error_msg = balance.get("msg1", "Unknown error")
                    logger.error("%s 거래소 API 오류: %s", exchange, error_msg)
                    raise ValueError(f"API error for {exchange}: {error_msg}")

                # 디버깅: API 응답 구조 확인 (INFO 레벨로 출력하여 항상 보이도록)
                logger.info("=" * 60)
                logger.info("%s 거래소 API 응답 키: %s", exchange, list(balance.keys()))
                logger.info("%s 거래소 API 응답 rt_cd: %s, msg1: %s", exchange, balance.get("rt_cd"), balance.get("msg1", "N/A"))
                
                # output2 contains account balance information
                # Common field names in Korean Investment API:
                # - dnca_tot_amt: 예수금 총액 (total cash)
                # - nxdy_excc_amt: 익일 정산 금액
                # - prvs_rcdl_excc_amt: 전일 정산 금액
                # - cma_evlu_amt: CMA 평가 금액
                # - bfdx_tot_amt: 전일 총액
                # - tot_evlu_amt: 총 평가 금액
                # - ord_psbl_cash: 주문 가능 현금
                # - nrcvb_buy_amt: 미수매수금액
                output2 = balance.get("output2", [])
                logger.info("%s 거래소 output2 존재 여부: %s, 타입: %s, 길이: %s", 
                           exchange, output2 is not None, type(output2), len(output2) if isinstance(output2, (list, dict)) else "N/A")
                
                if output2 and isinstance(output2, list) and len(output2) > 0:
                    logger.info("%s 거래소 output2[0] 타입: %s", exchange, type(output2[0]) if len(output2) > 0 else "N/A")
                    account_info = output2[0] if isinstance(output2[0], dict) else {}
                    
                    # 디버깅: account_info의 모든 키와 값 출력 (INFO 레벨로 출력)
                    if isinstance(account_info, dict):
                        logger.info(
                            "%s 거래소 account_info 모든 키: %s",
                            exchange,
                            list(account_info.keys()),
                        )
                        # 모든 필드와 값을 출력 (숫자 필드 중심)
                        numeric_fields = {k: v for k, v in account_info.items() if isinstance(v, (int, float, str)) and str(v).replace('.', '').replace('-', '').isdigit()}
                        if numeric_fields:
                            logger.info(
                                "%s 거래소 account_info 숫자 필드: %s",
                                exchange,
                                numeric_fields,
                            )
                        # 모든 필드 출력 (처음 10개)
                        logger.info(
                            "%s 거래소 account_info 전체 필드 (처음 10개): %s",
                            exchange,
                            {k: v for k, v in list(account_info.items())[:10]},
                        )
                    else:
                        logger.warning("%s 거래소 account_info가 dict가 아님: %s", exchange, type(account_info))
                    
                    # Try different possible field names for available cash (예수금)
                    # 실제 API 응답 필드명 사용
                    available_cash = 0.0
                    for field in [
                        "frcr_dncl_amt_2",  # 외화 예수금 (실제 필드)
                        "dnca_tot_amt",  # 일반 예수금
                        "dnca_tot_amt_2",
                        "dnca_tot_amt_1",
                        "cash",
                        "예수금"
                    ]:
                        value = account_info.get(field, 0) or 0
                        if value:
                            try:
                                available_cash = float(value)
                                logger.info("%s 거래소: 예수금 필드 '%s'에서 값 발견: %.2f", exchange, field, available_cash)
                                break
                            except (ValueError, TypeError):
                                continue
                    
                    # 총액 (평가금액)
                    exchange_balance = 0.0
                    for field in [
                        "frcr_evlu_amt2",  # 외화 평가금액 (실제 필드)
                        "tot_evlu_amt",  # 일반 총 평가금액
                        "bfdx_tot_amt",
                        "evlu_amt",
                        "total_amt",
                        "총액"
                    ]:
                        value = account_info.get(field, 0) or 0
                        if value:
                            try:
                                exchange_balance = float(value)
                                logger.info("%s 거래소: 총액 필드 '%s'에서 값 발견: %.2f", exchange, field, exchange_balance)
                                break
                            except (ValueError, TypeError):
                                continue
                    
                    # 매수가능금액
                    buyable_cash = 0.0
                    for field in [
                        "nxdy_frcr_drwg_psbl_amt",  # 익일 외화 출금가능금액 (실제 필드)
                        "frcr_drwg_psbl_amt_1",  # 외화 출금가능금액 (실제 필드)
                        "nxdy_excc_amt",  # 익일 정산 금액
                        "prvs_rcdl_excc_amt",  # 전일 정산 금액
                        "ord_psbl_cash",  # 주문 가능 현금
                        "buyable_cash",
                        "매수가능"
                    ]:
                        value = account_info.get(field, 0) or 0
                        if value:
                            try:
                                buyable_cash = float(value)
                                logger.info("%s 거래소: 매수가능 필드 '%s'에서 값 발견: %.2f", exchange, field, buyable_cash)
                                break
                            except (ValueError, TypeError):
                                continue
                    
                    # 매수가능금액이 없으면 예수금 사용
                    if buyable_cash == 0.0:
                        buyable_cash = available_cash

                    # 두 거래소의 잔액을 합산
                    total_available_cash += available_cash
                    total_balance += exchange_balance  # 수정: 누적 합산
                    total_buyable_cash += buyable_cash

                    logger.info(
                        "%s 거래소: 예수금=%.2f, 총액=%.2f, 매수가능=%.2f",
                        exchange,
                        available_cash,
                        exchange_balance,
                        buyable_cash,
                    )
                else:
                    logger.warning("%s 거래소: output2가 비어있거나 유효하지 않음", exchange)
                    logger.info("%s 거래소: balance 구조 - output2 타입: %s", exchange, type(output2))
                    if output2:
                        logger.info("%s 거래소: output2 값: %s", exchange, str(output2)[:200])
                    # output2가 없을 때 다른 가능한 키 확인
                    other_keys = [k for k in balance.keys() if k not in ["rt_cd", "msg1", "msg_cd", "output1", "output2"]]
                    if other_keys:
                        logger.info("%s 거래소: balance의 다른 키들: %s", exchange, other_keys)

            # Return combined balance from both exchanges
            # 잔액이 0이어도 정상 응답 반환 (0은 유효한 값)
            result = {
                "available_cash": total_available_cash,
                "total_balance": total_balance if total_balance > 0 else total_available_cash,
                "buyable_cash": total_buyable_cash if total_buyable_cash > 0 else total_available_cash,
            }
            
            if total_available_cash > 0 or total_balance > 0:
                logger.info(
                    "계좌 잔액 조회 성공: 예수금=%.2f, 총액=%.2f, 매수가능=%.2f",
                    result["available_cash"],
                    result["total_balance"],
                    result["buyable_cash"],
                )
            else:
                logger.warning(
                    "계좌 잔액이 0입니다: 예수금=%.2f, 총액=%.2f, 매수가능=%.2f",
                    result["available_cash"],
                    result["total_balance"],
                    result["buyable_cash"],
                )
            
            return result

        except (ValueError, KeyError, TypeError) as e:
            last_error = str(e)
            logger.error("=" * 60)
            logger.error("계좌 잔액 조회 중 오류 발생 (시도 %d/%d): %s", attempt + 1, APIConfig.MAX_RETRIES, str(e))
            logger.error("오류 타입: %s", type(e).__name__)
            import traceback
            logger.error("상세 오류:\n%s", traceback.format_exc())
            if os.path.exists("token.dat"):
                logger.info("token.dat 파일 삭제")
                os.remove("token.dat")
        except Exception as e:
            last_error = str(e)
            logger.error("=" * 60)
            logger.error("예상치 못한 오류 발생 (시도 %d/%d): %s", attempt + 1, APIConfig.MAX_RETRIES, str(e))
            logger.error("오류 타입: %s", type(e).__name__)
            import traceback
            logger.error("상세 오류:\n%s", traceback.format_exc())

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
                                "보유 종목: %s (%s) - 수량: %.2f, 평균가: %.2f, 현재가: %.2f",
                                symbol,
                                exchange,
                                quantity,
                                avg_price,
                                current_price,
                            )

            if all_holdings:
                logger.info("보유 종목 조회 성공: %d개 종목", len(all_holdings))
                return all_holdings
            logger.info("보유 종목 없음")
            return []

        except (ValueError, KeyError, TypeError) as e:
            last_error = str(e)
            logger.error("Error fetching holdings detail (attempt %d/%d): %s", attempt + 1, APIConfig.MAX_RETRIES, str(e))
            if os.path.exists("token.dat"):
                os.remove("token.dat")
        except Exception as e:
            last_error = str(e)
            logger.error("Unexpected error fetching holdings detail (attempt %d/%d): %s", attempt + 1, APIConfig.MAX_RETRIES, str(e))

    # All retries failed - raise exception instead of returning None
    error_msg = f"Failed to fetch holdings detail after {APIConfig.MAX_RETRIES} attempts"
    if last_error:
        error_msg += f": {last_error}"
    logger.error(error_msg)
    raise APIError(error_msg)

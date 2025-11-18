"""
test_improvements.py

테스트 케이스: 개선 사항 검증
- ZeroDivision 방지 테스트
- 데이터 부족 종목 제외 테스트
- 계좌 잔액 합산 테스트
- 환경 변수 검증 테스트
- 매수 수량 계산 로직 테스트
"""

import os
from unittest.mock import Mock, patch

import pytest

from config import ConfigError, EnvironmentConfig, StrategyConfig, InvestmentConfig
from stock_analysis import UsaStockFinder
from stock_operations import APIError, fetch_account_balance


class TestZeroDivisionPrevention:
    """ZeroDivision 방지 테스트"""

    def test_is_above_52_week_low_with_zero_low(self):
        """last_low가 0인 경우 False 반환 테스트"""
        symbols = ["TEST"]
        finder = UsaStockFinder(symbols)
        
        # last_low를 0으로 설정
        finder.last_low["TEST"] = 0.0
        finder.current_price["TEST"] = 100.0
        
        result = finder.is_above_52_week_low(0.0)
        
        # ZeroDivision이 발생하지 않고 False를 반환해야 함
        assert result["TEST"] is False

    def test_is_above_52_week_low_with_very_small_low(self):
        """last_low가 매우 작은 값인 경우 False 반환 테스트"""
        symbols = ["TEST"]
        finder = UsaStockFinder(symbols)
        
        # last_low를 최소 임계값보다 작게 설정
        finder.last_low["TEST"] = 0.001
        finder.current_price["TEST"] = 100.0
        
        result = finder.is_above_52_week_low(0.0)
        
        # False를 반환해야 함
        assert result["TEST"] is False


class TestDataInsufficientExclusion:
    """데이터 부족 종목 자동 제외 테스트"""

    def test_trend_template_with_insufficient_data(self):
        """MA 데이터가 부족한 종목은 트렌드 템플릿에서 제외"""
        symbols = ["TEST"]
        finder = UsaStockFinder(symbols)
        
        # MA 값을 0으로 설정 (데이터 부족)
        finder.last_high["TEST"] = 100.0
        finder.last_low["TEST"] = 50.0
        finder.current_price["TEST"] = 80.0
        
        # get_moving_averages가 0을 반환하도록 모킹
        with patch.object(finder, 'get_moving_averages', return_value={"TEST": 0.0}):
            result = finder.has_valid_trend_template(0.0)
            
            # 데이터 부족으로 False 반환
            assert result["TEST"] is False


class TestAccountBalanceSummation:
    """계좌 잔액 합산 테스트"""

    @patch('stock_operations._get_broker')
    def test_fetch_account_balance_summation(self, mock_get_broker):
        """두 거래소의 잔액이 정확히 합산되는지 테스트"""
        # NASDAQ 거래소 모킹
        nasdaq_broker = Mock()
        nasdaq_balance = {
            "rt_cd": "0",
            "output2": [{
                "dnca_tot_amt": "1000.0",
                "tot_evlu_amt": "5000.0",
                "nxdy_excc_amt": "1000.0",
            }]
        }
        nasdaq_broker.fetch_present_balance.return_value = nasdaq_balance
        
        # NYSE 거래소 모킹
        nyse_broker = Mock()
        nyse_balance = {
            "rt_cd": "0",
            "output2": [{
                "dnca_tot_amt": "2000.0",
                "tot_evlu_amt": "6000.0",
                "nxdy_excc_amt": "2000.0",
            }]
        }
        nyse_broker.fetch_present_balance.return_value = nyse_balance
        
        # 거래소별로 다른 브로커 반환
        def broker_side_effect(exchange):
            if exchange == "나스닥":
                return nasdaq_broker
            return nyse_broker
        
        mock_get_broker.side_effect = broker_side_effect
        
        result = fetch_account_balance()
        
        # 두 거래소의 잔액이 합산되어야 함
        assert result is not None
        assert result["available_cash"] == 3000.0  # 1000 + 2000
        assert result["total_balance"] == 11000.0  # 5000 + 6000
        assert result["buyable_cash"] == 3000.0  # 1000 + 2000


class TestEnvironmentVariableValidation:
    """환경 변수 검증 테스트"""

    def test_validate_missing_required_vars(self):
        """필수 환경 변수가 없을 때 ConfigError 발생"""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigError) as exc_info:
                EnvironmentConfig.validate()
            
            assert "Missing required environment variables" in str(exc_info.value)

    def test_validate_with_all_vars(self):
        """모든 필수 환경 변수가 있을 때 검증 통과"""
        test_env = {
            "ki_app_key": "test_key",
            "ki_app_secret_key": "test_secret",
            "account_number": "test_account",
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_CHAT_ID": "test_chat_id",
        }
        
        with patch.dict(os.environ, test_env, clear=True):
            # 예외가 발생하지 않아야 함
            EnvironmentConfig.validate()


class TestBuyQuantityCalculation:
    """매수 수량 계산 로직 테스트"""

    def test_additional_buy_calculation_new_stock(self):
        """신규 매수: current_quantity == 0인 경우"""
        investment_amount = 1000.0
        current_price = 100.0
        current_quantity = 0
        
        shares_to_buy = int(investment_amount / current_price)  # 10주
        if current_quantity == 0:
            additional_buy = shares_to_buy  # 신규매수
        else:
            additional_buy = max(shares_to_buy - current_quantity, 0)
        
        assert additional_buy == 10
        assert shares_to_buy == 10

    def test_additional_buy_calculation_existing_stock(self):
        """추가 매수: current_quantity > 0인 경우"""
        investment_amount = 1000.0
        current_price = 100.0
        current_quantity = 5  # 이미 5주 보유
        
        shares_to_buy = int(investment_amount / current_price)  # 목표: 10주
        if current_quantity == 0:
            additional_buy = shares_to_buy
        else:
            additional_buy = max(shares_to_buy - current_quantity, 0)  # 추가: 5주
        
        assert additional_buy == 5  # 10 - 5 = 5주 추가 매수
        assert shares_to_buy == 10  # 목표 총 수량

    def test_additional_buy_calculation_already_enough(self):
        """이미 목표 수량 이상 보유한 경우"""
        investment_amount = 1000.0
        current_price = 100.0
        current_quantity = 15  # 이미 15주 보유 (목표 10주 초과)
        
        shares_to_buy = int(investment_amount / current_price)  # 목표: 10주
        if current_quantity == 0:
            additional_buy = shares_to_buy
        else:
            additional_buy = max(shares_to_buy - current_quantity, 0)
        
        assert additional_buy == 0  # 추가 매수 불필요
        assert shares_to_buy == 10


class TestAPIRetryFailure:
    """API 재시도 실패 시 에러 처리 테스트"""

    @patch('stock_operations._get_broker')
    def test_fetch_account_balance_raises_on_failure(self, mock_get_broker):
        """모든 재시도 실패 시 APIError 발생"""
        broker = Mock()
        broker.fetch_present_balance.return_value = {"rt_cd": "1", "msg1": "API Error"}
        mock_get_broker.return_value = broker
        
        with pytest.raises(APIError) as exc_info:
            fetch_account_balance()
        
        assert "Failed to fetch account balance" in str(exc_info.value)


class TestMinMaxInvestment:
    """최소/최대 투자금 조건 테스트"""

    def test_min_investment_exclusion(self):
        """최소 투자금 미달 종목 제외"""
        buy_items = ["STOCK1", "STOCK2", "STOCK3"]
        total_investment = 250.0  # 총 투자 가능 금액
        min_investment = 100.0  # 최소 투자금
        
        investment_per_stock = total_investment / len(buy_items)  # 83.33
        affordable_stocks = []
        
        for symbol in buy_items:
            if investment_per_stock >= min_investment:
                affordable_stocks.append(symbol)
        
        # 최소 투자금 미달로 모든 종목 제외
        assert len(affordable_stocks) == 0

    def test_max_investment_capping(self):
        """최대 투자금 제한 적용"""
        investment_per_stock = 1000.0
        max_investment = 500.0
        
        if max_investment and investment_per_stock > max_investment:
            investment_per_stock = max_investment
        
        assert investment_per_stock == 500.0


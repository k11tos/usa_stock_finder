"""
Common test configuration and fixtures for the USA Stock Finder application.

This file provides shared fixtures and configuration that can be used across
all test modules without explicit import statements.
"""

import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(scope="session")
def test_environment():
    """전체 테스트 세션에서 사용할 환경 설정"""
    return {"test_mode": True, "log_level": "DEBUG", "timeout": 30, "max_retries": 3}


@pytest.fixture(scope="function")
def temp_directory():
    """각 테스트 함수마다 임시 디렉토리 제공"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir

    # 테스트 후 정리
    import shutil

    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)


@pytest.fixture(scope="function")
def sample_portfolio():
    """테스트용 샘플 포트폴리오 데이터"""
    return [
        {"symbol": "AAPL-US", "name": "Apple Inc", "market": "Nasdaq"},
        {"symbol": "MSFT-US", "name": "Microsoft Corp", "market": "Nasdaq"},
        {"symbol": "GOOGL-US", "name": "Alphabet Inc", "market": "Nasdaq"},
        {"symbol": "TSLA-US", "name": "Tesla Inc", "market": "Nasdaq"},
        {"symbol": "NVDA-US", "name": "NVIDIA Corp", "market": "Nasdaq"},
    ]


@pytest.fixture(scope="function")
def sample_correlations():
    """테스트용 샘플 상관관계 데이터"""
    return {
        "200": {"AAPL": 75.5, "MSFT": 82.3, "GOOGL": 68.9, "TSLA": 45.2, "NVDA": 78.1},
        "100": {"AAPL": 71.2, "MSFT": 78.9, "GOOGL": 65.4, "TSLA": 42.1, "NVDA": 74.8},
        "50": {"AAPL": 68.7, "MSFT": 76.2, "GOOGL": 62.1, "TSLA": 38.5, "NVDA": 71.3},
    }


@pytest.fixture(scope="function")
def mock_stock_finder():
    """테스트용 모의 주식 분석기"""
    mock_finder = MagicMock()
    mock_finder.symbols = ["AAPL", "MSFT", "GOOGL", "TSLA", "NVDA"]

    # has_valid_trend_template 메서드 모킹
    mock_finder.has_valid_trend_template = MagicMock(
        side_effect=[
            {"AAPL": True, "MSFT": True, "GOOGL": False, "TSLA": False, "NVDA": True},
            {"AAPL": True, "MSFT": True, "GOOGL": True, "TSLA": False, "NVDA": True},
        ]
    )

    return mock_finder


@pytest.fixture(scope="function")
def mock_telegram_bot():
    """테스트용 모의 텔레그램 봇"""
    mock_bot = MagicMock()
    mock_bot.sendMessage = AsyncMock()
    return mock_bot


@pytest.fixture(scope="function")
def mock_korea_investment_api():
    """테스트용 모의 한국투자증권 API"""
    mock_api = MagicMock()
    mock_api.fetch_present_balance.return_value = {
        "rt_cd": "0",  # 성공 응답 코드
        "output1": [
            {"pdno": "AAPL-US", "quantity": 100, "avg_price": 150.0},
            {"pdno": "MSFT-US", "quantity": 50, "avg_price": 300.0},
            {"pdno": "GOOGL-US", "quantity": 75, "avg_price": 2500.0},
        ],
    }
    return mock_api


@pytest.fixture(scope="function")
def test_data_files(temp_directory):
    """테스트용 데이터 파일들 생성"""
    # 포트폴리오 CSV 파일
    portfolio_file = os.path.join(temp_directory, "portfolio.csv")
    portfolio_content = (
        "Code,Name,Market\n"
        "AAPL-US,Apple Inc,Nasdaq\n"
        "MSFT-US,Microsoft Corp,Nasdaq\n"
        "GOOGL-US,Alphabet Inc,Nasdaq"
    )
    with open(portfolio_file, "w", encoding="utf-8") as f:
        f.write(portfolio_content)

    # 데이터 JSON 파일
    data_file = os.path.join(temp_directory, "data.json")
    test_data = {
        "portfolio": ["AAPL", "MSFT"],
        "last_updated": "2024-01-01",
        "correlations": {
            "200": {"AAPL": 75.5, "MSFT": 82.3},
            "100": {"AAPL": 71.2, "MSFT": 78.9},
            "50": {"AAPL": 68.7, "MSFT": 76.2},
        },
    }
    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(test_data, f, indent=2)

    # 에러 로그 파일
    error_log_file = os.path.join(temp_directory, "error_log.json")
    error_log = {"errors": [], "last_error": None, "error_count": 0, "recovery_attempts": 0}
    with open(error_log_file, "w", encoding="utf-8") as f:
        json.dump(error_log, f, indent=2)

    return {
        "portfolio_file": portfolio_file,
        "data_file": data_file,
        "error_log_file": error_log_file,
        "temp_directory": temp_directory,
    }


@pytest.fixture(scope="function")
def mock_yfinance_data():
    """테스트용 모의 yfinance 데이터"""
    mock_data = MagicMock()
    mock_data.index = MagicMock()
    mock_data.index.__getitem__ = MagicMock(return_value=MagicMock())

    # tail() 메서드 모킹
    mock_data.tail.return_value = mock_data

    # Close와 Volume 데이터 모킹
    def create_comparable_mock():
        mock = MagicMock()
        mock.__lt__ = MagicMock(return_value=MagicMock())
        mock.__ge__ = MagicMock(return_value=MagicMock())
        mock.__and__ = MagicMock(return_value=MagicMock())
        mock.mean.return_value = 0.75
        return mock

    mock_close = MagicMock()
    mock_close.__getitem__ = MagicMock(return_value=mock_close)
    mock_close.diff.return_value = create_comparable_mock()

    mock_volume = MagicMock()
    mock_volume.__getitem__ = MagicMock(return_value=mock_volume)
    mock_volume.diff.return_value = create_comparable_mock()

    # 데이터 타입별 반환 설정
    mock_data.__getitem__.side_effect = lambda x: mock_close if x == "Close" else mock_volume

    return mock_data


@pytest.fixture(scope="function")
def test_environment_variables():
    """테스트용 환경 변수 설정"""
    test_env = {
        "ki_app_key": "test_key_12345",
        "ki_app_secret_key": "test_secret_67890",
        "account_number": "test_account_123",
        "telegram_bot_token": "test_bot_token",
        "telegram_chat_id": "test_chat_id",
    }

    # 환경 변수 설정
    with patch.dict("os.environ", test_env):
        yield test_env


@pytest.fixture(scope="function")
def performance_benchmark():
    """성능 벤치마크 측정용 픽스처"""
    import time

    class PerformanceBenchmark:
        def __init__(self):
            self.start_time = None
            self.end_time = None

        def start(self):
            self.start_time = time.time()

        def stop(self):
            self.end_time = time.time()

        def get_duration(self):
            if self.start_time and self.end_time:
                return self.end_time - self.start_time
            return None

        def assert_faster_than(self, max_duration):
            duration = self.get_duration()
            assert duration is not None, "Benchmark not started/stopped"
            assert duration < max_duration, f"Operation took {duration:.3f}s, expected < {max_duration}s"

    return PerformanceBenchmark()


# pytest 마커 등록
def pytest_configure(config):
    """pytest 설정 시 마커 등록"""
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "slow: Slow running tests (>1s)")
    config.addinivalue_line("markers", "fast: Fast running tests (<1s)")
    config.addinivalue_line("markers", "error_handling: Error handling tests")
    config.addinivalue_line("markers", "performance: Performance tests")
    config.addinivalue_line("markers", "memory: Memory usage tests")
    config.addinivalue_line("markers", "concurrent: Concurrent operation tests")

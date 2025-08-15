"""
Test configuration and environment variables for the USA Stock Finder application.

This module provides test-specific configuration that can be imported
by test modules to ensure consistent test environment setup.
"""

import os
from typing import Any, Dict


class TestConfig:
    """테스트 환경 설정 클래스"""

    # Test Mode Settings
    TEST_MODE = True
    TEST_LOG_LEVEL = "DEBUG"
    TEST_DATA_DIR = "./test_data"
    TEST_TIMEOUT = 30
    TEST_MAX_RETRIES = 3

    # Test Data Settings
    TEST_PORTFOLIO_SIZE = 1000
    TEST_CORRELATION_SAMPLES = 100
    TEST_PERFORMANCE_THRESHOLD = 5.0

    # Test API Keys (Dummy values for testing)
    TEST_KI_APP_KEY = "test_key_12345"
    TEST_KI_APP_SECRET_KEY = "test_secret_67890"
    TEST_ACCOUNT_NUMBER = "test_account_123"
    TEST_EXCHANGE = "test_exchange"

    # Test Telegram Settings
    TEST_TELEGRAM_BOT_TOKEN = "test_bot_token_12345"
    TEST_TELEGRAM_CHAT_ID = "test_chat_id_67890"
    TEST_TELEGRAM_TIMEOUT = 10

    # Test File Settings
    TEST_CSV_ENCODING = "utf-8"
    TEST_JSON_INDENT = 2
    TEST_LOG_FORMAT = "json"

    # Test Performance Settings
    TEST_PERFORMANCE_TIMEOUT = 1.0
    TEST_MEMORY_LIMIT_MB = 512
    TEST_CONCURRENT_THREADS = 5

    # Test Coverage Settings
    TEST_COVERAGE_MIN = 80
    TEST_COVERAGE_REPORT_HTML = True
    TEST_COVERAGE_REPORT_XML = False

    # Test Parallel Settings
    TEST_PARALLEL_WORKERS = 2
    TEST_PARALLEL_TIMEOUT = 300

    # Test Markers
    TEST_MARKERS = "unit,integration,fast,error_handling"
    TEST_EXCLUDE_MARKERS = "slow,performance,memory"

    @classmethod
    def get_test_env_vars(cls) -> Dict[str, str]:
        """테스트용 환경 변수 딕셔너리 반환"""
        return {
            "TEST_MODE": str(cls.TEST_MODE),
            "TEST_LOG_LEVEL": cls.TEST_LOG_LEVEL,
            "TEST_DATA_DIR": cls.TEST_DATA_DIR,
            "TEST_TIMEOUT": str(cls.TEST_TIMEOUT),
            "TEST_MAX_RETRIES": str(cls.TEST_MAX_RETRIES),
            "TEST_KI_APP_KEY": cls.TEST_KI_APP_KEY,
            "TEST_KI_APP_SECRET_KEY": cls.TEST_KI_APP_SECRET_KEY,
            "TEST_ACCOUNT_NUMBER": cls.TEST_ACCOUNT_NUMBER,
            "TEST_EXCHANGE": cls.TEST_EXCHANGE,
            "TEST_TELEGRAM_BOT_TOKEN": cls.TEST_TELEGRAM_BOT_TOKEN,
            "TEST_TELEGRAM_CHAT_ID": cls.TEST_TELEGRAM_CHAT_ID,
            "TEST_TELEGRAM_TIMEOUT": str(cls.TEST_TELEGRAM_TIMEOUT),
            "TEST_CSV_ENCODING": cls.TEST_CSV_ENCODING,
            "TEST_JSON_INDENT": str(cls.TEST_JSON_INDENT),
            "TEST_LOG_FORMAT": cls.TEST_LOG_FORMAT,
            "TEST_PERFORMANCE_TIMEOUT": str(cls.TEST_PERFORMANCE_TIMEOUT),
            "TEST_MEMORY_LIMIT_MB": str(cls.TEST_MEMORY_LIMIT_MB),
            "TEST_CONCURRENT_THREADS": str(cls.TEST_CONCURRENT_THREADS),
            "TEST_COVERAGE_MIN": str(cls.TEST_COVERAGE_MIN),
            "TEST_COVERAGE_REPORT_HTML": str(cls.TEST_COVERAGE_REPORT_HTML),
            "TEST_COVERAGE_REPORT_XML": str(cls.TEST_COVERAGE_REPORT_XML),
            "TEST_PARALLEL_WORKERS": str(cls.TEST_PARALLEL_WORKERS),
            "TEST_PARALLEL_TIMEOUT": str(cls.TEST_PARALLEL_TIMEOUT),
            "TEST_MARKERS": cls.TEST_MARKERS,
            "TEST_EXCLUDE_MARKERS": cls.TEST_EXCLUDE_MARKERS,
        }

    @classmethod
    def setup_test_environment(cls) -> None:
        """테스트 환경 설정"""
        # 테스트 데이터 디렉토리 생성
        os.makedirs(cls.TEST_DATA_DIR, exist_ok=True)

        # 환경 변수 설정
        for key, value in cls.get_test_env_vars().items():
            os.environ[key] = value

    @classmethod
    def cleanup_test_environment(cls) -> None:
        """테스트 환경 정리"""
        # 테스트 환경 변수 제거
        for key in cls.get_test_env_vars():
            if key in os.environ:
                del os.environ[key]

        # 테스트 데이터 디렉토리 정리 (선택사항)
        # import shutil
        # if os.path.exists(cls.TEST_DATA_DIR):
        #     shutil.rmtree(cls.TEST_DATA_DIR)


# 테스트 설정 인스턴스
test_config = TestConfig()


# 편의를 위한 함수들
def setup_test_env():
    """테스트 환경 설정 함수"""
    test_config.setup_test_environment()


def cleanup_test_env():
    """테스트 환경 정리 함수"""
    test_config.cleanup_test_environment()


def get_test_env_var(key: str, default: Any = None) -> str:
    """테스트 환경 변수 값 반환"""
    return os.environ.get(key, default)


def set_test_env_var(key: str, value: str) -> None:
    """테스트 환경 변수 설정"""
    os.environ[key] = value

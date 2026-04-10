"""Backtest engine skeleton tests."""

import backtests.engine  # noqa: F401


def test_backtest_engine_module_imports() -> None:
    """Skeleton module should be import-safe."""
    assert backtests.engine is not None

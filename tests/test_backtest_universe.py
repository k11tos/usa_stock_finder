"""Backtest universe skeleton tests."""

import backtests.universe  # noqa: F401


def test_backtest_universe_module_imports() -> None:
    """Skeleton module should be import-safe."""
    assert backtests.universe is not None

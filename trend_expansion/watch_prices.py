"""Quarterly OHLCV validation and coarse momentum; no daily buy gates."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

from trend_expansion.research_cache import ResearchDataError

PRICE_CONVENTION = "yahoo_close_split_adjusted_dividend_unadjusted"


@dataclass(frozen=True)
class WatchParameters:  # pylint: disable=too-many-instance-attributes
    """Initial research defaults, not optimized or production strategy settings."""

    min_price: float = 5
    max_price: float = 90
    min_bars: int = 252
    liquidity_sessions: int = 20
    min_dollar_volume: float = 2_000_000
    short_sessions: int = 63
    long_sessions: int = 126
    short_weight: float = 0.4
    long_weight: float = 0.6
    market_cap_policy: str = "diagnostic"
    min_market_cap: float = 300_000_000
    target_total: int = 100
    max_expansion: int = 50
    max_verifications: int = 150

    def __post_init__(self):
        for value in (self.min_price, self.max_price, self.min_dollar_volume,
                      self.min_market_cap, self.short_weight, self.long_weight):
            if not math.isfinite(value) or value < 0:
                raise ValueError("parameters must be finite and nonnegative")
        if (self.min_price <= 0 or self.max_price < self.min_price
                or not math.isclose(self.short_weight + self.long_weight, 1, abs_tol=1e-12)):
            raise ValueError("invalid prices or weights")
        for value in (self.min_bars, self.liquidity_sessions, self.short_sessions,
                      self.long_sessions, self.target_total, self.max_expansion, self.max_verifications):
            if not isinstance(value, int) or not 1 <= value <= 10000:
                raise ValueError("invalid session or size parameter")
        if (self.min_bars < max(252, self.long_sessions + 1, self.short_sessions + 1, self.liquidity_sessions)
                or self.max_expansion > 50 or self.max_verifications > 200):
            raise ValueError("history or expansion resource bound violated")
        if self.market_cap_policy not in {"diagnostic", "require_known"}:
            raise ValueError("market_cap_policy must be diagnostic or require_known")


def asof_cutoff(asof_date: str, session_date: str) -> str:
    """Explicit exchange session avoids guessing U.S. holidays from weekdays.

    Use 16:00 America/New_York even on half days (a conservative daily-bar
    cutoff). Calendar quarter date may follow the supplied last session by <=4d.
    """
    asof, session = date.fromisoformat(asof_date), date.fromisoformat(session_date)
    if asof.isoformat() != asof_date or session.isoformat() != session_date:
        raise ValueError("dates must use YYYY-MM-DD")
    if asof > datetime.now(ZoneInfo("America/New_York")).date():
        raise ValueError("future asof_date")
    if session.weekday() > 4 or not 0 <= (asof - session).days <= 4:
        raise ValueError("invalid last session for asof_date")
    cutoff = datetime.combine(session, time(16), ZoneInfo("America/New_York"))
    if cutoff > datetime.now(ZoneInfo("America/New_York")):
        raise ValueError("session not closed")
    return cutoff.isoformat()


def chart_url(symbol: str, session_date: str) -> str:
    """Request only 550 calendar days through the last complete session."""
    end = date.fromisoformat(session_date) + timedelta(days=1)
    start = end - timedelta(days=550)
    zone = ZoneInfo("America/New_York")
    params = urlencode({"period1": int(datetime.combine(start, time(), zone).timestamp()),
                        "period2": int(datetime.combine(end, time(), zone).timestamp()),
                        "interval": "1d", "events": "history"})
    provider_symbol = symbol.replace(".", "-")
    return f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(provider_symbol, safe='')}?{params}"


def decode_chart(payload: bytes, symbol: str) -> list[dict]:
    """Decode raw Yahoo close, never Adj Close or auto-adjusted dividend returns."""
    try:
        data = json.loads(payload)["chart"]
        if data.get("error"):
            raise ResearchDataError("provider_error")
        result = data["result"][0]
        provider_symbol = result["meta"]["symbol"]
        if not isinstance(provider_symbol, str):
            raise ResearchDataError("ohlcv_malformed")
        if provider_symbol.upper() != symbol.replace(".", "-"):
            raise ResearchDataError("provider_symbol_mismatch")
        zone = ZoneInfo("America/New_York")
        values = result["indicators"]["quote"][0]
        stamps = result.get("timestamp", [])
        if len(stamps) > 550:
            raise ResearchDataError("too_many_bars")
        return [{"date": datetime.fromtimestamp(stamp, zone).date().isoformat(),
                 **{key: values[key][i] for key in ("open", "high", "low", "close", "volume")}}
                for i, stamp in enumerate(stamps)]
    except (ValueError, KeyError, TypeError, IndexError, OverflowError) as exc:
        raise ResearchDataError("ohlcv_malformed") from exc


def screen_bars(bars: list[dict], session_date: str, params: WatchParameters) -> dict:
    """Fail closed on invalid bars; retain threshold failures as valid OHLCV.

    No dropping invalid sessions or forward fill. Returns are C[t]/C[t-N]-1.
    Dollar volume is mean of the last 20 individual close*volume products.
    """
    # pylint: disable=too-many-return-statements
    result = {"ohlcv_validity": "invalid", "bar_count": len(bars), "reason": "missing_bars"}
    if not bars:
        return result
    if len(bars) > 550:
        return {**result, "reason": "too_many_bars"}
    normalized = []
    for daily in bars:
        try:
            day = date.fromisoformat(daily["date"])
            if day.isoformat() != daily["date"] or day.weekday() > 4:
                return {**result, "reason": "invalid_bar_date"}
            if day > date.fromisoformat(session_date):
                return {**result, "reason": "future_bar"}
            values = [float(daily[key]) for key in ("open", "high", "low", "close", "volume")]
        except (ValueError, TypeError, KeyError, OverflowError):
            return {**result, "reason": "missing_or_invalid_bar"}
        if not all(math.isfinite(value) for value in values):
            return {**result, "reason": "nonfinite_bar"}
        if any(value <= 0 for value in values[:4]):
            return {**result, "reason": "zero_or_negative_price"}
        if values[4] <= 0:
            return {**result, "reason": "zero_or_negative_volume"}
        opening, high, low, close, volume = values
        if not low <= min(opening, close) <= max(opening, close) <= high:
            return {**result, "reason": "inconsistent_ohlc"}
        normalized.append((day, close, volume))
    normalized.sort()
    if len({row[0] for row in normalized}) != len(normalized):
        return {**result, "reason": "duplicate_bar_date"}
    result["last_bar_date"] = normalized[-1][0].isoformat()
    if result["last_bar_date"] != session_date:
        return {**result, "reason": "stale_bars"}
    if len(normalized) < params.min_bars:
        return {**result, "reason": "insufficient_history"}
    # A missing weekday may be an exchange holiday: never invent a session.
    # Large unexplained gaps are data/suspension diagnostics, not a weak return.
    if any((right[0] - left[0]).days > 4 for left, right in zip(normalized, normalized[1:])):
        return {**result, "reason": "history_gap_or_suspension"}
    price = normalized[-1][1]
    try:
        trailing_products = [c * v for _, c, v in normalized[-params.liquidity_sessions:]]
        dollar_volume = math.fsum(trailing_products) / params.liquidity_sessions
    except OverflowError:
        return {**result, "reason": "nonfinite_metric"}
    returns = {"return_3m": price / normalized[-1 - params.short_sessions][1] - 1,
               "return_6m": price / normalized[-1 - params.long_sessions][1] - 1}
    if not all(math.isfinite(value) for value in (dollar_volume, *returns.values())):
        return {**result, "reason": "nonfinite_metric"}
    result.update(ohlcv_validity="valid", price=price, avg_dollar_volume_20=dollar_volume, **returns)
    result["reason"] = ("price_out_of_band" if not params.min_price <= price <= params.max_price
                        else "low_dollar_volume" if dollar_volume < params.min_dollar_volume else None)
    return result


def rank_momentum(rows: list[dict], params: WatchParameters) -> list[dict]:
    """Average-tie cross-sectional ranks divided by N; final ties symbol ASC."""
    ranked = [dict(row) for row in rows]
    count = len(ranked)
    for metric, output in (("return_3m", "percentile_3m"), ("return_6m", "percentile_6m")):
        ordered = sorted(ranked, key=lambda row: (row[metric], row["symbol"]))
        start = 0
        while start < count:
            end = start + 1
            while end < count and ordered[end][metric] == ordered[start][metric]:
                end += 1
            percentile = ((start + 1 + end) / 2) / count
            for row in ordered[start:end]:
                row[output] = percentile
            start = end
    for row in ranked:
        row["score"] = params.short_weight * row["percentile_3m"] + params.long_weight * row["percentile_6m"]
    ranked.sort(key=lambda row: (-row["score"], row["symbol"]))
    for rank, row in enumerate(ranked, 1):
        row["rank"] = rank
    return ranked

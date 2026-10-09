
# AGENTS.md — usa_stock_finder

## 1. Project Mission

USA Stock Finder is a Python-based U.S. equity
analysis and trading-signal system.

The live strategy combines:
- Quantus-sourced growth/value stock candidates
- Mark Minervini-style trend selection
- Price/volume-based entry risk filters
- Stop Loss, Trailing Stop, AVSL, and other exits
- Portfolio sizing and Telegram notifications

Primary engineering priorities:
1. Preserve intended investment behavior.
2. Prevent unsafe new-buy recommendations.
3. Keep decisions deterministic and reproducible.
4. Prefer minimal, testable changes.
5. Maintain reliable unattended daily operation.

Do not optimize for code elegance at the expense
of trading correctness.

## 2. Source of Truth

Before modifying code:
- Inspect the actual current implementation.
- Read relevant tests and configuration.
- Check existing documentation and recent changes.
- Trace upstream and downstream consumers.

The current production implementation is the
source of truth for existing behavior.

Documentation can be outdated. Never assume a
function or feature exists without checking.

If documentation and code disagree, identify
the discrepancy rather than silently choosing.

## 3. Repository Map

Important modules:

- main.py: daily orchestration and buy funnel
- config.py: runtime and strategy configuration
- stock_analysis.py: trend and OHLCV analysis
- stock_operations.py: broker account integration
- sell_signals.py: sell decisions and priority
- trailing_stop.py: trailing stop implementation
- original_avsl.py: original AVSL calculations
- telegram_utils.py: notification formatting
- live_performance_logger.py: performance records
- trend_expansion/: research-only pool utilities
- backtests/: backtesting components
- tests/: unit and integration tests
- docs/: implementation and design references

Inspect the actual call graph before making changes.

## 4. Investment Strategy Invariants

### 4.1 Candidate Universe

The current live entry universe comes from
portfolio/portfolio.csv.

Preserve the current Quantus candidate workflow
unless explicitly instructed otherwise.

Do not:
- Automatically union historical Quantus snapshots.
- Treat old candidates as currently eligible.
- Silently replace the live candidate source.
- Activate research-only pools in production.

The Trend Expansion Pool is intended to
supplement the Core Quant Pool, not replace it.

Research infrastructure must not change live
selection without an explicit rollout request.

### 4.2 Buy Funnel

Preserve the existing production buy funnel:

1. Load and validate entry candidates.
2. Apply exchange and tradability checks.
3. Apply trend and correlation selection.
4. Apply stop-loss cooldown.
5. Apply event quarantine.
6. Apply pinned-price special-situation filtering.
7. Evaluate sell decisions.
8. Calculate investment sizing and quantities.
9. Generate Telegram recommendations.
10. Persist tracking and performance records.

This is a conceptual ordering.
Inspect the current implementation for exact
dependencies and execution semantics.

A rejected new-buy candidate must not reappear
in downstream sizing, quantities, or Telegram
new-buy recommendations.

Maintain accurate exclusion diagnostics.

### 4.3 Actual Holdings vs Tracked Symbols

These represent different states:

- us_stock_holdings:
  Confirmed broker-account holdings.

- prev_tracked_items:
  Previously persisted tracking state loaded from
  data/data.json.

data/data.json is not proof of actual ownership.

Event-quarantine exemptions must use only
confirmed broker holdings.

Tracked-only symbols must not bypass quarantine.

Preserve the intentional event-quarantine
exemption for actual holdings, which maintains
existing additional-buy behavior.

Do not generalize this exemption to other filters
without explicit authorization.

### 4.4 Special-Situation Protection

Avoid new-buy recommendations for securities
showing suspicious event-driven price behavior,
including merger-arbitrage or take-private-like
pinned prices.

Preserve detection of:
- Large event-driven price gaps
- Abnormally flat post-event trading
- Post-event volatility compression
- Cases where ordinary ATR remains contaminated
  by the original event gap

The detector must distinguish recent post-gap
volatility from the event jump itself.

Avoid introducing unnecessary external news or
LLM dependencies into trading decisions.

Do not weaken protection merely to increase
the number of buy candidates.

### 4.5 Sell Decisions

Preserve existing sell priority and semantics.

Refer to sell_signals.py and existing tests for
the authoritative precedence.

The documented priority is:
1. Stop Loss
2. Special Situation Take Profit
3. Trailing Stop
4. AVSL
5. Trend Exit

Original AVSL uses deterministic OHLCV data.

Preserve strict AVSL comparison semantics:
latest_close < latest_avsl

Do not silently alter:
- Exit thresholds
- Priority ordering
- Effective holding-high calculations
- Trailing stop activation
- Sell quantities or reason codes

Strategy changes require explicit justification
and regression coverage.

### 4.6 Investment Sizing

Preserve existing cash, reserve, and allocation
semantics unless the task explicitly changes them.

Do not introduce hidden sizing adjustments.

Ensure that:
- Rejected candidates do not receive allocations.
- Final buy candidates match sizing inputs.
- Share quantities reflect approved candidates.
- Telegram output agrees with calculated quantities.

## 5. Data and Runtime Safety

Prefer deterministic OHLCV and metadata-based
rules for production trading decisions.

Avoid unnecessary:
- External API dependencies
- Real-time polling
- LLM-based trade classification
- Expensive or fragile runtime operations

Handle missing, stale, invalid, and non-finite
market data explicitly.

Do not silently convert missing data into a
valid trading signal.

Preserve existing behavior unless an explicit
safety correction is required.

Never expose API keys, account credentials,
Telegram tokens, or private account information.

Do not modify real portfolio or runtime state
as a side effect of tests.

Use isolated fixtures, temporary directories,
and mocked broker/network integrations.

## 6. Testing Requirements

Use pytest and existing test conventions.

For every behavior change:

1. Add a deterministic regression test.
2. Test the expected positive case.
3. Test an important negative case.
4. Test boundary conditions where relevant.
5. Test downstream integration when needed.

For buy-funnel changes, verify:
- Selection and exclusion results
- Investment sizing inputs
- Share quantities
- Telegram new-buy recommendations
- Exclusion counts and reason diagnostics

For holding-related changes, verify:
- Broker-held symbols
- Tracked-only symbols
- New symbols absent from both sets

For special-situation changes, include:
- PRTH-like pinned-price behavior
- Recent event-quarantine behavior
- Expired quarantine with active pinning
- Normal momentum candidates
- Invalid or insufficient OHLCV history

Use synthetic price series with deterministic
dates and expected outcomes.

Mock external services in automated tests.

Do not replace an end-to-end regression test
with only a helper-level unit test.

## 7. Quality and CI

Project runtime: Python 3.12+.

Use existing dependencies and coding conventions.

Before completing a PR, run when applicable:

- pytest
- pylint on tracked Python files
- python -m compileall .

For Docker-related changes, verify the build.

The repository CI also validates Docker images
for linux/amd64 and linux/arm64.

Do not introduce unrelated dependencies,
large refactors, or formatting-only changes.

If a check cannot run, report the limitation.
Never claim that unexecuted tests passed.

## 8. Change Management

Prefer the smallest safe change.

Do not:
- Modify unrelated trading rules.
- Change parameter defaults without approval.
- Refactor working paths without a clear need.
- Add speculative features.
- Remove useful diagnostics without considering
  operational impact.
- Hide exceptions that affect trade decisions.

Preserve backward compatibility for existing
configuration and persisted data when possible.

Treat strategy changes separately from refactoring.

If the task has multiple stages, implement only
the requested stage and document dependencies.

## 9. Observability and Telegram

Daily Telegram messages should prioritize
actionable investment information.

Keep detailed debugging data in logs rather
than routine user-facing notifications.

Preserve important information:
- New-buy recommendations
- Sell recommendations and reasons
- Relevant share quantities
- Critical failures and risk warnings

Keep diagnostic counts available for debugging
and regression testing, even if routine Telegram
messages are simplified.

## 10. Completion Report

When completing a task, report:

1. Root cause or implementation objective
2. Files changed
3. Trading behavior before and after
4. Tests executed and their results
5. CI status, if available
6. Remaining risks or limitations

For strategy-affecting changes, explicitly state:
- Whether candidate selection changed
- Whether buy/sell decisions changed
- Whether investment quantities changed
- Whether Telegram behavior changed

Do not claim verification without evidence.

## 11. General Principle

Protect live trading correctness first.

Prefer:
- Reproducibility over cleverness
- Deterministic rules over opaque heuristics
- Small changes over broad rewrites
- Regression tests over assumptions
- Operational stability over complexity

Explicit user instructions may authorize
intentional strategy changes.

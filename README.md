# USA Stock Finder

미국 주식 자동 분석 및 트레이딩 신호 생성 시스템

## 📋 개요

이 프로젝트는 Mark Minervini의 트레이딩 원칙과 Buff Dormeier의 AVSL(Average Volume Support Level) 방법론을 기반으로 한 자동화된 주식 분석 시스템입니다. 기술적 지표를 활용하여 매수/매도 신호를 생성하고 텔레그램으로 알림을 전송합니다.

## ⚠️ 면책 조항

**이 소프트웨어는 교육 및 연구 목적으로 제공됩니다. 실제 투자 결정에 사용하기 전에 충분한 검토와 테스트를 수행하시기 바랍니다. 투자 손실에 대한 책임은 사용자에게 있습니다.**

## 🎯 주요 기능

- **기술적 분석**: 이동평균선, 가격-거래량 상관관계 분석
- **트렌드 분석**: 52주 고가/저가 기반 트렌드 유효성 검증
- **매수/매도 신호**: 3단계 매도 시스템 (Stop Loss → Trailing Stop → AVSL → Trend)
- **포트폴리오 관리**: 자동 투자 금액 계산 및 분배
- **텔레그램 알림**: 실시간 매수/매도 신호 알림

## 🛠️ 기술 스택

- **Python 3.12+**
- **yfinance**: 주식 데이터 수집
- **pandas/numpy**: 데이터 분석
- **mojito**: 한국투자증권 API 연동
- **python-telegram-bot**: 텔레그램 알림

## 📦 설치

1. 저장소 클론
```bash
git clone https://github.com/k11tos/usa_stock_finder.git
cd usa_stock_finder
```

2. 가상 환경 생성 및 활성화
```bash
python -m venv env
source env/bin/activate  # Windows: env\Scripts\activate
```

3. 의존성 설치
```bash
pip install -r requirements.txt
```

### Docker를 사용한 실행 (권장)
```bash
# GitHub Container Registry에서 이미지 가져오기
docker pull ghcr.io/k11tos/usa-stock-finder:latest

# 실행
docker run --env-file .env ghcr.io/k11tos/usa-stock-finder:latest
```

또는 로컬에서 빌드:
```bash
docker build -t usa-stock-finder .
docker run --env-file .env usa-stock-finder
```

## ⚙️ 설정

1. `.env` 파일 생성
```bash
cp .env.example .env
```

2. 환경 변수 설정
```env
# 한국투자증권 API
ki_app_key=your_api_key
ki_app_secret_key=your_secret_key
account_number=your_account_number

# 텔레그램
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# 전략 파라미터 (선택사항)
STOP_LOSS_PCT=0.10
CORRELATION_THRESHOLD_STRICT=50.0
# ... 기타 파라미터는 config.py 참조
```

3. 포트폴리오 CSV 파일 준비
```bash
# portfolio/portfolio.csv 파일에 분석할 종목 목록 추가
# 형식: Code,Name,Market
```

## 🚀 사용법

### 기본 실행
```bash
python main.py
```

### 스케줄 실행 (cron 예시)
```bash
# 매일 오후 8시 (KST) 실행
0 20 * * * cd /path/to/usa_stock_finder && /path/to/env/bin/python main.py
```


## 📈 Live Performance Logs

런타임 실행 시 실제 운용 성과 추적을 위한 CSV 로그가 생성됩니다.

- `data/live/trade_signals.csv`: 매수/매도 신호 로그 (run_id, side, symbol, quantity, price, reason 등)
- `data/live/account_snapshots.csv`: 일별 계좌/보유 스냅샷 (현금, 총자산, 종목별 평가손익 등)
- `data/live/cash_flows.csv` (선택): 입출금/배당/수수료 로그 (`date,amount,currency,type,memo`)

특징:
- append-only 저장 (기존 기록 보존)
- 파일이 없으면 헤더 자동 생성
- 실행 단위 `run_id`는 KST 기준 `YYYYMMDD_HHMMSS` 형식으로 생성

## 📊 Performance Report (Browser HTML)

`tools/performance_report.py`는 기본 산출물(CSV/JSON/Markdown)과 함께 정적 `index.html` 리포트를 생성합니다.

기본 출력(기존 호환):
- `outputs/performance/equity_curve.csv`
- `outputs/performance/benchmark_comparison.csv`
- `outputs/performance/performance_summary.json`
- `outputs/performance/performance_report.md`
- `outputs/performance/index.html`

배포 옵션:
- `--publish-latest`: `outputs/performance/latest/`에 리포트 번들 복사
- `--history`: `outputs/performance/history/<report_run_id>/`에 리포트 번들 복사
- `--report-run-id`: 미지정 시 KST 기준 `YYYYMMDD_HHMMSS` 자동 생성

예시:
```bash
python tools/performance_report.py \
  --output outputs/performance \
  --cash-flows data/live/cash_flows.csv \
  --publish-latest \
  --history
```

`--cash-flows` 파일이 존재하면 Modified Dietz 방식의 현금흐름 보정 수익률을 함께 계산합니다.  
파일이 없거나 비어 있으면 기존과 동일하게 단순 equity 기반 수익률만으로 동작하며 호환성을 유지합니다.

`type` 허용값:
- `deposit`
- `withdrawal`
- `dividend`
- `fee`
- `tax`
- `adjustment`

리포트 번들에는 아래 파일이 포함됩니다:
- `index.html`
- `performance_report.md`
- `performance_summary.json`
- `equity_curve.csv`
- `benchmark_comparison.csv`
- `charts/cumulative_return.png`
- `charts/drawdown.png`
- `charts/excess_return.png`

## Backtesting

`run_backtest.py`로 CSV 기반 백테스트를 실행할 수 있습니다.

**필수 입력 파일**
- `--prices`: 가격 이력 CSV
- `--candidates`: 후보 스냅샷 CSV

**필수 입력 컬럼**
- 기본(required)
  - `--prices`: `date`, `symbol`, `close`
  - `--candidates`: `asof_date`, `symbol`, `universe_type`
- 모드별 추가(required when used)
  - `--universe quantus_minervini`: `market_cap`, `avg_dollar_volume`, `rs_score`, `pct_below_52w_high`
  - `--entry trend_relaxed|trend_basic|trend_strict`: `close`, `sma50`, `sma150`, `sma200`, `high_52w`, `low_52w`, `rs_score`
  - `--exit avsl`: `close`, `avsl` (`avsl`는 사전 계산된 일별 AVSL 스탑 값, 유효한 양수 숫자 필수)

**지원 모드**
- `--universe`: `quantus`, `quantus_minervini`
- `--entry`: `none`, `trend_relaxed`, `trend_basic`, `trend_strict`
- `--exit`: `hold_fixed`, `stop_loss`, `trailing`, `trend_exit`, `avsl`

> 백테스트 `avsl`는 **근사(approximation)** 입니다.  
> 라이브 코드처럼 VPCI/동적 길이 기반 AVSL를 백테스트 엔진 안에서 직접 계산하지 않고,
> 입력된 가격 이력의 `avsl` 컬럼(사전 계산값)을 사용해 `close < avsl` 조건만 평가합니다.
> 이는 비교 실험의 결정론/재현성을 위한 의도적 분리입니다. `avsl` 입력이 누락/무효이면
> AVSL 백테스트는 실패(fail fast)하도록 설계되어, 조용히 잘못된 결과가 생성되지 않게 합니다.

**예시 명령어**
```bash
python run_backtest.py \
  --prices data/backtest/prices.csv \
  --candidates data/backtest/candidates.csv \
  --universe quantus_minervini \
  --entry trend_basic \
  --exit trailing \
  --start-date 2024-01-01 \
  --end-date 2024-12-31 \
  --top-n 5 \
  --save-output
```

**출력 위치**
- `--save-output` 사용 시: 기본 `outputs/backtests/<run_tag>/`
- 주요 파일: `trades.csv`, `equity_curve.csv`, `summary_metrics.json`,
  `candidate_snapshot.csv`, `candidate_snapshot_universe.csv`,
  `candidate_snapshot_entry.csv`, `candidate_snapshot_selected.csv`, `lm_review_log.jsonl`
- `--output-root`로 출력 루트 경로를 변경할 수 있습니다.

### 백테스트 출력 해석 가이드 (진단 중심)

- **포트폴리오 상태(고수준)**
  - 엔진은 `cash + open_positions(시가평가)`로 일별 equity를 계산합니다.
  - 리밸런스 시점마다 신규 진입은 "해당 시점 가용 현금"을 진입 후보 수로 균등 분할합니다.
  - 이미 보유 중인 심볼은 같은 리밸런스에서 중복 진입하지 않습니다.
  - 데이터 종료 시 미청산 포지션은 마지막 관측 종가로 강제 종료(`exit_reason=end_of_data`)됩니다.

- **단계별 후보 스냅샷(`candidate_snapshot_*.csv`)**
  - `candidate_snapshot_universe.csv`: 유니버스 필터 통과 집합
  - `candidate_snapshot_entry.csv`: 엔트리 필터 통과 집합
  - `candidate_snapshot_selected.csv`: 최종 `top_n` 선정 집합
  - 각 파일에는 `rebalance_date`, `execution_date`, `stage`, `universe`, `entry_filter`, `exit_rule`, `rank_col`, `top_n` 메타데이터가 포함되어, "어떤 리밸런스가 어떤 거래일에 실행되었는지"를 추적할 수 있습니다.

- **`trades.csv` 진단 필드(핵심)**
  - 기본 체결 정보: `symbol`, `entry_date`, `exit_date`, `entry_price`, `exit_price`, `quantity`, `pnl`
  - 실험 컨텍스트: `universe`, `entry_filter`, `exit_rule`, `exit_reason`
  - 진입 추적: `entry_signal_date`(선정 스냅샷 날짜), `rank_value`(선정 시 사용한 랭크 값), `holding_days`
  - 포지션 품질: `mfe_pct`, `mae_pct`

- **MFE / MAE 정의**
  - `mfe_pct`(Maximum Favorable Excursion): 진입 후 보유 중 관측된 **최대 유리 수익률(%)**
  - `mae_pct`(Maximum Adverse Excursion): 진입 후 보유 중 관측된 **최대 불리 수익률(%)**
  - 둘 다 일별 `close` 기준으로 계산되며, 장중 고가/저가 기반 excursion은 반영하지 않습니다.

- **비교 모드(`--compare-basic`)**
  - 4개 고정 조합(`quantus/none`, `quantus/trend_basic`, `quantus_minervini/none`, `quantus_minervini/trend_basic`; 공통 `hold_fixed`)을 일괄 실행해 콘솔 요약을 출력합니다.
  - 빠른 상대 비교용 기능이며, 파라미터 스윕/통계적 유의성 검정까지 자동 제공하지는 않습니다.

- **제한사항 / AVSL 근사**
  - `--exit avsl`는 여전히 **근사 모델**입니다. 백테스트 엔진 내부에서 VPCI/동적 길이 AVSL를 재계산하지 않고, 입력 CSV의 `avsl` 컬럼을 그대로 사용해 `close < avsl`만 판정합니다.
  - 따라서 AVSL 백테스트 품질은 입력 `avsl` 시계열 품질에 직접 의존합니다. `avsl`가 누락/비정상(양수 수치 아님)이면 fail-fast로 중단됩니다.

### LM 후보 정성 필터 로그 스키마 (준비 단계)

정성 필터(LLM 또는 수동 심사) 결과 비교를 위해 JSONL 로그 포맷을 추가했습니다. 현재 단계에서는 **실제 LLM 호출 없이** 스키마와 저장 유틸만 제공합니다.

- 파일: `outputs/backtests/<run_tag>/lm_review_log.jsonl`
- 레코드 필드:
  - `date` (`YYYY-MM-DD`)
  - `symbol` (티커)
  - `decision` (`passed` | `rejected` | `skipped`)
  - `confidence` (0.0~1.0)
  - `reason_codes` (짧은 enum code 배열)
  - `final_action` (`keep` | `drop` | `defer`)

이 로그는 향후 아래 3개 코호트 성과를 비교 분석하기 위한 기반으로 사용됩니다.
- raw candidate
- LM 통과 candidate
- LM 거절 candidate

## 📊 전략 파라미터

주요 전략 파라미터는 `config.py`에서 환경 변수로 설정할 수 있습니다:

- **이동평균**: MA_50_DAYS, MA_150_DAYS, MA_200_DAYS
- **상관관계 임계값**: CORRELATION_THRESHOLD_STRICT, CORRELATION_THRESHOLD_RELAXED
- **손절 기준**: STOP_LOSS_PCT (기본값: 10%)
- **트레일링 스탑**: TRAILING_ATR_MULTIPLIER (기본값: 3.0)

자세한 내용은 `config.py` 파일을 참조하세요.

## 📁 프로젝트 구조

```
usa_stock_finder/
├── main.py              # 메인 실행 파일
├── config.py            # 설정 관리
├── stock_analysis.py     # 주식 분석 로직
├── stock_operations.py   # 계좌 조회 및 거래
├── sell_signals.py      # 매도 신호 평가
├── telegram_utils.py    # 텔레그램 알림
├── portfolio/           # 포트폴리오 CSV (gitignore)
└── data/                # 거래 데이터 (gitignore)
```

## 🧪 테스트

```bash
# 전체 테스트 실행
pytest

# 특정 테스트 파일 실행
pytest tests/test_main.py

# 커버리지 포함
pytest --cov=. --cov-report=html
```

## 📝 라이선스

이 프로젝트는 MIT 라이선스를 따릅니다. 자세한 내용은 `LICENSE` 파일을 참조하세요.

## 🙏 감사의 말

- **Mark Minervini**: 트레이딩 원칙 및 전략
- **Buff Dormeier**: AVSL 방법론


### Optional post-run AVSL monitoring

`main.py` can optionally generate a monitoring-only legacy-vs-original AVSL comparison after the normal daily run.
The monitor includes current holdings first and also checks final buy / not-sell symbols when available. It writes CSV and markdown artifacts to `outputs/avsl_monitor/latest/` and historical copies to `outputs/avsl_monitor/history/<run_date>/`. Monitor errors are logged as warnings and do not affect trading execution or Telegram buy/sell messages.

Environment variables:

- `AVSL_MONITOR_ENABLED` (default: `False`)
- `AVSL_MONITOR_TELEGRAM_ENABLED` (default: `False`) - must be explicitly set to `true` to send the compact monitoring-only Telegram summary; local artifacts are still generated when only `AVSL_MONITOR_ENABLED=true`
- `AVSL_MONITOR_OUTPUT_DIR` (default: `outputs/avsl_monitor`)

```env
AVSL_MONITOR_ENABLED=true
AVSL_MONITOR_TELEGRAM_ENABLED=false
AVSL_MONITOR_OUTPUT_DIR=outputs/avsl_monitor
```

### Optional auto refresh after daily run

`main.py` can optionally refresh the live performance report **after** it appends trade signals/account snapshots and saves `data/data.json`.
This step is failure-tolerant: report generation errors are logged as warnings and will not stop the daily signal run.

Environment variables:

- `PERFORMANCE_REPORT_ENABLED` (default: `false`)
- `PERFORMANCE_REPORT_OUTPUT_DIR` (default: `outputs/performance`)
- `PERFORMANCE_REPORT_BENCHMARKS` (default: `SPY,IWM`)
- `PERFORMANCE_REPORT_PUBLISH_LATEST` (default: `true`)
- `PERFORMANCE_REPORT_HISTORY` (default: `false`)
- `PERFORMANCE_REPORT_TELEGRAM_ENABLED` (default: `false`)
- `PERFORMANCE_REPORT_URL` (optional, example: `http://breadpig:8091/latest/`)

`.env` example:

```env
PERFORMANCE_REPORT_ENABLED=true
PERFORMANCE_REPORT_OUTPUT_DIR=outputs/performance
PERFORMANCE_REPORT_BENCHMARKS=SPY,IWM
PERFORMANCE_REPORT_PUBLISH_LATEST=true
PERFORMANCE_REPORT_HISTORY=true
PERFORMANCE_REPORT_TELEGRAM_ENABLED=true
PERFORMANCE_REPORT_URL=http://breadpig:8091/latest/
```

`PERFORMANCE_REPORT_URL`는 텔레그램 요약 알림에서 최신 HTML 리포트로 이동하는 링크입니다.  
공개 인터넷 URL 대신 **Tailscale / Cloudflare Access 등으로 보호된 private 페이지**를 사용하세요.

## ⚠️ 주의사항

- 실제 거래 전에 충분한 백테스팅과 검증을 수행하세요
- API 키와 계좌 정보는 절대 공개하지 마세요
- 투자 손실에 대한 책임은 사용자에게 있습니다
- 이 시스템은 투자 조언이 아닙니다

## 🛡️ 보안

### Pre-commit Hook
프로젝트에는 실수로 민감한 파일을 커밋하는 것을 방지하는 pre-commit hook이 포함되어 있습니다.

**자동으로 설정됨**: 저장소를 클론하면 hook이 자동으로 활성화됩니다.

**수동 설정** (필요한 경우):
```bash
chmod +x .git/hooks/pre-commit
```

**테스트**:
```bash
.git/hooks/pre-commit-test.sh
```

Hook이 차단하는 항목:
- `.env` 파일 및 환경 변수 파일
- `portfolio/*.csv` 파일
- `data/*.json` 파일
- 코드에 하드코딩된 API 키/토큰

## 📧 문의

이슈나 질문이 있으시면 GitHub Issues를 이용해주세요.

## 📉 Live Performance Report (vs SPY/IWM)

라이브 로그(`data/live/account_snapshots.csv`, `data/live/trade_signals.csv`)를 사용해
전략 성과를 SPY/IWM 벤치마크와 비교하는 리포트를 생성할 수 있습니다.

```bash
python tools/performance_report.py
```

옵션 예시:

```bash
python tools/performance_report.py \
  --snapshots data/live/account_snapshots.csv \
  --trades data/live/trade_signals.csv \
  --benchmarks SPY IWM \
  --output outputs/performance \
  --start-date 2026-01-01 \
  --end-date 2026-03-31
```

출력 파일:
- `outputs/performance/equity_curve.csv`
- `outputs/performance/benchmark_comparison.csv`
- `outputs/performance/performance_summary.json`
- `outputs/performance/performance_report.md`

주의:
- 외부 입출금이 있었던 경우 단순 equity 기반 수익률은 왜곡될 수 있습니다.
- 향후 cash-flow 로그를 추가하면 정확도를 개선할 수 있습니다.

## 🧾 Dry-run Special Review (Explanation-only)

가격 기반 필터(`event_quarantine`, `pinned_price`)로 이미 제외된 소수 심볼에 대해,
사후 설명/수동 확인용 리뷰 패킷을 생성하는 도우미입니다.

```bash
python tools/dry_run_special_review.py --symbol-reason GAPX:event_quarantine EWCZ:pinned_price
```

JSON 출력:

```bash
python tools/dry_run_special_review.py --symbol-reason GAPX:event_quarantine --json
```

원칙:
- 이 도구는 **dry-run/report 전용**이며 매수/매도 결정에 연결되지 않습니다.
- 트레이딩 의사결정은 기존처럼 **결정론적 가격 기반 로직**만 사용합니다.
- 뉴스 API 키(`NEWS_API_KEY`)가 없어도 동작하며, 이 경우 가격 기반 리뷰만 출력합니다.
- 유료 API/시크릿은 이 도구에 필수로 요구되지 않습니다.

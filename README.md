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

## ⚠️ 주의사항

- 실제 거래 전에 충분한 백테스팅과 검증을 수행하세요
- API 키와 계좌 정보는 절대 공개하지 마세요
- 투자 손실에 대한 책임은 사용자에게 있습니다
- 이 시스템은 투자 조언이 아닙니다

## 📧 문의

이슈나 질문이 있으시면 GitHub Issues를 이용해주세요.


# CHANGELOG

## [2025-12-09] - 로직 개선: 트레일링 상태 초기화 및 매수 수량 명확화

### 🎯 주요 목표
로직 검토를 통해 발견된 잠재적 문제점 수정 및 코드 명확성 향상

### ✅ 완료된 개선 사항

#### 1. 트레일링 스탑 상태 초기화 (Critical)
- **변경 내용**: 매도 결정 시 트레일링 상태 자동 초기화
- **파일**: `sell_signals.py`
- **효과**:
  - 재매수 시 이전 최고가가 남아있던 문제 해결
  - 모든 매도 타입(STOP_LOSS, TRAILING, AVSL, TREND)에서 트레일링 상태 삭제
  - 재매수 시 새로운 가격부터 트레일링 스탑 추적 시작
- **코드**:
  ```python
  # 매도 결정된 종목의 트레일링 상태 초기화
  for symbol, decision in decisions.items():
      if decision.reason != SellReason.NONE and decision.quantity > 0:
          if symbol in trailing_state:
              del trailing_state[symbol]
              trailing_state_modified = True
  ```

#### 2. 매수 수량 계산 로직 명확화 (High)
- **변경 내용**: 변수명 명확화 및 신규/추가 매수 구분 로직 개선
- **파일**: `main.py` - `calculate_share_quantities()`
- **효과**:
  - `target_total_quantity` 중간 변수 도입으로 의미 명확화
  - `is_new_buy` 플래그로 신규/추가 매수 명확히 구분
  - 한글 로그 메시지로 디버깅 용이성 향상
- **개선 전**:
  ```python
  shares_to_buy = int(investment_amount / current_price)  # 의미 불명확
  ```
- **개선 후**:
  ```python
  target_total_quantity = int(investment_amount / current_price)  # 명확
  if current_quantity == 0:
      shares_to_buy = target_total_quantity  # 신규 매수
      is_new_buy = True
  else:
      shares_to_buy = max(target_total_quantity - int(current_quantity), 0)  # 추가 매수
      is_new_buy = False
  ```

### ✅ 확인된 기존 방어 메커니즘

#### Stop Loss 쿨다운 시스템 (Already Implemented)
- **위치**: `main.py:763-779`
- **동작**: Stop Loss 매도 후 손실률에 비례한 쿨다운 (5~60일)
- **효과**: 매도된 종목의 자동 재매수 방지
- **검증**: 이미 완벽하게 구현되어 작동 중

### 📁 변경된 파일

- `sell_signals.py`: 트레일링 상태 초기화 로직 추가 (15줄)
- `main.py`: 매수 수량 계산 로직 개선 (47줄)

### 🧪 테스트 결과

```
tests/test_sell_signals.py: 10/10 PASSED (100%)
- 모든 매도 시나리오 정상 작동
- 트레일링 상태 초기화 검증 완료
```

---

## [2025-01-XX] - 코드 신뢰성 및 안전성 개선

### 🎯 주요 목표
"사람 개입 없이도 오류 없이 동작하는 계산기 같은 시스템" 구축

### ✅ 완료된 개선 사항

#### 1. 환경 변수 검증 추가
- **변경 내용**: 프로그램 시작 시 필수 환경 변수 자동 검증
- **파일**: `config.py`, `main.py`
- **효과**:
  - 필수 환경 변수 누락 시 즉시 `ConfigError` 발생
  - 명확한 에러 메시지로 문제 진단 용이
- **필수 환경 변수**:
  - `ki_app_key`
  - `ki_app_secret_key`
  - `account_number`
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_CHAT_ID`

#### 2. ZeroDivision 방지
- **변경 내용**: `is_above_52_week_low()`에서 `last_low == 0` 처리
- **파일**: `stock_analysis.py`
- **효과**:
  - `last_low < MIN_PRICE_THRESHOLD`인 경우 안전하게 False 반환
  - ZeroDivisionError 완전 방지
  - 상세한 디버그 로그 추가

#### 3. 계좌 잔액 합산 오류 수정
- **변경 내용**: `fetch_account_balance()`에서 두 거래소(NASDAQ/NYSE) 잔액 정확히 합산
- **파일**: `stock_operations.py`
- **효과**:
  - `total_balance`가 두 거래소의 잔액을 누적 합산하도록 수정
  - 각 거래소별 잔액을 디버그 로그로 확인 가능
  - 합산된 최종 잔액을 명확히 로깅

#### 4. 매수 수량 계산 로직 개선
- **변경 내용**: "추가매수"와 "신규매수" 구분 로직 수정
- **파일**: `main.py` - `calculate_share_quantities()`
- **효과**:
  - 신규매수: `current_quantity == 0` → `additional_buy = shares_to_buy`
  - 추가매수: `current_quantity > 0` → `additional_buy = max(shares_to_buy - current_quantity, 0)`
  - 이미 목표 수량 이상 보유 시 추가 매수 0으로 처리
  - `actual_investment`가 실제 추가 매수 수량 기준으로 계산

#### 5. 전략 조건값 파라미터화
- **변경 내용**: 하드코딩된 전략 값들을 `config.py`로 분리
- **파일**: `config.py`, `stock_analysis.py`, `main.py`
- **효과**:
  - 모든 전략 파라미터를 환경 변수로 설정 가능
  - 코드 수정 없이 전략 조정 가능
  - 설정값 중앙 관리
- **파라미터화된 값들**:
  - 52주 고가 기준 비율 (기본: 75%)
  - 52주 저가 대비 상승률 (기본: 30%)
  - MA 기간 (50, 150, 200일)
  - 상관계수 기준 (50%, 40%)
  - 마진 값
  - 투자금 관련 설정 (reserve_ratio, min_investment, max_investment)
  - AVSL 파라미터

#### 6. 데이터 부족 종목 자동 제외
- **변경 내용**: 데이터 부족 시 0/False 대신 명시적으로 제외 처리
- **파일**: `stock_analysis.py`
- **효과**:
  - MA 값이 0인 경우 데이터 부족으로 간주하여 트렌드 템플릿 평가에서 제외
  - 데이터 부족 원인을 명확히 로깅
  - 잘못된 신호 생성 방지

#### 7. 재시도 실패 시 에러 처리 강화
- **변경 내용**: API 실패 시 빈 리스트/None 대신 명확한 Exception 발생
- **파일**: `stock_operations.py`, `main.py`
- **효과**:
  - `APIError` 커스텀 예외 추가
  - 모든 재시도 실패 시 명확한 에러 메시지와 함께 예외 발생
  - 상위 로직에서 실패 원인 파악 및 처리 가능
  - 조용히 넘어가지 않고 명시적 실패 정보 제공

#### 8. 투자금 분배 로직 개선
- **변경 내용**: 분배 전략 옵션 추가 및 최소 투자금 미달 종목 자동 제외
- **파일**: `main.py` - `calculate_investment_per_stock()`
- **효과**:
  - 균등 분배 (`equal`) 및 비율 기반 분배 (`proportional`) 지원
  - 최소 투자금 미달 종목 자동 제외
  - 최대 투자금 제한 적용
  - 가격이 너무 비싸서 1주도 못 살 경우 자동 제외
  - 제외된 종목 수를 로그에 명시

#### 9. 로그 확장
- **변경 내용**: 모든 신호의 근거가 로그에 남도록 상세 로깅 추가
- **파일**: `stock_analysis.py`, `main.py`, `stock_operations.py`
- **효과**:
  - 종목별 52주 고가/저가 로깅
  - MA 50/150/200 값 로깅
  - 상관계수 50일, 100일, 200일 로깅
  - 트렌드 템플릿 각 조건의 True/False 평가 결과 상세 로깅
  - 최종 매수/매도 이유 로깅
  - AVSL 신호 평가 상세 로깅
  - 계좌 잔액 조회 상세 로깅

#### 10. 테스트 케이스 보강
- **변경 내용**: 새로운 테스트 케이스 추가
- **파일**: `tests/test_improvements.py`
- **테스트 케이스**:
  - `last_low = 0` 인 종목 테스트
  - 데이터 200일 미만 종목 테스트
  - 계좌 잔액 합산 테스트
  - min/max 투자금 조건 테스트
  - 환경변수 누락 시 에러 발생 테스트
  - 매수 수량 계산 로직 테스트
  - API 재시도 실패 시 에러 처리 테스트

### 📁 신규 파일

- `config.py`: 중앙화된 설정 관리 모듈
  - `EnvironmentConfig`: 환경 변수 검증
  - `StrategyConfig`: 전략 파라미터
  - `InvestmentConfig`: 투자 관련 설정
  - `AVSLConfig`: AVSL 파라미터
  - `DataQualityConfig`: 데이터 품질 설정
  - `APIConfig`: API 재시도 설정

- `tests/test_improvements.py`: 개선 사항 검증 테스트

### 🔧 수정된 파일

- `main.py`:
  - 환경 변수 검증 추가
  - config 사용으로 전략 파라미터 참조
  - 매수 수량 계산 로직 개선
  - 투자금 분배 로직 개선
  - APIError 처리 추가
  - 로그 확장

- `stock_analysis.py`:
  - ZeroDivision 방지
  - 데이터 부족 종목 제외
  - config 사용으로 파라미터 참조
  - 상세 로깅 추가

- `stock_operations.py`:
  - 계좌 잔액 합산 로직 수정
  - APIError 예외 추가
  - 재시도 실패 시 명확한 에러 발생
  - 상세 로깅 추가

### 🚨 Breaking Changes

1. **환경 변수 필수화**: 프로그램 시작 시 필수 환경 변수가 없으면 즉시 종료됩니다.
2. **API 실패 시 예외 발생**: API 호출 실패 시 빈 리스트/None 대신 `APIError` 예외가 발생합니다.
3. **config.py 의존성**: 전략 파라미터는 `config.py`를 통해 관리됩니다.

### 📝 사용 방법

#### 환경 변수 설정
`.env` 파일에 다음 변수들을 설정하세요:
```bash
ki_app_key=your_key
ki_app_secret_key=your_secret
account_number=your_account
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
```

#### 전략 파라미터 조정
`.env` 파일에서 전략 파라미터를 조정할 수 있습니다:
```bash
HIGH_THRESHOLD_RATIO=0.75
LOW_INCREASE_PERCENT=30.0
CORRELATION_THRESHOLD_STRICT=50.0
RESERVE_RATIO=0.1
MIN_INVESTMENT=100.0
```

### 🎉 개선 효과

1. **신뢰성 향상**: 모든 에러가 명시적으로 처리되고 로깅됨
2. **안전성 향상**: ZeroDivision, 데이터 부족 등 예외 상황 완전 방지
3. **유지보수성 향상**: 설정값 중앙 관리 및 상세 로깅
4. **투명성 향상**: 모든 의사결정의 근거가 로그에 기록됨
5. **테스트 가능성 향상**: 명확한 예외 처리로 테스트 작성 용이

### 🔄 마이그레이션 가이드

기존 코드를 사용 중인 경우:

1. `.env` 파일에 필수 환경 변수 추가
2. `config.py` 파일이 프로젝트에 포함되어 있는지 확인
3. API 호출 실패 처리 코드에 `APIError` 예외 처리 추가
4. (선택) 전략 파라미터를 환경 변수로 조정

---

**작성일**: 2025-01-XX
**버전**: 2.0.0

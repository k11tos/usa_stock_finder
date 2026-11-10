# PR: KRW TWR의 명시적 수집 캘린더 및 Preview 검증

현재 체크아웃은 이미 주말을 포함한 실제 관측 구간을 계산하지만, 예정된
평일 수집 실패도 경고만 남기고 통과시킨다. 독립적으로 검증한 KST 관측
캘린더를 필수로 적용해 정상 비수집일과 실제 누락을 구분한다.

## 변경 파일

- `tools/krw_twr.py`: 읽기 전용 캘린더 로더, 날짜별 검증, 예정일 누락 시
  구간 실패 및 전체 TWR/MDD 무효화. 기존 실제 timestamp 기반 현금흐름
  경계, complete/verified 규칙, 검증 실패 뒤 재연결 금지 유지.
- `tools/performance_report.py`: `--krw-observation-calendar` 연결.
- `tools/krw_benchmarks.py`: 비교 불가 원인을 관측일·시리즈별로 보존.
- `tests/test_krw_observation_calendar.py`: 주말, 미국 휴장일, 한국 설날,
  예정일 누락, 캘린더 결측/미검증/오류, 중복 스냅샷 회귀 테스트.
- `tests/test_krw_twr.py`: 명시적 합성 캘린더 fixture. 기존 현금흐름 미검증,
  중간 입출금, 경계 입출금, 연결 TWR/MDD, 변동성 테스트 유지.
- `tests/test_krw_performance_charts.py`: 합성 캘린더 연결, 결측/신선도
  원인 검증, 리포트·차트·벤치마크 회귀 검증.
- `docs/krw_time_weighted_return.md`: 정책, CSV 계약, 운영 검증 절차.
- `docs/krw_twr_pr_notes.md`: 이 PR 설명 및 검증 기록.

## 기존 동작과 차이

이전에는 다일 구간의 현금흐름만 검증되면 평일 누락도 통과했다. 이제
각 KST 날짜의 수집 계획과 검증 근거가 필요하다. 확인된 `closed` 날짜는
건너갈 수 있지만 `scheduled` 누락은 전체 성과를 무효화한다. 휴장일도
실제 수집 정책에서 쉬는 날로 확인되어야 한다. 캘린더 없이 KRW 모드를
실행하면 N/A가 된다. legacy_usd 기본값, 기존 운영 리포트 경로, 전략,
후보 선정, 매매 판단, 주문, 수량·사이징, Telegram 동작은 변경하지 않았다.

## 검증

관련 7개 테스트 파일의 pytest 결과와 정적 검사는 아래 최종 검증 기록 참조.
모든 실행은 임시 경로의 합성 입력 및 모의 시세를 사용했다. 계좌, 운영
스냅샷, 실제 현금흐름 CSV를 조회하거나 수정하지 않았다. 외부 API 호출과
운영 전환도 수행하지 않았다.

`/workspace/krw-preview-synthetic/` 별도 출력에서 2026-10-19~11-10의
평일 17개 합성 스냅샷을 검증했다. SPY/IWM 및 과거 환율도 모의 데이터다.

| Preview | 결과 |
| --- | --- |
| valid | 16개 구간 검증, TWR +1.6%, MDD 0%, SPY/IWM 비교 가능 |
| missing-scheduled | 10/26 예정일 누락 검출, 전체 TWR/MDD N/A |
| unverified-flow | 마지막 구간 pending 검출, 전체 TWR/MDD N/A |

각 실행에서 스냅샷·현금흐름·캘린더 입력 바이트 불변을 확인했다.
검증 요약은 `verification.json`, 각 출력의 `performance_summary.json`,
`twr_curve.csv`, `benchmark_curve.csv`, `index.html`에서 확인할 수 있다.
혼합 관측 간격의 연율화 변동성은 N/A다.

## 잔여 위험 및 적용 범위

캘린더 근거의 정확성은 별도 운영 검토가 필요하다. 누락된 스냅샷을 보고
사후에 `closed`로 바꾸면 수집 실패를 숨길 수 있으므로 금지한다. 관측일
단위 정책으로 일중 실행 횟수나 예정 시각까지 검증하지 않는다. MDD는
실제 관측 지점에서만 계산하며 구간 중간 하락은 복원하지 않는다.
다른 관측 간격의 신뢰할 수 있는 연율화 정의를 추가하지 않았다.

사용자의 무입출금 확인을 CSV에 자동 반영하지 않는다. 실제 데이터의
각 정확한 관측 구간에 대한 complete/verified 검토와 캘린더 검증이 끝나기
전에는 운영 KRW TWR 성공을 주장할 수 없다. 원격 CI는 실행하지 않았고,
자동 운영 전환은 수행하지 않았다. 이 문서의 검증 기록은 PR 발행 전 로컬 검증 결과다.

## 최종 검증 기록

- pytest: `test_krw_twr`, `test_krw_observation_calendar`,
  `test_krw_performance_charts`, `test_performance_report`,
  `test_broker_equity_report`, `test_broker_equity_snapshots`,
  `test_live_performance_logger` — **383 passed**.
- 변경한 Python 파일 6개 pylint — **10.00/10**, 종료 코드 0.
- `python -m compileall -q .` — 통과.
- `git diff --check` — 통과.
- 합성 Preview 3종 — 예상 성과/실패 조건 및 입력 불변 검증 통과.
- 전체 pytest 및 원격 CI는 실행하지 않았다.

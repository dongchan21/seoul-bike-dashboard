# 실시간 따릉이 재고 수집기

Python 3.10 이상, 표준 라이브러리만 사용한다. 추가 pip 설치가 없다.

## 실행

프로젝트 폴더에서 다음을 실행한다.

```powershell
Set-Location 'D:\졸업프로젝트'
Copy-Item .env .env
# .env를 편집해 SEOUL_API_KEY에 발급받은 키 입력. 이미 .env가 있으면 복사 생략.
python -m backend.collect --once
python -m backend.collect --status
python -m backend.collect
```

마지막 명령은 즉시 한 번 수집하고 다음 5분 경계마다 반복한다. Ctrl+C로 종료한다.
Python 명령이 없다면 정상 설치된 Python 3.10 이상 실행 파일 경로를 사용한다.
현재 환경의 py 실행기는 이전 Microsoft Store Python 경로를 가리켜 실행되지 않았다.
키는 채팅이나 프런트엔드 코드에 붙이지 않는다.

키 발급·서비스 사용 신청: [서울 열린데이터광장 공식 데이터](https://data.seoul.go.kr/dataList/OA-15493/A/1/datasetView.do).
공식 예시의 HTTP 주소 openapi.seoul.go.kr:8088을 사용한다. 인증키가 URL 경로로 전송되므로 요청 URL은 로그에 남기지 않는다.

## 저장 위치

- data/inventory/raw/YYYY-MM-DD/실행ID/: 페이지별 원본 응답 gzip. 유효하지 않은 JSON 응답도 보존.
- data/inventory/inventory.sqlite3: 실행 이력과 대여소별 관측.
- runs: success / partial / failed / running, 건수, 오류 코드.
- observations: 실행별 재고·좌표·거치대 수·원본 거치율·수신 시각.
- slots: 성공한 실행만 5분 슬롯에 연결.
- latest_inventory 뷰: 마지막으로 완주한 수집의 모든 대여소.

원본과 DB 모두 기본적으로 D 프로젝트 내부에 저장된다. --data-dir로 다른 디스크를 지정할 수 있다.
데이터는 자동 삭제하지 않으므로 주기적으로 용량을 확인한다.

## 안정성 규칙

- 요청당 최대 1,000건. 짧은 마지막 페이지 또는 INFO-200까지 계속 요청한다.
- 총 대여소 수를 2,000으로 고정하지 않으며 list_total_count를 전역 합계로 가정하지 않는다.
- 네트워크·일시적 HTTP 오류·깨진 JSON은 최대 3회 재시도한다. 인증 오류는 재시도하지 않는다.
- 부분 실패는 partial로 보존하고 최신 성공 결과를 교체하지 않는다.
- 같은 슬롯의 성공 수집은 다시 실행해도 건너뛴다. 실패한 슬롯은 --once 재실행으로 재시도할 수 있다.
- 프로세스 잠금으로 같은 저장소의 중복 수집을 방지한다. 종료 시 OS가 잠금을 해제한다.
- 페이지 간 중복 ID, 비정상 숫자, 빈 전체 결과를 성공으로 처리하지 않는다.
- 0대는 유효한 재고다. 거치대보다 많은 자전거도 원본 그대로 저장한다.
- 원본에 관측 시각이 없으므로 source_observed_at은 NULL이다. fetched_at을 원본 관측 시각으로 꾸미지 않는다.
- 모든 저장 시각과 원본 폴더 날짜는 UTC다. 한국 시간은 +9시간이다.
- 여러 페이지는 순서대로 수집되므로 정확히 동시에 관측된 스냅샷은 아니다. 목록 변경으로 인한 누락까지 완전히 보장하지는 않는다.
- PC 절전·종료 중에는 수집하지 못한다. 현재 상태 API로 지난 시점 재고를 복원할 수 없다.

## 검증

```powershell
python -m unittest backend.test_collect -v
```

테스트는 가짜 API 응답으로 페이지 순회, 중복 실행, 부분 실패·복구, 잘못된 숫자를 검증한다.
실제 API 검증은 본인 키를 설정한 후 --once로 수행해야 한다.
success와 0보다 큰 rows를 확인한 뒤 --status로 실행 이력을 점검한다.
현재 React 화면은 FastAPI를 통해 이 DB의 최신 재고와 강남구 예측 결과를 표시한다.

## 과거 평균 기준 모델 백테스트

강남구 1년 데이터의 앞 8개월을 학습, 다음 2개월을 검증, 마지막 2개월을 테스트로 자동 분리한다. 검증·테스트 행으로 평균을 만들지 않으므로 미래 정보 누수가 없다.

```powershell
Set-Location 'D:\졸업프로젝트'
.\.venv\Scripts\python.exe -m backend.evaluate_baseline
```

기본 평가는 서로 크게 겹치는 표본을 반복 집계하지 않도록 30분 간격으로 예측한다. 운영 주기와 똑같이 모든 5분 시점을 평가하려면 다음 옵션을 사용한다.

```powershell
.\.venv\Scripts\python.exe -m backend.evaluate_baseline --origin-step-minutes 5
```

결과는 `reports/baseline-evaluation/`에 저장된다.

- `evaluation.json`: 기간·학습량·커버리지·전체 지표
- `overall.csv`: 모델별 MAE·RMSE·WAPE
- `by_time_bucket.csv`: 출근·낮·퇴근·야간 지표
- `by_station.csv`: 대여소별 지표
- `SUMMARY.md`: 실제 실행 결과와 해석

비교 모델은 수요 0, 직전 30분 반복, 대여소·요일·5분 시점 과거 평균의 세 가지다. `stockChange30m`은 반납량에서 대여량을 뺀 흐름 기반 재고 변화이며 실제 재고 스냅숏 자체가 아니다.

## 실제 재고 스냅숏 평가

수집 DB에서 정확히 30분 차이인 성공 스냅숏을 연결해 대시보드의 평균 기반 예상 재고와 실제 재고를 비교한다. 모델 학습 종료일 이전의 시점은 미래 정보 누수를 막기 위해 기본적으로 제외한다.

```powershell
Set-Location 'D:\졸업프로젝트'
.\.venv\Scripts\python.exe -m backend.evaluate_inventory
```

다음 결과가 `reports/inventory-evaluation/`에 생성된다.

- 실제 재고 MAE·RMSE
- 현재 재고 유지 기준과 평균 모델 비교
- 부족·정상·과잉 Precision·Recall·F1과 혼동행렬
- 실제 0대 품절과 만차 탐지 성능
- 시간대별·대여소별 재고 오차

`--include-training-period` 옵션은 학습 종료일 이전 스냅숏도 포함하지만 데이터 누수가 생길 수 있으므로 공식 평가에는 사용하지 않는다.

## 수집 연속성 점검

최근 7일의 성공 슬롯을 5분 간격 기대값과 비교해 누락률, 가장 긴 누락 구간, 마지막 성공 후 경과 시간을 계산한다.

```powershell
Set-Location 'D:\졸업프로젝트'
.\.venv\Scripts\python.exe -m backend.collection_health --days 7
```

기본 기준은 최근 성공 10분 이내, 수집률 95% 이상이다. 운영 자동 점검에서는 다음 스크립트를 사용할 수 있다.

```powershell
.\scripts\check_collection_health.ps1
```

로그인할 때 수집기를 자동으로 시작하고 중단 시 재시작하는 Windows 작업 스케줄러 등록 스크립트도 제공한다. 이 명령은 실제 PC 설정을 변경하므로 사용자가 직접 실행한다.

```powershell
.\scripts\install_collector_task.ps1
Start-ScheduledTask -TaskName 'SeoulBikeInventoryCollector'
```

## LightGBM 기본 비교 모델

머신러닝 의존성을 설치한 뒤 대여소·시간·요일·월·계절 주기·주말·공휴일·출퇴근 구분으로 향후 30분 대여량과 반납량을 각각 학습한다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-ml.txt
.\.venv\Scripts\python.exe -m backend.train_lightgbm
```

학습 데이터는 평균 모델과 동일하게 약 8개월·2개월·2개월로 시간순 분리한다. 모델 파일은 `models/calendar-lightgbm-v1/`, 평가 결과는 `reports/calendar-lightgbm-v1/`에 저장된다. 모델 파일은 용량과 재생성 가능성을 고려해 Git에서 제외한다.

첫 실험 결과 달력 변수만 사용한 LightGBM은 과거 평균보다 대여·반납 MAE가 각각 약 6.4% 높아 운영 API에 연결하지 않았다. 자세한 결과는 `reports/calendar-lightgbm-v1/SUMMARY.md`에 기록했다.

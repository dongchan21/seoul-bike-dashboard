# 실시간 따릉이 재고 수집기

Python 3.10 이상, 표준 라이브러리만 사용한다. 추가 pip 설치가 없다.

## 실행

프로젝트 폴더에서 다음을 실행한다.

```powershell
Set-Location 'D:\졸업프로젝트'
Copy-Item .env.example .env
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
python -m unittest backend.test_collect backend.test_api -v
```

테스트는 가짜 API 응답으로 페이지 순회, 중복 실행, 부분 실패·복구, 잘못된 숫자를 검증한다.
실제 API 검증은 본인 키를 설정한 후 --once로 수행해야 한다.
success와 0보다 큰 rows를 확인한 뒤 --status로 실행 이력을 점검한다.
FastAPI와 React 화면이 이 DB에 연결되어 있다. 별도 터미널에서 다음을 실행한다.

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.api:app --host 127.0.0.1 --port 8000
npm.cmd run dev
```

브라우저는 `http://127.0.0.1:5173`을 연다. 화면의 조회 버튼은 SQLite만 다시 읽으며 서울시 API를 호출하지 않는다.

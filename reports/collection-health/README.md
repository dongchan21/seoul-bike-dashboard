# 실시간 재고 수집 상태 점검

다음 명령은 최근 7일 동안 5분 슬롯이 얼마나 연속으로 수집됐는지 검사한다.

```powershell
.\.venv\Scripts\python.exe -m backend.collection_health --days 7
```

실행 결과인 `latest.json`과 `daily.csv`는 계속 바뀌는 운영 파일이므로 Git에 올리지 않는다. `status`는 다음 기준으로 결정한다.

- `normal`: 마지막 성공이 10분 이내이고 수집률이 95% 이상
- `incomplete`: 마지막 성공은 최근이지만 기간 수집률이 95% 미만
- `delayed`: 마지막 성공 후 10분을 초과했거나 성공 기록이 없음

`scripts/check_collection_health.ps1`은 상태가 정상이 아닐 때 종료 코드 2를 반환하므로 작업 스케줄러나 모니터링 도구에서 사용할 수 있다.

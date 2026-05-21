# Quickstart: Wikimedia 변경사항 Bronze 적재 파이프라인

본 문서는 `001-wikimedia-changes-ingest` 기능을 로컬 개발 → 워크스페이스 배포까지 검증하는 최단
경로를 제공한다.

## 사전 요구사항

- macOS / Linux + Python 3.12 (`python3 --version`)
- [`uv`](https://docs.astral.sh/uv/) 설치: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- [`databricks` CLI v0.299.2+](https://docs.databricks.com/dev-tools/cli/install.html)
- Azure 계정으로 `az login` 가 가능하고, `dbw-dataplay-lab-kc` 워크스페이스의 SP 가 카탈로그
  생성 권한을 가짐(없으면 사전 발급 필요 — 본 카탈로그를 워크스페이스 admin 이 1회 수동 생성한
  뒤 본 번들의 `resources.catalogs` 블록을 임시 주석 처리하는 fallback 가능)

## 1. 로컬 셋업

```bash
# 레포 루트에서
uv sync                       # pyproject.toml 의 dependencies + dev group 설치
uv run pytest -q              # 단위 + 통합 테스트 (외부 자원 없음)
uv run ruff check src tests
uv run black --check src tests
```

기대 결과:
- 모든 테스트 통과.
- ruff/black 위반 없음.

## 2. 잡 호출부 단독 실행 (선택)

로컬에서 `--override-window-start` 인자로 특정 슬롯을 적재해 본다(`tmp_path` 사용).

```bash
uv run python -m dataplay.jobs.wikimedia_recentchanges \
  --volume-root /tmp/dataplay-local/bronze/recentchanges_raw \
  --override-window-start 2026-05-22T03:25:00Z
```

기대 결과:
- `/tmp/dataplay-local/bronze/recentchanges_raw/wiki=en.wikipedia/year=2026/month=05/day=22/hour=03/minute=25/recentchanges-2026-05-22T03-25-00Z.jsonl.gz`
  파일 생성.
- 표준 출력에 `IngestResult(window=..., record_count=N, ...)` 로그 라인.

> **주의**: 본 실행은 실제 `en.wikipedia.org/w/api.php` 를 호출한다. UA 헤더가 누락되면 4xx 가
> 나며, 평소 부하면 1초 내 종료.

## 3. 번들 검증 + 배포

```bash
az login                                          # 로컬 인증
databricks bundle validate --target lab           # 구성·스키마 검증 (no-op 변경)
databricks bundle deploy   --target lab           # 카탈로그·스키마·볼륨·잡 생성/갱신
databricks bundle run wikimedia_recentchanges --target lab    # 1회 수동 실행
```

기대 결과 (SC-004 검증):
- `databricks bundle deploy` 가 30분 이내 종료.
- 워크스페이스 `Catalog Explorer` 에서 `wikimedia-dataplay` → `bronze` → `recentchanges_raw` 볼륨
  존재.
- `bundle run` 의 잡이 3분 이내 성공(SC-002), 볼륨에 첫 슬롯 파일이 생성됨.

## 4. 정기 실행 확인

```bash
# 잡 정의 확인 — schedule.pause_status 이 UNPAUSED 인지
databricks bundle summary --target lab | grep wikimedia_recentchanges
```

`*/5` cron 으로 다음 5분 슬롯 시점에 자동 실행되어야 함. Databricks Jobs UI 의 Run history 에서
확인.

## 5. 헌법 자가 점검

- [ ] 잡과 자산이 `resources/` / `configuration/` 의 DAB 정의로만 생성됨 (UI 수동 변경 없음)
- [ ] 태스크 스크립트 `src/dataplay/jobs/wikimedia_recentchanges.py` 가 호출부만 (≤ 50 줄, 비즈
      니스 로직 없음)
- [ ] 모든 함수에 타입 힌트
- [ ] `uv run pytest -q` 통과
- [ ] `uv run ruff check` / `black --check` 통과
- [ ] 모든 모듈 상단에 한국어 docstring
- [ ] 모든 코드 주석이 한국어
- [ ] `pyproject.toml` 단일 의존성 관리, `requirements.txt` 부재

## 6. 흔한 트러블슈팅

| 증상 | 원인 | 조치 |
|------|------|------|
| `bundle deploy` 가 `Catalog already exists` 로 실패 | 이미 catalog 가 다른 owner 로 존재 | catalog 블록을 `configuration/catalogs.yml` 에서 임시 주석 처리하고 schema/volume 만 배포 |
| MediaWiki 호출이 403 | `User-Agent` 헤더 누락/부적절 | `IngestionConfig.user_agent` 가 식별 가능한지 점검 |
| 잡 1회 실행이 5분 초과 | 페이지네이션 호출 수가 `max_pages_per_window` 에 임박 | 이벤트 폭증 가능성 — 잡 로그의 `api_calls` 확인 후 상한 조정 (단, 5배 이상이면 사람 개입 검토) |
| 볼륨 파일이 안 보임 | 워크스페이스 권한 / 카탈로그 이름의 하이픈 SQL 참조 | `SELECT * FROM \`wikimedia-dataplay\`.bronze.recentchanges_raw` 처럼 백틱 사용 |

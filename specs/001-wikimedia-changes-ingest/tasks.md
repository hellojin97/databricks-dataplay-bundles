---

description: "Task list for 001-wikimedia-changes-ingest"
---

# Tasks: Wikimedia 변경사항 Bronze 적재 파이프라인

**Input**: Design documents from `/specs/001-wikimedia-changes-ingest/`

**Prerequisites**: plan.md (필수), spec.md (필수), research.md, data-model.md, contracts/

**Tests**: 헌법 원칙 V("변환 함수에 대한 단위 테스트는 필수") 에 따라 본 기능의 단위 테스트는
선택사항이 아닌 **필수**다. 통합 테스트는 외부 자원 없이 더블(`responses`, `tmp_path`) 로 수행.

**Organization**: 태스크는 사용자 스토리(US1=P1 / US2=P2 / US3=P3) 별로 묶인다. 각 스토리는
독립적으로 구현·테스트 가능하며 체크포인트에서 검증한다.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 동일 파일 충돌이 없고 선행 의존성이 완료된 경우 병렬 실행 가능.
- **[Story]**: 해당 태스크가 속한 사용자 스토리 (US1/US2/US3).
- 모든 태스크는 실제 파일 경로를 포함한다.

## Path Conventions

본 프로젝트는 단일 Python 패키지 구조 — plan.md "Project Structure" 트리 참조.

- 잡 정의: `resources/jobs/<name>.yml`
- 카탈로그/스키마/볼륨: `configuration/catalogs.yml`
- 소스: `src/dataplay/...`
- 테스트: `tests/unit/...`, `tests/integration/...`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 빌드/실행/테스트 가능한 골격 마련. 본 기능의 1번째 PR 단위에서 모두 한 번에 처리.

- [X] T001 레포 루트에 `pyproject.toml` 신규 생성 (uv 관리, Python `>=3.12`, dependencies = requests + pydantic, dev-group = pytest+ruff+black+responses). 설정 골자는 [research.md R9](./research.md#r9-uv-패키지-매니징--pyprojecttoml-신규) 참조.
- [X] T002 `databricks.yml` 갱신 — (a) `include` 에 `configuration/*.yml` 추가, (b) `python.venv_path: .venv` + `python.resources: ["resources:load_resources"]` 추가 (pydabs 진입점), (c) `targets.lab` 에서 `mode: development` 제거 (2026-05-22 토폴로지 결정 — cron 활성·정식 리소스 이름). [research.md R6/R7](./research.md#r7-잡-정의-resourcesjobswikimedia_recentchangespy-pydabs--databricksyml-의-lab-target).
- [X] T003 [P] `src/dataplay/__init__.py`, `src/dataplay/jobs/__init__.py`, `src/dataplay/wikimedia/__init__.py` 생성 — 각 파일 최상단에 한국어 모듈 docstring(헌법 VII).
- [X] T004 [P] `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py` 신규 (빈 파일 가능).
- [X] T005 [P] `tests/conftest.py` 작성 — 공용 fixture: `frozen_now`(테스트용 UTC datetime), `tmp_volume_root`(tmp_path 기반 볼륨 루트).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 모든 스토리 진입의 선결 조건. 본 프로젝트는 도메인이 단순해 별도 인프라가 거의 없음.

**⚠️ CRITICAL**: 본 페이즈가 완료되어야 어떤 user story 도 시작 가능.

- [X] T006 `uv sync` 가 성공하는지 검증 (T001 의 산물). 실패하면 의존성 명세 수정 후 재시도.

**Checkpoint**: Foundation 준비 완료 — 이후 user story 들은 (독립 컴포넌트에 한해) 병렬 진행 가능.

---

## Phase 3: User Story 1 - Bronze 레이어에 위키미디어 변경사항 정기 적재 (Priority: P1) 🎯 MVP

**Goal**: `en.wikipedia.org` 의 직전 5분 슬롯을 MediaWiki Action API 로 가져와 NDJSON+gzip 으로
볼륨에 적재(+`_SUCCESS` marker). 멱등(파일 덮어쓰기).

**Independent Test**: `uv run python -m dataplay.jobs.wikimedia_recentchanges --override-window-start <iso>`
실행 시 지정 슬롯의 `.jsonl.gz` 와 `_SUCCESS` 가 볼륨 루트(tmp 가능) 에 생성되고, 파일을 다시
읽었을 때 라인 수 = `IngestResult.record_count` = MediaWiki 응답의 윈도우 내 이벤트 수와 일치
(이벤트 한 건의 `timestamp == window.end` 인 경계 이벤트는 제외됨).

### Tests for User Story 1 (헌법 V — 필수) ⚠️

> 변환 함수와 합성 로직은 단위 테스트 없이 머지 불가.

- [X] T007 [P] [US1] `tests/unit/test_window.py` — `compute_previous_slot(now)` 의 정각/+5/+9분 경계 케이스, UTC 가정, 초/마이크로초 입력 무시 검증.
- [X] T008 [P] [US1] `tests/unit/test_window.py` 에 `window_to_volume_dir`, `window_to_file_name` 의 경로 명명 규약 검증 추가 (contracts/bronze-file-layout.md 와 정합).
- [X] T009 [P] [US1] `tests/unit/test_window.py` 에 `filter_events_within_window` 의 좌폐우개 경계 (`event.timestamp == window.end` 제거) 검증 추가.
- [X] T010 [P] [US1] `tests/unit/test_window.py` 에 `serialize_event_line(event) -> bytes` 의 UTF-8 보존(`ensure_ascii=False`) 및 separators 검증 추가.
- [X] T011 [P] [US1] `tests/unit/test_pipeline.py` — `orchestrate(config, now, source=Fake, writer=Fake)` 합성: 가짜 source 가 N개 이벤트를 돌려주면 가짜 writer 가 받은 (path, bytes, success_marker) 튜플이 기대대로인지.
- [X] T012 [P] [US1] `tests/integration/test_source.py` — `responses` 또는 `pytest-httpserver` 로 MediaWiki API 응답 더블링. `MediaWikiRecentChangesClient.fetch_window` 가 (a) 페이지네이션을 정확히 따라가고, (b) `User-Agent` 헤더를 붙이며, (c) `max_pages` 초과 시 예외, (d) HTTP 429 시 `Retry-After` 1회 재시도 후 실패 동작을 검증.
- [X] T013 [P] [US1] `tests/integration/test_writer.py` — `tmp_path` 위에서 `BronzeVolumeWriter`(또는 동일 인터페이스의 `LocalDirectoryWriter`) 가 `.jsonl.gz` 와 `_SUCCESS` 를 만들고, 같은 윈도우 재실행 시 둘 다 덮어쓰는지 검증. gzip 압축 해제 후 라인 수 = 입력 이벤트 수.

### Implementation for User Story 1

- [X] T014 [P] [US1] `src/dataplay/wikimedia/window.py` 작성 — `IngestWindow` frozen dataclass + `compute_previous_slot(now)` + `window_to_volume_dir(window, root, wiki_id)` + `window_to_file_name(window)` + `filter_events_within_window(events, window)` + `serialize_event_line(event)`. 모든 함수에 타입 힌트, 모듈 상단 한국어 docstring.
- [X] T015 [P] [US1] `src/dataplay/wikimedia/config.py` 작성 — `IngestionConfig` (Pydantic v2) + `RecentChangesResponse` (shape 검증만, extra=allow). [data-model.md §1](./data-model.md#1-외부-입력-경계--pydantic) 참조.
- [X] T016 [US1] `src/dataplay/wikimedia/source.py` 작성 — `MediaWikiRecentChangesClient` (생성자: `requests.Session`, api_url, user_agent, timeout) + `PageBatch` dataclass. `fetch_window(window, max_pages)` 메서드 구현 (페이지네이션, `rcstart=window.end`, `rcend=window.start`, `rcdir=older`, `rclimit=500`, contracts 참조). T014, T015 선행.
- [X] T017 [US1] `src/dataplay/wikimedia/writer.py` 작성 — `BronzeVolumeWriter` 클래스(`/Volumes/...` 경로용) + `LocalDirectoryWriter` 클래스(테스트용, 동일 인터페이스). `write_window(window, events) -> IngestResult` 가 NDJSON+gzip stream write 후 `_SUCCESS` 파일 생성. T014 선행.
- [X] T018 [US1] `src/dataplay/wikimedia/pipeline.py` 작성 — `IngestResult` dataclass + `orchestrate(config, now, source, writer) -> IngestResult` 합성 함수. T014–T017 선행. SparkSession 받지 않음(헌법 IV N/A 케이스, plan Complexity #1 참조).
- [X] T019 [US1] `src/dataplay/jobs/wikimedia_recentchanges.py` 작성 — 태스크 엔트리포인트(호출부 only, ≤ 50 줄). `argparse` 로 `--volume-root` / `--user-agent` / `--override-window-start` 파라미터 파싱 → `IngestionConfig` 생성 → `requests.Session` + `MediaWikiRecentChangesClient` + `BronzeVolumeWriter` 생성 → `orchestrate(...)` 호출 → 결과 stdout 출력. 헌법 II 의 "호출부" 정의 준수.
- [X] T020 [US1] `resources/jobs/wikimedia_recentchanges.py` (pydabs) — `databricks-bundles` Python DSL 로 `Job(...)` 정의. 서버리스 Python task + cron `*/5` + `environment_version="2"` + dependencies. 함께 `resources/__init__.py` 의 `load_resources` 진입점과 `databricks.yml` 의 `python.resources` 설정이 필요. [research.md R7](./research.md#r7-잡-정의-resourcesjobswikimedia_recentchangespy-pydabs--databricksyml-의-lab-presets) 참조. (2026-05-22 YAML → pydabs 전환.)

**Checkpoint US1**: 
- `uv run pytest -q` 전체 통과
- 로컬에서 `python -m dataplay.jobs.wikimedia_recentchanges --volume-root /tmp/.../recentchanges_raw --override-window-start 2026-05-22T03:25:00Z` 실행 시 `.jsonl.gz` + `_SUCCESS` 생성 (실제 위키미디어 호출 동반)

---

## Phase 4: User Story 2 - 카탈로그·스키마·볼륨을 코드로 정의 (Priority: P2)

**Goal**: `wikimedia-dataplay` 카탈로그 + `bronze` 스키마 + `recentchanges_raw` 볼륨을 DAB 코드로
정의. `bundle deploy` 한 번으로 자산 생성.

**Independent Test**: `databricks bundle validate --target lab` 가 0 종료, plan diff 에 catalog/
schema/volume 자산이 신규 생성/관리 대상으로 표시. (실제 deploy 는 Phase 6 의 e2e 단계에서 검증.)

### Implementation for User Story 2

- [X] T021 [US2] `configuration/catalogs.yml` 신규 — `resources.catalogs.wikimedia_dataplay` (name = `wikimedia-dataplay`), `resources.schemas.bronze` (catalog_name 참조 + name = `bronze`), `resources.volumes.recentchanges_raw` (catalog_name + schema_name 참조 + name = `recentchanges_raw` + `volume_type: MANAGED`). [research.md R6](./research.md#r6-카탈로그스키마볼륨의-dab-정의-위치) 의 YAML 골자 그대로. T002 의 include 갱신 선행.
- [ ] T022 [US2] `databricks bundle validate --target lab` 실행 후 출력에서 `wikimedia-dataplay`/`bronze`/`recentchanges_raw` 세 자산이 plan 으로 노출되는지 수동 확인 — 결과를 PR 본문에 캡처/요약.

**Checkpoint US2**: validate 통과, 자산 정의가 DAB 의 단일 소스로 박힘.

---

## Phase 5: User Story 3 - 적재 결과의 운영 관측성 (Priority: P3, 부분만 MVP 포함)

**Goal (MVP 부분)**: 잡 실행 로그에 처리한 윈도우 시각과 적재 레코드 수가 **구조화된 형태** 로
노출(FR-011). Discord 알림(FR-008) 은 별도 PR — 본 phase 의 후속 deferred 작업.

**Independent Test**: T019 의 호출부 실행 결과 stdout 마지막 라인이 다음 키들을 포함하는 단일 JSON
객체 또는 `key=value` 라인이다: `window_start_iso`, `window_end_iso`, `record_count`, `file_path`,
`bytes_written`, `api_calls`.

### Implementation for User Story 3 (MVP)

- [X] T023 [US3] `src/dataplay/jobs/wikimedia_recentchanges.py` (T019 결과물) 수정 — `IngestResult` 의 모든 필드를 직렬화한 1라인 JSON 로그를 stdout 에 출력 (예: `{"event":"ingest_complete", "window_start":"...", "record_count":N, ...}`). T019 선행.
- [X] T024 [US3] `tests/unit/test_pipeline.py` (또는 신규 `tests/unit/test_jobs_entry.py`) 에 stdout 로그 라인의 JSON parse 가능 + 필수 필드 존재 검증 추가. T023 선행.

### Deferred for post-MVP

- [ ] T025 [US3] (Deferred) Discord webhook 알림 통합 — FR-008. 별도 PR 에서 (a) Databricks Job 의 `webhook_notifications.on_failure` 또는 (b) GitHub Actions 의 워크플로 콜백을 통한 Discord 전송 구현. 본 tasks 범위 외.

**Checkpoint US3 (부분)**: 구조화 로그 + 단위 테스트 추가됨. Discord 알림은 별도 트래킹.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 헌법 자가점검, 정적 분석, e2e 수동 검증, 문서 링크.

- [X] T026 [P] 전체 코드베이스에서 `uv run ruff check src tests` 와 `uv run black --check src tests` 가 0 종료하는지 확인. 위반 시 자동 수정 후 재실행.
- [X] T027 [P] 모든 새 모듈(`src/dataplay/...`)의 상단에 한국어 docstring 이 존재하는지 점검(헌법 VII). 코드 주석이 한국어이며 식별자는 영어 `snake_case`/`PascalCase` 인지 점검.
- [X] T028 [P] `quickstart.md` 의 "헌법 자가 점검" 체크리스트를 PR 본문에 복사하고 각 항목 체크.
- [ ] T029 수동 e2e 검증 — `az login` → `databricks bundle deploy --target lab` 후 30분 이내 자산 준비(SC-004), `databricks bundle run wikimedia_recentchanges --target lab` 1회 실행이 3분 이내 종료(SC-002), 볼륨에 `.jsonl.gz` + `_SUCCESS` 생성 확인.
- [X] T030 [P] `README.md` 의 "워크로드 추가하기" 또는 "문서" 섹션에 `specs/001-wikimedia-changes-ingest/` 와 `specs/001-wikimedia-changes-ingest/quickstart.md` 링크 추가.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 무의존, 즉시 시작 — 단 T002 는 T021 의 선결조건(include 갱신).
- **Foundational (Phase 2)**: Setup 완료 후 → 이후 모든 user story 선결.
- **User Story 1 (P1)**: Foundational 완료 후 즉시 시작 가능. 본 MVP.
- **User Story 2 (P2)**: Foundational 완료 + T002 (include) 완료 후 시작 가능. US1 과 **병렬 가능**.
- **User Story 3 (P3, 부분)**: T019 (US1 의 엔트리포인트) 완료 후 시작. US2 와 병렬 가능.
- **Polish (Phase 6)**: US1 + US2 (+ US3 부분) 완료 후 마무리.

### Within Each User Story

- 테스트(헌법 V) 는 구현 전에 작성하고, 실패하는 것을 확인 → 구현 → 통과 사이클 권장.
- 모델(`window.py`, `config.py`) → 서비스(`source.py`, `writer.py`) → 합성(`pipeline.py`) → 호출부 / 잡 YAML 순서.

### Parallel Opportunities

- 모든 `[P]` 표시 태스크는 서로 다른 파일에 작업하므로 병렬 가능.
- T007–T013 (US1 의 테스트들) 은 모두 다른 단정(assertion) 영역 또는 다른 파일이라 병렬 작성 가능.
- T014, T015 (window.py, config.py) 는 서로 독립.
- US1 의 구현과 US2 의 YAML 정의는 서로 다른 트리라 다른 개발자에게 할당 가능.

---

## Parallel Example: User Story 1 (테스트 + 구현 동시 진행)

```bash
# 테스트 작성 트랙 (한 개발자)
Task: "tests/unit/test_window.py — T007~T010 합쳐서 작성"
Task: "tests/unit/test_pipeline.py — T011 작성"
Task: "tests/integration/test_source.py — T012 작성"
Task: "tests/integration/test_writer.py — T013 작성"

# 구현 트랙 (다른 개발자)
Task: "src/dataplay/wikimedia/window.py — T014 구현"
Task: "src/dataplay/wikimedia/config.py — T015 구현"
# T016, T017, T018, T019, T020 은 의존성 순서로 진행
```

---

## Implementation Strategy

### MVP First (US1 only)

1. Phase 1 (Setup) 전체 완료
2. Phase 2 (Foundational) 완료
3. Phase 3 (US1) 완료
4. **STOP and VALIDATE**: T029 의 수동 e2e 를 lab 워크스페이스에서 1회 실행(US1 만으로도 가치
   증명 가능).
5. Demo / Deploy.

### Incremental Delivery

1. Setup + Foundational → 골격 준비.
2. US1 (P1) 완료 → 첫 슬롯 적재 가시화 → demo.
3. US2 (P2) 완료 → 자산 거버넌스 코드화 → demo (`bundle deploy` 만 보여줘도 충분).
4. US3 (P3, 부분) 완료 → 구조화 로깅 → demo.
5. Polish → 헌법 자가점검 통과 → 머지.

### Parallel Team Strategy

- 1인 개발: 위 MVP 순서대로 진행. US1 의 테스트와 구현은 같은 사람이라도 두 트랙 번갈아 진행.
- 2인 개발: 한 명이 US1 구현, 다른 명이 US2(YAML) + 테스트 작성 보조. US1 완료 후 합류해 US3 +
  Polish 마무리.

---

## Notes

- `[P]` = 서로 다른 파일, 의존성 없음 = 병렬 가능.
- `[Story]` = 추적성. 한 story 가 깨져도 다른 story 의 작업이 영향받지 않는다.
- 테스트는 헌법 V 에 의해 **변환 함수와 합성 로직에 대해 필수**.
- 본 plan 의 Complexity Tracking #1 / #2 가 깨지면(예: 추후 PySpark 도입), 본 tasks.md 의 가정도
  깨질 수 있으니 plan.md 재검토 후 갱신.
- 각 태스크 완료 시 또는 논리 단위로 commit. PR 단위는 phase 단위(또는 MVP=US1) 권장.

# Implementation Plan: Wikimedia 변경사항 Bronze 적재 파이프라인

**Branch**: `001-wikimedia-changes-ingest` | **Date**: 2026-05-22 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-wikimedia-changes-ingest/spec.md`

**Note**: This plan was authored by `/speckit-plan`. Phase 0/1 artifacts referenced below are
generated as siblings of this file.

## Summary

`en.wikipedia.org` 의 **MediaWiki Action API `list=recentchanges`** 를 5분 벽시계 슬롯
(`[HH:MM, HH:MM+5)`) 단위로 폴링해, Unity Catalog 볼륨 `wikimedia-dataplay.bronze.recentchanges_raw`
에 **NDJSON+gzip 원본** 그대로 적재한다. 카탈로그/스키마/볼륨은 `configuration/catalogs.yml`
에 DAB 1급 리소스(`resources.catalogs/schemas/volumes`) 로 코드 정의한다. 잡은 Databricks
**서버리스 Python task** 로 실행(기존 `example_job.yml` 와 동일 패턴)하며, 본 워크로드 규모
(~수백~수천 이벤트/슬롯) 가 작아 **PySpark 를 사용하지 않는다** (Complexity Tracking 참조). 멱등성은
"윈도우 경로 파일 덮어쓰기" 로 보장. 실패는 잡 실패로 시끄럽게 통보(Discord 알림 재사용); 자동
백필은 본 MVP 범위 외.

## Technical Context

**Language/Version**: Python 3.12+ (Databricks Serverless Python task `environment_version: "2"` 기준)

**Primary Dependencies**:
- `requests` (HTTPS 클라이언트, MediaWiki API 호출)
- `pydantic` ≥ 2 (외부 입력 검증)
- 표준 라이브러리 `gzip`, `json`, `pathlib`, `datetime`(zoneinfo)
- (테스트) `pytest`, `responses` 또는 `pytest-httpserver` (HTTP mock)
- (개발도구) `ruff`, `black`, `mypy`(선택)

**Storage**: Databricks Unity Catalog **Volume** (`/Volumes/wikimedia-dataplay/bronze/recentchanges_raw/...`)
— 서버리스 task 에서 POSIX FUSE 경로로 직접 쓰기.

**Testing**: `pytest` (단위 + 통합). HTTP 는 `responses`/`pytest-httpserver` 로 더블; 볼륨 쓰기는
`tmp_path` 로 더블링하고 통합 테스트는 같은 인터페이스를 가진 로컬 디렉터리 어댑터로 검증.

**Target Platform**:
- **빌드/배포**: Databricks Asset Bundle (CLI v0.299.2+, GitHub Actions OIDC → SP → Azure Databricks).
- **런타임**: Databricks Serverless Jobs (Workspace `dbw-dataplay-lab-kc`, target `lab`).
- **개발**: macOS/Linux + Python 3.12 + `uv` (로컬 단위/통합 테스트).

**Project Type**: 데이터 파이프라인(Lakeflow Job) — 단일 패키지(`src/dataplay/`).

**Performance Goals**:
- 1 슬롯 처리 ≤ 3분(SC-002). 정상 부하 시 실제 목표 ≤ 30초 (API 응답 + 페이지네이션 합산).
- 슬롯당 API 호출 ≤ 10회(페이지네이션 1회당 `rclimit=500` 사용).
- 적재 파일 크기 ≤ 5 MB (gzip 압축 후) 정상 부하 기준.

**Constraints**:
- MediaWiki API `User-Agent` 헤더 필수(Wikimedia 정책). 실패 시 4xx.
- 익명 호출 rate limit: 사실상 IP 기준 burst 제한 — 5분 슬롯당 ~10회 호출은 안전 구간.
- 서버리스 Python task 의 콜드 스타트 ~10–20초 → SC-002 의 3분 예산 내.
- 본 MVP 는 **자동 백필 없음** (FR-007 의 "보정"은 다음 정기 실행에서 직전 슬롯 1개만 재시도).

**Scale/Scope**:
- `en.wikipedia.org` 정상 부하: ~150–250 changes/min → 1 슬롯(5분) 당 ~750–1,250 이벤트.
- 1일 ~288 슬롯, 1일 데이터 ~200K–360K 이벤트.
- 1년 보존 시 볼륨 사용량 ~100–200 GB (gzip 압축 후 추정).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

본 헌법(v1.0.0, [constitution.md](../../.specify/memory/constitution.md)) 의 7개 원칙 + 기술 표준에
대한 점검 결과:

| # | 원칙 | 상태 | 근거 |
|---|------|------|------|
| I | Bundle-First 잡 정의 (NON-NEGOTIABLE) | ✅ Pass | 잡은 `resources/jobs/wikimedia_recentchanges.yml`, 자산은 `configuration/catalogs.yml` 로 모두 DAB 코드 정의. 워크스페이스 UI 수동 생성 없음. |
| II | 호출부와 비즈니스 로직 분리 (NON-NEGOTIABLE) | ✅ Pass | 태스크 스크립트 `src/dataplay/jobs/wikimedia_recentchanges.py` 는 호출부 only. 비즈니스 로직은 `src/dataplay/wikimedia/{config,window,source,writer,pipeline}.py`. |
| III | 함수형 변환 · 클래스형 I/O | ⚠️ Partial — 정당화 | I/O 는 클래스(`MediaWikiRecentChangesClient`, `BronzeVolumeWriter`), 외부 입력은 Pydantic(`IngestionConfig`), 내부 데이터는 frozen dataclass(`IngestWindow`, `IngestResult`). **`DataFrame.transform` 합성은 본 워크로드 규모상 N/A** → Complexity Tracking 의 1번 항목 참조. 변환 함수는 순수 파이썬으로 합성. |
| IV | 명시적 SparkSession 주입 (NON-NEGOTIABLE) | ✅ N/A | 본 잡은 PySpark 를 사용하지 않으므로 SparkSession 자체가 없음. 향후 silver 단계가 추가되면 그때 본 원칙이 발동. |
| V | 테스트 우선 (pytest) | ✅ Pass | `pytest`. 변환 함수(`pipeline.split_by_minute_window`, `parse_recentchange` 등) 단위 테스트 필수. 통합 테스트는 HTTP/볼륨 더블 사용. |
| VI | 타입 안전성과 포맷 일관성 | ✅ Pass (선행 셋업 필요) | 모든 함수 타입 힌트, `uv` + `pyproject.toml` 신규, `ruff`/`black` 설정 단일 소스. `pyproject.toml` 부재 → Phase 1 의 Setup 단계에서 신규 생성(헌법의 단일 의존성 관리 요구 충족). |
| VII | 한국어 문서화 · 영어 식별자 | ✅ Pass | 본 plan/spec/research/data-model 모두 한국어. 식별자 모두 영어 `snake_case`/`PascalCase`. 모든 모듈 상단 `"""..."""` 한국어 docstring. |
| 기술 표준 | Python 3.12+, PySpark 3.5+, DBR 16.4, uv, pyproject.toml | ⚠️ Partial — 정당화 | (a) PySpark 미사용은 Complexity #1 정당화. (b) "DBR 16.4" 는 본 워크로드가 서버리스 Python task 이므로 `environment_version` 기반 의존성 명시로 대체 — Complexity #2 정당화. (c) Python 3.12, uv, pyproject.toml 전부 준수. |

**Gate 결과**: 위반 2건 모두 Complexity Tracking 에 정당화 기록 → **PASS**.

### Post-Design 재평가 (Phase 1 산출물 작성 후)

`data-model.md` / `contracts/` / `research.md` 작성 후 재점검:

- 원칙 II: 비즈니스 로직 모듈(`config`, `window`, `source`, `writer`, `pipeline`) 과 호출부
  스크립트가 명확히 분리됨 → ✅ 유지.
- 원칙 III: I/O 클래스(`MediaWikiRecentChangesClient`, `BronzeVolumeWriter`), 외부 입력 Pydantic
  (`IngestionConfig`), 내부 데이터 frozen dataclass(`IngestWindow`, `IngestResult`, `PageBatch`)
  로 매핑이 일관 → 부분 위반(Complexity #1) 외에는 ✅.
- 원칙 V: 테스트 항목이 `research.md` R10 에 단위/통합으로 분리됨, 외부 자원 의존 없음 → ✅.
- 원칙 VI: `pyproject.toml` 의 골자가 R9 에 정의되어 단일 의존성 관리 충족, ruff/black 설정 포함
  → ✅.
- 신규 위반 발견: **없음**.

**Post-Design Gate**: **PASS**. tasks 생성으로 진행 가능.

## Project Structure

### Documentation (this feature)

```text
specs/001-wikimedia-changes-ingest/
├── plan.md              # 본 파일 (/speckit-plan 산출)
├── research.md          # Phase 0 산출
├── data-model.md        # Phase 1 산출
├── quickstart.md        # Phase 1 산출
├── contracts/           # Phase 1 산출 (외부 API + 볼륨 파일 레이아웃)
│   ├── mediawiki-recentchanges-request.md
│   └── bronze-file-layout.md
├── checklists/
│   └── requirements.md  # /speckit-specify 산출
└── tasks.md             # /speckit-tasks 산출(미생성)
```

### Source Code (repository root)

```text
configuration/                              # DAB 카탈로그·스키마·볼륨 정의 (사용자 지정 위치)
└── catalogs.yml                            # resources.catalogs / schemas / volumes

resources/
├── example_job.yml                         # (기존)
└── jobs/
    └── wikimedia_recentchanges.yml         # 본 잡 DAB 정의 (서버리스 Python task, cron */5)

src/
├── example.py                              # (기존, 추후 제거 후보)
└── dataplay/                               # 본 프로젝트의 단일 Python 패키지
    ├── __init__.py
    ├── jobs/
    │   ├── __init__.py
    │   └── wikimedia_recentchanges.py      # 태스크 엔트리포인트 = 호출부 only
    └── wikimedia/
        ├── __init__.py
        ├── config.py                       # Pydantic: IngestionConfig (외부 입력 경계)
        ├── window.py                       # frozen dataclass: IngestWindow + 윈도우 계산 함수
        ├── source.py                       # 클래스: MediaWikiRecentChangesClient (HTTP I/O)
        ├── writer.py                       # 클래스: BronzeVolumeWriter / LocalDirectoryWriter (FS I/O)
        └── pipeline.py                     # 함수 합성: orchestrate(spark=None) -> IngestResult

tests/
├── unit/
│   ├── test_window.py                      # 슬롯 정렬 / 경계 계산 함수
│   └── test_pipeline.py                    # 합성 로직 (가짜 source/writer 주입)
└── integration/
    ├── test_source.py                      # responses 로 MediaWiki HTTP 더블 + 페이지네이션
    └── test_writer.py                      # tmp_path 로 NDJSON+gzip 파일 형태 검증

pyproject.toml                              # uv 관리 — 신규 생성
databricks.yml                              # 기존; include 에 configuration/*.yml 추가 필요
```

**Structure Decision**:
- 단일 Python 패키지 `dataplay` 아래 도메인 서브패키지 `wikimedia` 와 호출부 모음 `jobs` 로
  분리(헌법 II). 향후 silver/gold 또는 다른 데이터 소스가 추가되어도 `src/dataplay/<domain>/` 으로
  확장 가능.
- 자산 정의(`configuration/catalogs.yml`) 와 잡 정의(`resources/jobs/...yml`) 는 다른 폴더로 분리.
  사용자 명시 요청을 따른 결과이며, 자산 거버넌스 변경과 잡 정의 변경의 리뷰 동선이 자연스럽게
  분리되는 이점.
- `databricks.yml` 의 `include` 에 `configuration/*.yml` 을 추가해야 카탈로그 정의가 번들에 포함됨
  → Phase 1 Setup 의 첫 task 로 포함.
- 같은 `databricks.yml` 의 `targets.lab` 에 `presets.trigger_pause_status: UNPAUSED` 와
  `presets.skip_name_prefix_for_schema: true` 를 추가해야 (a) `*/5` 스케줄이 실제 동작하고 (b)
  schema 이름이 `bronze` 그대로 유지된다(`mode: development` 의 자동 prefix/pause 해제) — 본
  내용은 `research.md` R7 의 결정사항.

## Complexity Tracking

> Constitution Check 에서 단순 대안을 기각한 위반 2건의 정당화.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| **#1 PySpark 미사용** (원칙 III 의 `DataFrame.transform` 합성, 기술 표준의 PySpark 3.5+ 적용 안 함) | 워크로드 규모가 슬롯당 ~1K 이벤트로 매우 작음. 순수 Python 으로 충분하고, HTTP fetch + gzip + file write 는 본질적으로 비-Spark 작업. 변환 함수 합성은 일반 함수형 합성으로 대체. | "PySpark 도 함께 사용" 대안 기각: (a) Spark 세션 콜드 스타트가 SC-002 의 3분 예산을 ~30초 이상 소모, (b) 워크로드가 분산이 불필요해 컴퓨트 비용만 증가, (c) bronze 의 본질이 "원본 NDJSON 저장" 이라 DataFrame 변환 가치가 없음. 향후 silver 단계에서 PySpark 도입이 자연스럽고, 그때 SparkSession 명시적 주입(원칙 IV) 이 즉시 적용됨. |
| **#2 DBR 16.4 미고정** (기술 표준의 "잡 클러스터 정의는 본 런타임을 기본값") | 본 잡은 **classic 클러스터를 정의하지 않는 서버리스 task**. 기존 `example_job.yml` 와 동일하게 `environment_version`(예: "2") 으로 표준 런타임을 사용한다. 헌법의 "DBR 16.4" 조항은 *classic 클러스터를 만들 때의 기본값* 으로 해석한다. | "Classic job_cluster 로 DBR 16.4 고정" 대안 기각: (a) 5분마다 새 클러스터 기동/종료가 비용 면에서 비효율(서버리스 권장 케이스), (b) 본 잡이 1 노드로 충분해 워커 분산 가치가 없음. 단, 헌법 다음 개정에서 본 해석을 명문화하는 것을 권장 → MINOR 수준 헌법 개정 후보로 기록. |

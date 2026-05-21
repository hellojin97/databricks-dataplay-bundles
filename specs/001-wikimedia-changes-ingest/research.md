# Phase 0 Research: Wikimedia 변경사항 Bronze 적재 파이프라인

본 문서는 `/speckit-plan` Phase 0 의 산출물로, 본 기능 구현을 위해 결정해야 하는 기술 항목과
선택지, 그리고 본 프로젝트가 채택한 결정을 정리한다. 각 항목은 **Decision / Rationale /
Alternatives considered** 형식을 따른다.

## R1. MediaWiki Action API `list=recentchanges` 호출 형태

**Decision**: HTTPS GET 으로 `https://en.wikipedia.org/w/api.php` 에 다음 파라미터 호출.

```
action=query
format=json
formatversion=2
list=recentchanges
rcstart=<window_end_iso>     # 주의: rcstart 가 'newer' 기본 정렬에서는 newest, rcdir 와 함께 사용
rcend=<window_start_iso>
rcdir=older                  # rcstart -> rcend (시간이 오래된 쪽으로) 진행
rclimit=500                  # 최대값
rcprop=title|timestamp|ids|sizes|flags|user|userid|comment|parsedcomment|tags|loginfo
rctype=edit|new|log|categorize
rccontinue=<token>           # 페이지네이션 이어받기 (응답 continue 객체)
```

User-Agent 헤더: `dataplay-bundles/0.1 (https://github.com/hellojin97/databricks-dataplay-bundles; contact@example)` —
Wikimedia 정책상 식별 가능한 UA 가 필수.

**Rationale**:
- `rcdir=older` + `rcstart=window_end` / `rcend=window_start` 조합은 윈도우 끝→시작 순서로 페이지
  네이션이 깔끔. 결과 정렬은 다운스트림 분석 시 재정렬 가능.
- `rclimit=500` 은 익명/User account 모두에 허용되는 최대 페이지 크기 → 호출 횟수 최소화.
- `rcprop` 에 가능한 모든 표준 속성 포함 — bronze 는 **원본 보존** 이 목표이므로 가능한 한 풍부.
- `formatversion=2` 는 modern JSON 응답(불필요한 `*` wrapping 없음). 파싱 단순.
- 페이지네이션 컨텍스트(`continue.rccontinue`) 는 응답에서 받아 다음 호출에 그대로 전달.

**Alternatives considered**:
- **EventStreams (SSE)**: 멀티 wiki 단일 스트림이지만 사용자가 명시적으로 Action API 를 선택
  (Clarifications Q1). 본 결정에서 제외.
- **Wikimedia Enterprise**: 유료 상용. 본 PoC 범위 외.

## R2. 페이지네이션과 호출 수 추정

**Decision**: 슬롯당 페이지네이션 호출 수를 **최대 10회** 로 제한. 초과 시 잡 실패 처리(상한
exceed 알람).

**Rationale**:
- `en.wikipedia.org` 의 정상 부하는 ~150–250 changes/min × 5min = ~750–1,250 events/슬롯.
- `rclimit=500` 으로 페이지네이션 호출은 정상 부하에서 2–3회. 10회 한도는 상한 부하 기준
  **약 4배** 안전 마진 (1,250 × 4 = 5,000 events ≒ 10 페이지).
- 10회 초과면 평소의 ~4배 이상 이벤트 폭증 의심 → 사람 개입이 필요한 신호. 잡 실패가 적절.

**Alternatives considered**:
- **무제한 페이지네이션**: rate limit 위반·런타임 폭주 위험. 기각.
- **rclimit 더 낮춰 호출 수 증가**: 의미 없음. 500 이 최대 + 권장값.

## R3. 출력 파일 포맷과 압축

**Decision**: **NDJSON + gzip** (`.jsonl.gz`). 1 슬롯 = 1 파일 (정상 부하).

- 각 라인 = MediaWiki 응답의 `query.recentchanges[]` 배열 원소 1개를 직접 직렬화 (`json.dumps`,
  `ensure_ascii=False`, `separators=(',', ':')`).
- gzip 수준 6(기본). 슬롯 크기 ~1KB×1K events ≈ 1MB 원본, gzip 후 ~200–400KB 추정.

**Rationale**:
- **원본 보존**: API 응답 각 원소를 가공 없이 그대로 직렬화 → 페이로드 스키마 변경에도 강건.
- **압축률**: JSON 텍스트는 gzip 압축률이 매우 좋음(반복 키 이름이 압축됨).
- **읽기 호환성**: Spark `spark.read.json("/Volumes/.../*.jsonl.gz")` 직접 읽기 가능 → silver
  단계에서 추가 변환 비용 0.
- **Append 불필요**: 1 슬롯 = 1 파일 = 1회 gzip stream write. 트랜잭션 단순.

**Alternatives considered**:
- **Parquet**: 컬럼나 + 압축은 좋지만 (a) 스키마 사전 선언 필요 — bronze 의 페이로드 진화 위배,
  (b) 작은 파일은 Parquet 메타데이터 오버헤드. 기각.
- **JSON without compression**: 압축률 5–10배 손실. Wikimedia 1년치 ≈ 1–2 TB 가 200 GB 로 줄어드는
  효과를 포기. 기각.
- **gzip 대신 zstd**: 압축률·속도 모두 우수하나 `gzip` 표준 라이브러리만으로 가능한 zero-dep 옵션이
  단순. zstd 채택은 향후 silver 결정.

## R4. 멱등성 — 윈도우 경로 파일 덮어쓰기

**Decision**: 동일 슬롯 키(시작 시각)는 동일 경로로 결정되며, 잡은 **항상 그 경로에 덮어쓴다**.
별도 상태 저장(KV/DB) 없음.

**Rationale** (Clarifications Q3):
- MediaWiki API 는 같은 시각 윈도우에 대해 결정적 응답(같은 `rcid` 집합) 을 돌려준다.
- 덮어쓰기 자체가 멱등성의 정의(`f(f(x)) = f(x)`) 를 만족.
- 외부 상태 0 → 운영 복잡도 최소.

**Implementation note**:
- Databricks Volume FUSE 의 rename 원자성이 공식 보장되지 않으므로 `_SUCCESS` marker 패턴을
  사용한다 ([bronze-file-layout.md](./contracts/bronze-file-layout.md) "원자성" 절 참조).
- 최종 경로에 직접 stream write → finalize/fsync → 같은 디렉터리에 0-byte `_SUCCESS` 생성. 다운스트림은
  `_SUCCESS` 존재로 슬롯 완료를 판정.

**Alternatives considered**:
- 외부 상태 저장: 운영 부담만 증가. 기각.

## R5. FR-007 "보정" 의 구체 정책

**Decision**: **MVP 는 자동 백필 없음.** 잡 실패는 다음 정기 실행에서 `*/5 * * * *` cron 에 의해
다음 슬롯이 처리되는 것 뿐이고, 누락된 슬롯은 그대로 데이터 결손으로 남는다. 누락 슬롯의
재처리는 **운영자가 수동으로 잡을 1회 트리거** 하며, 그 1회는 `--params window_start=<ts>`
인자를 받아 해당 슬롯을 다시 적재한다(R4 에 의해 멱등).

**Rationale** (advisor 권고):
- "Overwrite 멱등성 + 직전 슬롯만 자동" 모델과 정합. 자동 백필이 들어가면 잡 1회 = 1 슬롯 가정이
  깨지고 SLA 측정 복잡해짐.
- Wikimedia 의 5분 누락은 통상적으로 사람 개입을 거쳐도 무방한 수준.

**Spec 갱신 영향**:
- FR-007 의 "보정 시도" 는 "직전 슬롯 재시도(=다음 정기 실행) + 수동 재실행 가능" 으로 의미를
  좁힌다. spec 본문은 그대로 두되 본 research 가 운영 해석의 기준이 됨.

**Alternatives considered**:
- **자동 gap detection + 일괄 백필**: 볼륨 경로 list 후 누락 슬롯 N개 재처리. 구현 가능하나 5-min
  스케줄과 시간 예산(SC-002) 안에서 N=많을 때 깨질 위험. 본 MVP 보류, 사용량 패턴 보고 향후 추가.

## R6. 카탈로그/스키마/볼륨의 DAB 정의 위치

**Decision**: `configuration/catalogs.yml` 단일 파일에 다음을 정의한다.

```yaml
resources:
  catalogs:
    wikimedia_dataplay:                # bundle 내부 리소스 키 (영문 snake_case)
      name: wikimedia-dataplay         # 실제 Unity Catalog 이름 (사용자 지정, 하이픈 포함)
  schemas:
    bronze:
      catalog_name: ${resources.catalogs.wikimedia_dataplay.name}
      name: bronze
  volumes:
    recentchanges_raw:
      catalog_name: ${resources.catalogs.wikimedia_dataplay.name}
      schema_name: ${resources.schemas.bronze.name}
      name: recentchanges_raw
      volume_type: MANAGED
```

그리고 `databricks.yml` 의 `include` 에 다음을 추가:

```yaml
include:
  - resources/*.yml
  - resources/**/*.yml
  - configuration/*.yml         # ← 추가
```

**Rationale**:
- DAB CLI v0.299.2 가 `resources.catalogs`/`schemas`/`volumes` 를 1급 리소스로 지원함을 확인
  (bundle_config_schema.json L285/L1667/L1974).
- 카탈로그 이름에 하이픈(`-`) 이 들어가 SQL 참조 시 백틱이 필요하지만 DAB 식별자 자체는
  `snake_case` 로 관리 → 충돌 없음.
- 단일 파일이 사용자 명시 요청과 일치 (`configuration/catalogs.yml` 만 만들어 달라).

**Permissions / 권한 메모**:
- Catalog 생성에는 워크스페이스 메타스토어 admin 권한 필요. 본 SP 가 권한 없으면 deploy 시 catalog
  is_managed 충돌 발생 — 사전 권한 점검 또는 catalog 만 워크스페이스 admin 이 한 번 생성한
  뒤 본 번들은 schema/volume 만 관리하도록 catalog 블록을 임시 주석 처리하는 fallback 을 README
  에 명시한다.

**Alternatives considered**:
- 자산 정의를 `resources/catalogs.yml` 에 두기: include 패턴이 이미 잡혀있어 편리하나 사용자 명시
  요청을 위배. 기각.

## R7. 잡 정의 (`resources/jobs/wikimedia_recentchanges.py`, pydabs) + `databricks.yml` 의 lab target

**Decision (revised 2026-05-22)**: 헌법 원칙 I 의 "pydabs 우선" 정책에 따라 잡 정의를
**`databricks-bundles` Python DSL** 로 작성한다. 서버리스 Python task + cron 트리거의 구조는
동일하되, YAML 대신 Python 객체로 표현되어 타입 안전·합성·동일 toolchain(ruff/black) 사용이
가능해진다.

**`databricks.yml` 의 `lab` target 은 `mode: development` 를 사용하지 않는다.** 본 워크스페이스
(`dbw-dataplay-lab-kc`)가 단일 운영 타깃이고 `wikimedia_recentchanges` 의 `*/5` cron 이 실제로
동작해야 하기 때문이다 (FR-002). DAB CLI 는 `mode: development` 일 때 `trigger_pause_status:
UNPAUSED` 의 target-level 오버라이드를 안전장치로 거부한다 → dev 모드 자체를 끄는 게 깨끗한
해법 (advisor + CI 검증 결과).

`databricks.yml` 의 `lab` target + pydabs 진입점 골자:

```yaml
python:
  venv_path: .venv
  resources:
    - "resources:load_resources"

targets:
  lab:
    # mode 를 명시하지 않음 — dev 모드의 자동 prefix·schedule 일시정지 회피.
    # cron 은 Job 자체의 pause_status=UNPAUSED 로 활성, schema 이름은 정식 `bronze` 유지.
    default: true
    workspace:
      host: https://adb-7405613177889652.12.azuredatabricks.net/
```

`resources/jobs/wikimedia_recentchanges.py` (pydabs):

```python
from databricks.bundles.jobs import (
    CronSchedule, Environment, Job, JobEmailNotifications,
    JobEnvironment, PauseStatus, SparkPythonTask, Task,
)

wikimedia_recentchanges = Job(
    name="wikimedia_recentchanges",
    schedule=CronSchedule(
        quartz_cron_expression="0 */5 * * * ?",
        timezone_id="UTC",
        pause_status=PauseStatus.UNPAUSED,
    ),
    max_concurrent_runs=1,
    tasks=[Task(
        task_key="ingest",
        spark_python_task=SparkPythonTask(
            python_file="../../src/dataplay/jobs/wikimedia_recentchanges.py",
            parameters=[...],          # 본 코드 참조
        ),
        environment_key="default",
    )],
    environments=[JobEnvironment(
        environment_key="default",
        spec=Environment(
            environment_version="2",
            dependencies=["requests>=2.32,<3", "pydantic>=2.7,<3"],
        ),
    )],
    email_notifications=JobEmailNotifications(on_failure=[]),
)
```

`resources/__init__.py` 가 `load_resources_from_current_package_module()` 로 `wikimedia_recentchanges`
변수를 자동 발견한다 — 변수명이 그대로 resource key 가 된다.

**Rationale**:
- `*/5` cron 은 Quartz 6-field 표현 `0 */5 * * * ?` 으로 표기. UTC 고정으로 DST 영향 없음. spec
  본문의 5-field `*/5 * * * *` 는 표준 cron 약식이며 본 구현에서는 Quartz 형식으로 변환된다.
- `max_concurrent_runs: 1` 로 1 슬롯 = 1 인스턴스 보장.
- `environment_version: "2"` 는 현재 권장 서버리스 환경. dependencies 는 잡 단위에 격리.
- Discord 알림은 본 잡 자체가 아닌 워크플로/별도 자동화(추후) 로 처리. 본 MVP 에서는 잡 실패가
  Databricks UI 와 (선택적으로) 워크스페이스 이메일에서 가시화되는 데 만족.
- **dev-mode auto-pause 해제는 `lab` target preset 으로만 가능**. 잡 YAML 의 `pause_status` 단독
  설정으로는 안 됨 (`mode: development` 가 override). 본 결정은 README 의 "스케줄 자동 일시정지"
  관행을 본 잡에 한해 해제하는 것과 동등 — 다른 잡(예: example_job) 의 스케줄도 함께 풀린다는
  부작용 있음. example_job 은 스케줄이 없는 상태이므로 현 시점 영향 없음.

**Alternatives considered**:
- **YAML 잡 정의**: 가능하나 헌법 I 의 "pydabs 우선" 정책에 어긋남. catalogs/schemas/volumes
  같은 단순 자산은 YAML 유지, 잡은 pydabs 로 정의 — 본 결정 (revised 2026-05-22).
- **Classic job_cluster (DBR 16.4)**: 5분마다 클러스터 기동/종료 비용 비효율. 기각 (Complexity #2).
- **Streaming job (Spark Structured Streaming)**: PySpark 도입 + Action API 가 batch 친화적이라
  부적합. 기각.
- **외부 cron / Airflow**: DAB 단일 소스 원칙(헌법 I) 위배. 기각.

## R8. Discord 알림 — MVP 포함 여부

**Decision**: **MVP 에서는 잡 단위 Discord 알림을 구현하지 않는다.** US3(P3) 의 일부로만 보고,
별도 PR/태스크로 다룬다. 본 PR 의 범위에는 FR-008 의 만족 여부를 "deferred" 로 표기.

**Rationale**:
- 기존 CI/CD Discord webhook 은 GitHub Actions 의 deploy 단계에서 발사되는 채널이며, Databricks
  잡 실패를 webhook 으로 보내려면 별도 작업(워크스페이스 webhook 노티 / Databricks Job webhook
  destination 설정) 이 필요. 본 적재 잡의 핵심 가치(데이터 적재) 와 직교.
- spec 의 P3 우선순위에 맞춰 추후 PR 로 분리.

**Alternatives considered**:
- **email_notifications.on_failure 활성화**: 이메일 알림은 단순하지만 운영팀 합의 부재 → 기본
  off 로 둠.

## R9. uv 패키지 매니징 — `pyproject.toml` 신규

**Decision**: 레포 루트에 `pyproject.toml` 을 신규 생성. 다음 골자.

```toml
[project]
name = "dataplay-bundles"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "requests>=2.32,<3",
  "pydantic>=2.7,<3",
]

[dependency-groups]
dev = [
  "pytest>=8",
  "ruff>=0.6",
  "black>=24",
  "responses>=0.25",     # MediaWiki HTTP 더블
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E","F","W","I","UP","B","SIM","ANN"]
ignore = ["ANN101","ANN102"]

[tool.black]
line-length = 100
target-version = ["py312"]

[tool.pytest.ini_options]
addopts = "-q"
testpaths = ["tests"]
```

**Rationale** (헌법 VI, 기술 표준):
- `uv` 가 본 `pyproject.toml` 을 단일 소스로 사용(`uv sync`, `uv run pytest`).
- 잡 task 의 `environment.spec.dependencies` 와 본 dependencies 는 **두 곳에 동일하게** 적힘 —
  이는 환경 격리(잡 환경) vs 로컬 개발 환경의 의도된 분리. CI 에서 두 곳의 일관성을 검증하는
  체크는 후속 enhancement.

**Alternatives considered**:
- **Poetry / pip-tools**: 헌법 VI 가 uv 단일화 강제. 기각.
- **잡 의존성을 별도 `requirements.txt` 로 분리**: 이중 관리 금지(헌법 VI). 기각.

## R10. 테스트 전략

**Decision**: 다음 3 종류의 테스트.

1. **단위 테스트** (`tests/unit/`) — 외부 자원 무관:
   - `test_window.py`: `compute_previous_slot(now)`, `slot_key`, `window_to_path` 함수의 경계 케이스
     (정각, 초/마이크로초 입력, DST 무관 UTC 가정 검증).
   - `test_pipeline.py`: `orchestrate(config, now, source, writer)` 의 합성 — 가짜 `source` 가 정해진
     이벤트 셋을 돌려주면 가짜 `writer` 가 받은 (path, bytes) 가 기대한 구조인지.
2. **통합 테스트** (`tests/integration/`):
   - `test_source.py`: `responses` 라이브러리로 MediaWiki HTTP 응답을 더블링 → `MediaWikiRecentChangesClient`
     가 페이지네이션을 올바르게 수행하고 모든 결과를 합치는지.
   - `test_writer.py`: `tmp_path` 로 `BronzeVolumeWriter` 를 `LocalDirectoryWriter` 어댑터로 대체해
     실제 NDJSON+gzip 파일 형태(라인 수, gzip header, JSON parse) 를 검증.
3. **수동 워크스페이스 검증**: `databricks bundle deploy --target lab` 후 `databricks bundle run
   wikimedia_recentchanges --target lab` 으로 1회 슬롯 적재 확인(SC-004).

**Rationale**:
- 단위 테스트는 SparkSession/Databricks Connect 없이 결정적이고 빠르게 — 헌법 V 준수.
- 통합 테스트는 외부 자원 없이도 행위 검증 가능 (responses + tmp_path).
- 워크스페이스 검증은 별도 e2e 로, 회귀 안전망 위해 CI 의 `bundle validate` 가 매 PR 에서 실행됨.

**Alternatives considered**:
- **Databricks Connect 로 통합 테스트**: 로컬에서 워크스페이스 의존 — 헌법 V 의 "외부 자원 접근
  금지" 위배. 기각.

## R11. 시각 처리 / 타임존

**Decision**: 모든 시각은 **UTC**, `datetime.datetime(tz=zoneinfo.ZoneInfo("UTC"))`. 슬롯 키는 ISO
8601 UTC 문자열 `YYYY-MM-DDTHH:MM:00Z`. 파일 경로의 `year=`, `month=`, ..., `minute=` 는 UTC
기준.

**Rationale**: MediaWiki API 는 UTC `rcstart`/`rcend` 를 그대로 인식. DST/타임존 모호성 제거.

**Alternatives considered**:
- 로컬 타임존(KST): 운영 가시성은 좋으나 DST/시각 환산 부담. 기각.

---

## NEEDS CLARIFICATION 해결 현황

본 plan 의 Technical Context 에서 마킹된 미확정 항목은 0건. 모든 결정은 위 R1–R11 로 해소됨.

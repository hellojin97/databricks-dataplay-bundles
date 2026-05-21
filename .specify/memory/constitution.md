<!--
Sync Impact Report
==================
Version change: (template) → 1.0.0
Bump rationale: 초기 비준. 빈 템플릿(placeholder) 상태에서 실제 프로젝트 원칙을 처음 확정하므로
                semantic versioning 의 초기 안정 버전인 1.0.0 으로 시작한다.

Modified principles (template placeholder → concrete):
  - [PRINCIPLE_1_NAME] → I. Bundle-First 잡 정의 (NON-NEGOTIABLE)
  - [PRINCIPLE_2_NAME] → II. 호출부와 비즈니스 로직 분리 (NON-NEGOTIABLE)
  - [PRINCIPLE_3_NAME] → III. 함수형 변환 · 클래스형 I/O
  - [PRINCIPLE_4_NAME] → IV. 명시적 SparkSession 주입 (NON-NEGOTIABLE)
  - [PRINCIPLE_5_NAME] → V. 테스트 우선 (pytest)
Added principles (확장):
  - VI. 타입 안전성과 포맷 일관성
  - VII. 한국어 문서화 · 영어 식별자

Added sections:
  - 기술 표준 (Technology Standards) — [SECTION_2_*] 자리 대체
  - 개발 워크플로 (Development Workflow) — [SECTION_3_*] 자리 대체

Removed sections: 없음

Templates requiring updates:
  - ✅ .specify/templates/plan-template.md  — Constitution Check 게이트는 본 헌법의
       원칙을 직접 참조하도록 사용. 템플릿 자체 수정 불필요.
  - ✅ .specify/templates/spec-template.md  — 필수 섹션이 헌법과 충돌하지 않음.
  - ✅ .specify/templates/tasks-template.md — 단위/통합 테스트 단계 구분이 원칙 V와 정합.
  - ✅ .specify/templates/checklist-template.md — 변경 불필요.
  - ✅ README.md — 기존 DAB·CI/CD 설명과 일관. 헌법 원칙과 충돌 없음.
  - ✅ CLAUDE.md — "현재 plan 을 읽어 기술 컨텍스트를 확인" 지침 유지.

Follow-up TODOs:
  - 없음. 모든 placeholder 가 구체값으로 대체됨.
-->

# databricks-dataplay-bundles Constitution

본 헌법은 Azure Databricks(워크스페이스 `dbw-dataplay-lab-kc`) 위에서 Databricks Asset Bundle(DAB)
과 Lakeflow Job 으로 동작하는 데이터 파이프라인 코드를 작성·리뷰·배포할 때 따라야 할 **변경 불가능한
규약** 을 정의한다. 모든 PR, 코드 리뷰, 자동화(예: `/speckit-*`)는 본 문서를 1차 기준으로 삼는다.

## Core Principles

### I. Bundle-First 잡 정의 (NON-NEGOTIABLE)

모든 운영성 잡과 파이프라인은 **Databricks Asset Bundle 정의로만 배포한다**. 워크스페이스 UI 에서
손수 만든 잡, ad-hoc 노트북 스케줄은 운영 자산으로 간주하지 않는다.

규칙:

- 잡 매니페스트는 `resources/jobs/<job_name>.yml` (또는 `resources/jobs/<job_name>.py` — pydabs)
  에만 정의한다. `databricks.yml` 의 `include` 가 이를 자동 포함한다.
- 잡·태스크의 **구조(클러스터, 의존성, 스케줄, 권한)** 는 pydabs 또는 YAML 로 코드 기반으로 표현하며,
  복잡한 반복·분기 로직이 필요한 경우 pydabs 를 우선한다.
- `databricks bundle validate --target lab` 가 통과하지 못한 변경은 머지하지 않는다.
- 워크스페이스 host 같은 환경 식별자는 `databricks.yml` 의 `targets.*.workspace.host`
  단일 소스에서만 관리한다 — 환경변수/시크릿/코드 내 하드코딩 금지.

근거: 형상관리·재현가능성·롤백 능력을 확보하고, 워크스페이스 UI 의 잡 정의와 레포의 정의가
어긋나는 drift 를 원천 차단한다.

### II. 호출부와 비즈니스 로직 분리 (NON-NEGOTIABLE)

태스크 엔트리포인트 스크립트는 **호출부** 만 담당한다. 데이터 변환·검증 등 비즈니스 로직은
재사용 가능한 **모듈** 로 분리한다.

규칙:

- 잡 태스크가 가리키는 스크립트(예: `src/<package>/jobs/<task>.py`)는 다음만 수행한다:
  (a) 인자/환경 파싱, (b) SparkSession 등 의존성 생성, (c) 비즈니스 로직 모듈 호출,
  (d) 결과 기록·로그.
- 비즈니스 로직(변환 함수, 도메인 검증, 집계 규칙)은 `src/<package>/<domain>/...` 처럼 도메인별
  서브패키지에 둔다. 태스크 스크립트에서 import 만 해서 사용한다.
- 태스크 스크립트에는 단위 테스트를 강제하지 않는다. 대신 모듈에 단위 테스트가 존재해야 한다.
- 동일 비즈니스 로직을 두 곳 이상의 태스크에서 복제 구현하면 안 된다. 공통 모듈로 추출한다.

근거: 잡 정의 변경(스케줄·클러스터)과 비즈니스 로직 변경(컬럼·규칙)을 분리해 리뷰 비용과 회귀
위험을 낮춘다. 단위 테스트 대상이 명확해진다.

### III. 함수형 변환 · 클래스형 I/O

데이터 형태는 다음 원칙을 따른다:

- **변환은 함수로** 표현하며, `DataFrame.transform(...)` 으로 합성한다. 변환 함수는 부수효과가
  없어야 하며, 입력 `DataFrame` 과 명시적 파라미터만으로 출력 `DataFrame` 을 결정해야 한다.
- **I/O 는 클래스로** 캡슐화한다 (예: `BronzeSource`, `SilverWriter`). I/O 클래스는 SparkSession
  과 설정을 생성자로 받아 `read()` / `write()` 같은 명시적 메서드를 제공한다.
- **외부 입력(잡 파라미터, 설정 파일, API 응답)** 은 **Pydantic** 모델로 받아 검증한다.
  미검증 dict 를 비즈니스 로직 깊숙이 흘려보내면 안 된다.
- **내부 데이터(불변 값 묶음, 변환 함수 간 전달용)** 는 `@dataclass(frozen=True)` 를 우선한다.
  Pydantic 은 경계에서만 사용한다.

근거: 변환의 합성·테스트 가능성을 극대화하고, I/O 경계에서의 부수효과·외부 신뢰 경계를 명확히
분리한다. 내부 데이터에까지 Pydantic 을 쓰면 직렬화 비용이 누적된다.

### IV. 명시적 SparkSession 주입 (NON-NEGOTIABLE)

`SparkSession` 은 **항상 함수/메서드 인자로 명시적으로 전달**한다.

규칙:

- 모듈 전역 변수, 싱글톤, `SparkSession.builder.getOrCreate()` 호출을 비즈니스 로직 모듈 안에
  두지 않는다. `getOrCreate()` 는 태스크 스크립트(호출부) 또는 테스트 fixture 에서만 호출한다.
- `SparkSession` 을 받는 함수의 첫 번째 인자명은 `spark` 로 통일한다.
- 변환 함수가 SparkSession 을 직접 필요로 한다면(임시 뷰, broadcast 등), 인자로 받는다.

근거: 전역 SparkSession 은 테스트 격리(로컬 세션 주입)와 멀티 잡 실행(서로 다른 세션 설정)을
망가뜨린다. 명시적 주입은 의존성 가시화와 단위 테스트의 전제조건이다.

### V. 테스트 우선 (pytest)

테스트 도구는 **pytest** 로 통일한다. 변환 함수에 대한 단위 테스트는 필수다.

규칙:

- **변환 함수**(원칙 III) 는 단위 테스트 없이 머지할 수 없다. 단위 테스트는 로컬 SparkSession
  fixture 를 사용하고 외부 자원(Databricks workspace, Unity Catalog, 클라우드 스토리지) 에
  접근하면 안 된다.
- **통합 테스트**는 `tests/integration/` 에 분리하고, 로컬 `SparkSession` 을 fixture 로 주입한다
  (원칙 IV). Databricks-connect 가 필요한 경우 fixture 에서 격리한다.
- I/O 클래스는 fake/double 또는 임시 경로(`tmp_path`) 를 사용한 통합 테스트로 검증한다.
- 새 기능(특히 사용자 스토리)을 구현하기 전, 해당 단위 테스트를 먼저 작성해 **실패 → 구현 → 통과**
  사이클을 거치는 것을 권장한다. (NON-NEGOTIABLE 은 아니지만 강력히 SHOULD.)
- 테스트 파일은 `tests/unit/test_<module>.py`, `tests/integration/test_<flow>.py` 명명 규칙을
  따른다.

근거: 변환 함수의 회귀를 빠르게 검출하고, SparkSession 주입(원칙 IV)이 실제로 가능한지 테스트가
강제한다.

### VI. 타입 안전성과 포맷 일관성

코드 품질은 도구로 자동 강제한다.

규칙:

- **모든 함수·메서드 시그니처에 타입 힌트** 를 작성한다. `-> None` 도 명시한다.
- 포맷터는 **black**, 린터는 **ruff** 를 사용하며 CI 에서 위반 시 실패시킨다. 룰셋은
  `pyproject.toml` 에 단일 정의로 관리한다.
- 식별자 규칙:
  - 함수명·메서드명: 영어 `snake_case`.
  - 클래스명: 영어 `PascalCase`.
  - 변수명: 영어 `snake_case`.
  - 모듈명: 영어 `snake_case`.
- 모듈 식별자는 영어로만 작성한다. 한국어/한자/특수문자 식별자는 금지한다.
- 의존성은 **uv** 로 관리하고, 공개 의존성 선언은 `pyproject.toml` 의 `[project.dependencies]`
  (또는 `[dependency-groups]`) 한 곳에서만 한다. `requirements.txt` 와의 이중 관리는 금지한다.

근거: 사람 리뷰가 잡아내기 어려운 일관성 결함을 도구로 비용 0 에 가깝게 차단한다. uv 단일화는
재현 가능한 환경(특히 Databricks 16.4 + Python 3.12) 을 보장한다.

### VII. 한국어 문서화 · 영어 식별자

자연어 문서는 한국어, 코드 식별자는 영어로 명확히 분리한다.

규칙:

- 모든 산출 문서(`spec.md`, `plan.md`, `tasks.md`, ADR, 핸드온 문서, PR 본문) 는 **한국어**
  로 작성한다.
- **모든 코드 주석은 한국어** 로 작성한다 (단순 docstring 의 인자 설명 포함).
- **모든 모듈 스크립트 최상단에 `"""..."""` docstring 으로 모듈 설명** 을 작성한다. 1줄 요약 +
  필요 시 빈 줄 + 상세 설명 구조를 사용한다.
- speckit (`/speckit-*`) 명령이 사용자에게 노출하는 진행 메시지, 질문, 요약, 보고는 모두 한국어
  로 출력한다.
- 위 규칙에도 불구하고 **식별자(함수명/클래스명/변수명/모듈명)** 는 원칙 VI에 따라 영어로만 둔다.

근거: 팀의 1차 언어가 한국어이므로 의사결정 맥락은 한국어 문서로 남기고, 식별자는 도구 호환성과
오타·자동완성 안정성을 위해 영어로 통일한다.

## 기술 표준 (Technology Standards)

본 프로젝트의 모든 신규 코드와 잡은 다음 표준을 따라야 한다.

- **런타임**: Databricks Runtime 16.4 LTS. 잡 클러스터 정의는 본 런타임을 기본값으로 한다.
- **언어**: Python 3.12 이상. `pyproject.toml` 의 `requires-python` 으로 강제한다.
- **데이터 처리**: PySpark 3.5 이상. DataFrame API 를 1차 인터페이스로 사용한다.
- **잡 패키징**: Databricks Asset Bundle (DAB). 잡 정의는 **pydabs** 우선, 단순한 케이스는
  YAML 도 허용한다.
- **패키지·환경 관리**: `uv` + `pyproject.toml`. 다른 패키지 매니저 도입 금지.
- **테스트**: `pytest` + 로컬 `SparkSession` fixture.
- **포맷·린트**: `black`, `ruff`. 설정은 `pyproject.toml` 중앙 관리.
- **CI/CD 인증**: GitHub OIDC → Azure SP → Databricks. 워크스페이스 토큰/패스워드 시크릿 저장
  금지 (README "GitHub 레포 설정값" 참조).
- **소스 트리 관례**:
  - 실행 코드: `src/<package>/...`
  - 태스크 엔트리포인트: `src/<package>/jobs/<task>.py`
  - 잡 정의: `resources/jobs/<job_name>.{yml,py}`
  - 테스트: `tests/unit/`, `tests/integration/`
  - 단일 패키지/단일 프로젝트 구조를 기본으로 하며, 멀티 패키지가 필요하면 plan 의 Complexity
    Tracking 에 정당화를 기록한다.

## 개발 워크플로 (Development Workflow)

본 헌법은 다음 워크플로에서 게이트로 사용된다.

- **명세 작성 (`/speckit-specify`)**: 사용자 스토리·요구사항을 한국어로 작성한다(원칙 VII).
- **계획 (`/speckit-plan`)**: "Constitution Check" 게이트에서 본 헌법의 7개 원칙을 모두
  점검한다. 위반이 있다면 plan 의 *Complexity Tracking* 표에 정당화 사유와 거부된 단순 대안을
  적어야 머지 가능하다.
- **태스크 (`/speckit-tasks`)**: 변환 함수에 대한 단위 테스트 태스크를 누락하면 안 된다
  (원칙 V).
- **구현 (`/speckit-implement`)**: 진행 메시지는 한국어로 노출한다(원칙 VII).
- **분석/체크리스트 (`/speckit-analyze`, `/speckit-checklist`)**: 본 헌법과의 정합성을
  검증한다.
- **PR 검토**: 리뷰어는 (a) Bundle 정의 위치, (b) 호출부/모듈 분리, (c) SparkSession 명시적
  주입, (d) 타입 힌트와 ruff/black 통과, (e) 한국어 문서/주석을 확인한다.
- **로컬 검증**: `databricks bundle validate --target lab` 를 PR 전에 실행하는 것을 SHOULD
  로 한다. main 푸시 시 CI 가 동일 검증과 deploy 를 수행한다.

## Governance

- **헌법의 권위**: 본 헌법은 코드 스타일 가이드, 임시 합의, 개별 PR 코멘트에 **우선한다**.
  헌법과 다른 관행이 있다면 헌법 수정 PR 을 먼저 진행한다.
- **수정 절차**:
  1. 수정 제안은 PR 로 제출한다 — 변경 부분, 영향 받는 템플릿, 마이그레이션 영향(있다면)을
     본문에 명기한다.
  2. 본 파일과 함께 `.specify/templates/*.md` 의 정합성을 동시에 갱신한다 (Sync Impact Report
     의 체크리스트).
  3. 최소 1인의 리뷰 승인 후 머지한다.
- **버전 정책 (semantic versioning)**:
  - **MAJOR**: 원칙 삭제 또는 호환되지 않는 재정의 (예: NON-NEGOTIABLE 의 의미 변경).
  - **MINOR**: 새 원칙/섹션 추가, 또는 실질적으로 강화되는 가이드 추가.
  - **PATCH**: 표현 정비, 오탈자 수정, 비의미적 정리.
- **준수 검토**: 모든 PR 리뷰는 본 헌법 위반 여부를 점검한다. 위반이 불가피하면 plan 의
  *Complexity Tracking* 표 또는 PR 본문에 정당화를 적는다.
- **런타임 가이드**: 본 헌법과 함께 `README.md`, `docs/handson/*`, `docs/reference/*` 를
  실무 가이드로 사용한다. 가이드 문서는 헌법을 우회할 수 없다.

**Version**: 1.0.0 | **Ratified**: 2026-05-21 | **Last Amended**: 2026-05-21

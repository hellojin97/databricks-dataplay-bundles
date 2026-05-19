# 실습 2: 번들 골격 + 스키마 자동완성

[실습 1](01-azure-prereq.md)에서 Azure 사전 준비가 끝났다는 전제. 이 문서는 로컬 번들 골격과 VSCode 자동완성 세팅을 다룹니다.

---

## 2-1. 디렉터리 골격

```text
databricks-dataplay-bundles/
├── databricks.yml              # 번들 정의 (타깃·워크스페이스)
├── bundle_config_schema.json   # 자동완성용 JSON 스키마 (커밋함)
├── resources/                  # 잡/파이프라인 등 리소스 정의 *.yml
├── src/                        # 잡이 실행할 코드
└── .github/workflows/          # CI (validate / deploy)
```

생성:

```bash
cd ~/Workspace/GitHub/databricks-dataplay-bundles
mkdir -p resources src .github/workflows
touch src/.gitkeep
```

---

## 2-2. `databricks.yml`

```yaml
# yaml-language-server: $schema=./bundle_config_schema.json
bundle:
  name: dataplay-bundles

include:
  - resources/*.yml
  - resources/**/*.yml

targets:
  lab:
    mode: development
    default: true
    workspace:
      host: https://adb-7405613177889652.12.azuredatabricks.net/
```

| 항목 | 의미 |
|---|---|
| 1번째 줄 `$schema` 주석 | VSCode 자동완성 연결 (2-3에서 설명, **반드시 첫 줄**) |
| `bundle.name` | 워크스페이스 배포 경로·리소스 prefix에 사용 |
| `include` | `resources/` 의 최상위·하위 폴더 `*.yml` 자동 포함 |
| `targets.lab` | 단일 타깃. `mode: development` = 리소스명 `[dev you]` prefix + 스케줄 자동 일시정지(실수 방지) |
| `workspace.host` | 배포 대상 워크스페이스. 비밀값 아님 → 여기 한 곳에만 둠 |

> 호스트가 비밀이 아닌 이유, 인증 사슬은 → [reference/azure-sp-oidc-federation.md §5~6](../reference/azure-sp-oidc-federation.md#5-이-레포에서--azure를-거쳐-databricks까지)

---

## 2-3. VSCode 자동완성 (번들 스키마)

기본 상태에선 `databricks.yml`에서 키 자동완성·오타 검증이 안 됩니다. Databricks CLI가 스키마를 JSON으로 내보낼 수 있어 이를 YAML에 연결합니다.

### 전제: Red Hat YAML 확장

VSCode에 **`redhat.vscode-yaml`** 확장이 설치돼 있어야 `$schema` 주석을 인식합니다.

### 스키마 생성 (커밋 방식)

```bash
cd ~/Workspace/GitHub/databricks-dataplay-bundles
databricks bundle schema > bundle_config_schema.json
```

- `databricks.yml` 첫 줄에 이미 `# yaml-language-server: $schema=./bundle_config_schema.json` 연결됨
- `resources/*.yml`에서도 쓰려면 그 파일 첫 줄에 `# yaml-language-server: $schema=../bundle_config_schema.json`
- 파일마다 주석이 싫으면 `.vscode/settings.json`:

  ```json
  {
    "yaml.schemas": {
      "./bundle_config_schema.json": ["databricks.yml", "resources/**/*.yml"]
    }
  }
  ```

### ⚠️ 재생성 규칙

`bundle_config_schema.json`은 **설치된 Databricks CLI 버전에 종속**됩니다. (생성 시점 기준 `v0.299.2`)

> CLI를 업그레이드하면 → `databricks bundle schema > bundle_config_schema.json` 다시 실행 후 **재커밋**.
> 안 하면 자동완성이 옛 스키마 기준이라 신규 필드가 "잘못된 키"로 표시될 수 있음.

### 커밋 vs ignore — 이 레포는 "커밋"

| | 선택 |
|---|---|
| 방식 | **커밋** (소규모 lab, clone 즉시 팀원 자동완성) |
| 결과 | `.gitignore`에 `bundle_config_schema.json`을 **넣지 않음** |
| 대가 | CLI 버전 업 시 재생성·재커밋 (위 규칙) |

---

## 완료 체크리스트

- [ ] `head -1 databricks.yml` → `# yaml-language-server: $schema=./bundle_config_schema.json`
- [ ] `python3 -c "import json;json.load(open('bundle_config_schema.json'))"` → 에러 없음
- [ ] `git status --porcelain bundle_config_schema.json` → `??` (ignore 안 됨, 커밋 예정)
- [ ] VSCode에서 `databricks.yml` 열었을 때 `bundle:` 하위 키 자동완성 동작
- [ ] `redhat.vscode-yaml` 확장 설치됨

다음: `resources/`에 첫 리소스(잡) 정의 추가 → CI 워크플로우 작성.

# databricks-dataplay-bundles

Azure Databricks 워크스페이스(`dbw-dataplay-lab-kc`)에 **Databricks Asset Bundle(DAB)** 로 잡·파이프라인을 배포하는 레포. CI/CD는 GitHub Actions, 인증은 **GitHub OIDC → Azure SP → Databricks** (시크릿 없음).

워크스페이스 인프라 자체는 별도 레포 [`azure-infra`](https://github.com/hellojin97/azure-infra)에서 Terraform으로 관리합니다.

---

## 동작 개요

```mermaid
flowchart LR
    PR[Pull Request] -->|bundle-validate.yml| V[databricks bundle validate]
    M[main push] -->|bundle-deploy.yml| D[validate + deploy]
    V -.OIDC.-> AAD[Azure AD]
    D -.OIDC.-> AAD
    AAD --> WS[(Databricks 워크스페이스)]
```

- **PR**: `databricks bundle validate` (읽기전용 검증)
- **main 머지**: `validate` → `deploy` (실제 반영) → Discord 알림
- 인증: azure-infra와 **동일 SP**를 OIDC로 재사용. 자세한 원리 → [docs/reference/azure-sp-oidc-federation.md](docs/reference/azure-sp-oidc-federation.md)

---

## ⚠️ 처음 한 번: Azure 사전 작업 (필수)

이걸 안 하면 CI 첫 실행이 인증 실패합니다. SP에 **이 레포용 federated credential 2개**를 등록해야 합니다.

→ 절차: **[docs/handson/01-azure-prereq.md](docs/handson/01-azure-prereq.md)**

요지: 같은 SP에 subject가 아래인 FC를 추가/갱신.
- `repo:hellojin97/databricks-dataplay-bundles:ref:refs/heads/main`
- `repo:hellojin97/databricks-dataplay-bundles:pull_request`

---

## 레포 구조

```text
databricks-dataplay-bundles/
├── databricks.yml              # 번들 정의 (타깃 lab, 워크스페이스 host)
├── bundle_config_schema.json   # VSCode 자동완성 스키마 (커밋함)
├── resources/                  # 잡/파이프라인 정의 *.yml
│   └── example_job.yml
├── src/                        # 잡 실행 코드
│   └── example.py
├── .github/workflows/
│   ├── bundle-validate.yml     # PR: validate
│   └── bundle-deploy.yml       # main push: validate + deploy + 알림
└── docs/
    ├── handson/                # 단계별 실습 가이드
    └── reference/              # 개념 설명
```

---

## GitHub 레포 설정값

OIDC라 SP 식별자는 비밀이 아님 → **Variables**. Discord webhook만 **Secret**.
(이유 → [reference §6](docs/reference/azure-sp-oidc-federation.md#6-왜-github-secrets가-아니라-variables인가))

| 종류 | 이름 | 값 출처 |
|---|---|---|
| Variable | `AZURE_CLIENT_ID` | azure-infra와 동일 SP appId |
| Variable | `AZURE_TENANT_ID` | azure-infra와 동일 |
| Variable | `AZURE_SUBSCRIPTION_ID` | azure-infra와 동일 |
| Secret | `DATABRICKS_BUNDLES_DISCORD_WEBHOOK_URL` | Discord webhook (azure-infra 것 재사용 가능) |

```bash
gh variable set AZURE_CLIENT_ID       --body "<appId>"
gh variable set AZURE_TENANT_ID       --body "<tenantId>"
gh variable set AZURE_SUBSCRIPTION_ID --body "<subscriptionId>"
gh secret   set DATABRICKS_BUNDLES_DISCORD_WEBHOOK_URL --body "<webhook-url>"
```

> 워크스페이스 host는 GitHub 설정이 아니라 `databricks.yml`의 `targets.lab.workspace.host` 한 곳에서만 관리합니다(단일 소스).

---

## 로컬 개발

```bash
az login                                  # 개인 계정으로 로컬 인증
databricks bundle validate --target lab   # 구성 검증
databricks bundle deploy   --target lab   # 워크스페이스에 배포
databricks bundle run example_job --target lab   # 잡 실행
```

`mode: development`라 배포된 리소스는 `[dev <you>]` prefix가 붙고 스케줄은 자동 일시정지됩니다(운영 리소스와 격리).

---

## 워크로드 추가하기

1. 실행 코드를 `src/`에 추가
2. `resources/<name>.yml`에 잡/파이프라인 정의 (`databricks.yml`의 `include`가 자동 포함)
3. PR → validate 통과 확인 → main 머지 시 자동 배포

상세 → [docs/handson/02-bundle-setup.md](docs/handson/02-bundle-setup.md)

---

## 스키마 자동완성 유지보수

`bundle_config_schema.json`은 **Databricks CLI 버전에 종속**(생성 시 `v0.299.2`). CLI 업그레이드 시:

```bash
databricks bundle schema > bundle_config_schema.json
git add bundle_config_schema.json && git commit -m "chore: regenerate bundle schema"
```

VSCode 자동완성은 `redhat.vscode-yaml` 확장 필요.

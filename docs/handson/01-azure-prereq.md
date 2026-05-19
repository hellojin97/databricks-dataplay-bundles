# 실습 1: Azure 사전 준비 (Phase 0)

GitHub Actions가 Databricks Asset Bundle을 배포하려면, **워크플로우가 처음 돌기 전에** Azure 쪽에서 신뢰 관계를 미리 맺어둬야 합니다. 한 번만 수동으로 진행하는 작업입니다.

개념이 궁금하면 먼저 → [docs/reference/azure-sp-oidc-federation.md](../reference/azure-sp-oidc-federation.md)

---

## 이 레포의 전제

이 레포는 새 SP를 만들지 않고, **`azure-infra` 레포가 이미 만들어 둔 SP를 재사용**합니다. 그 SP는 구독 범위 `Owner`/`Contributor`를 갖고 있어 Databricks 워크스페이스 admin으로 자동 인정됩니다.

따라서 Phase 0에서 **새로 하는 일은 단 하나**: 그 SP에 *이 레포용* federated credential을 추가하는 것.

| 항목 | 값 (이 환경 기준) |
|---|---|
| GitHub 레포 | `hellojin97/databricks-dataplay-bundles` |
| Databricks 워크스페이스 | `https://adb-7405613177889652.12.azuredatabricks.net/` |
| 재사용 SP `AZURE_CLIENT_ID` (appId) | `d27c582a-59a0-4c8f-a12b-97cabd6daeb8` |
| `AZURE_TENANT_ID` | `3026e9ae-1c6f-48bc-aa40-711484d97639` |
| `AZURE_SUBSCRIPTION_ID` | `d17a6b68-0254-4879-8601-3e71f5b8e06c` |
| SP application **Object ID** | `1e200a4f-64c3-4cb9-b44b-c3a640bcd88f` |

---

## 사전 조건

- Azure CLI(`az`) 설치 + `az login` 완료
- GitHub CLI(`gh`) 설치 + 로그인 (변수/시크릿 등록 단계에서 사용)
- 대상 GitHub 레포가 이미 생성돼 있을 것

---

## 0-1. 재사용할 SP의 appId 확인

`azure-infra` 레포의 GitHub Variables에서 가져옵니다.

```bash
gh variable list --repo hellojin97/azure-infra
```

출력의 `AZURE_CLIENT_ID` / `AZURE_TENANT_ID` / `AZURE_SUBSCRIPTION_ID` 세 값을 메모합니다. 이 레포에서도 같은 값을 그대로 씁니다.

---

## 0-2. appId → application Object ID 조회

federated credential을 붙이는 명령(`--id`)에는 appId가 아니라 **application Object ID**가 필요합니다 (둘은 다른 값 — [레퍼런스 §1](../reference/azure-sp-oidc-federation.md#1-등장인물-정리) 참고).

```bash
az login   # 아직 안 했다면

az ad app show --id d27c582a-59a0-4c8f-a12b-97cabd6daeb8 --query id -o tsv
# → 1e200a4f-64c3-4cb9-b44b-c3a640bcd88f
```

---

## 0-3. 이 레포용 federated credential 2개 추가

워크플로우가 **main push 배포**와 **PR 검증** 두 가지를 쓰므로 FC도 2개 필요합니다 (이유 → [레퍼런스 §4](../reference/azure-sp-oidc-federation.md#4-federated-credential--신뢰의-핵심)).

먼저 기존 패턴을 확인 (이름 충돌 방지 + subject 형식 맞추기):

```bash
az ad app federated-credential list --id 1e200a4f-64c3-4cb9-b44b-c3a640bcd88f \
  --query "[].{name:name, subject:subject}" -o table
```

> `azure-infra`의 FC(`github-main-branch`, `github-pull-request`)가 이미 같은 SP에 있습니다. **이름이 겹치면 안 되므로** 이 레포 것은 `-databricks-` 를 넣어 구분합니다.

**main 브랜치용:**
```bash
az ad app federated-credential create --id 1e200a4f-64c3-4cb9-b44b-c3a640bcd88f --parameters '{
  "name": "github-databricks-bundles-main",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:hellojin97/databricks-dataplay-bundles:ref:refs/heads/main",
  "audiences": ["api://AzureADTokenExchange"]
}'
```

**pull request용:**
```bash
az ad app federated-credential create --id 1e200a4f-64c3-4cb9-b44b-c3a640bcd88f --parameters '{
  "name": "github-databricks-bundles-pr",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:hellojin97/databricks-dataplay-bundles:pull_request",
  "audiences": ["api://AzureADTokenExchange"]
}'
```

각각 `subject`가 포함된 JSON 응답이 나오면 성공.

### ⚠️ 레포 이름을 바꿨다면 (실제로 겪은 케이스)

레포 이름을 `databricks-bundles` → `databricks-dataplay-bundles`로 바꾸면, 먼저 만든 FC의 `subject`가 옛 이름으로 박혀 **인증이 전부 깨집니다**. 삭제하지 말고 `update`로 subject만 교정합니다 (update는 PATCH가 아니라 전체 객체 PUT — 모든 필드를 다시 보내야 함):

```bash
az ad app federated-credential update \
  --id 1e200a4f-64c3-4cb9-b44b-c3a640bcd88f \
  --federated-credential-id github-databricks-bundles-main \
  --parameters '{
    "name": "github-databricks-bundles-main",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:hellojin97/databricks-dataplay-bundles:ref:refs/heads/main",
    "audiences": ["api://AzureADTokenExchange"]
  }'

az ad app federated-credential update \
  --id 1e200a4f-64c3-4cb9-b44b-c3a640bcd88f \
  --federated-credential-id github-databricks-bundles-pr \
  --parameters '{
    "name": "github-databricks-bundles-pr",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:hellojin97/databricks-dataplay-bundles:pull_request",
    "audiences": ["api://AzureADTokenExchange"]
  }'
```

`--federated-credential-id`에는 이름 또는 GUID를 넣을 수 있습니다.

### JSON 안에서 셸 변수 쓰기

작은따옴표 JSON 안에서는 변수 치환이 안 됩니다. 변수만 잠깐 빠져나오는 패턴: `'repo:'"$GH_REPO"':pull_request'`

---

## 0-4. SP가 워크스페이스 admin인지 확인

Azure Databricks는 워크스페이스 리소스에 `Contributor`/`Owner` RBAC를 가진 주체를 자동으로 admin으로 인정합니다 ([레퍼런스 §5](../reference/azure-sp-oidc-federation.md#5-이-레포에서--azure를-거쳐-databricks까지)).

```bash
az role assignment list \
  --assignee d27c582a-59a0-4c8f-a12b-97cabd6daeb8 \
  --scope "/subscriptions/d17a6b68-0254-4879-8601-3e71f5b8e06c/resourceGroups/rg-dataplay-lab-kc" \
  --include-inherited \
  --query "[].{role:roleDefinitionName, scope:scope}" -o table
```

기대 결과 (구독 범위에서 상속):

```text
Role         Scope
-----------  ---------------------------------------------------
Contributor  /subscriptions/d17a6b68-0254-4879-8601-3e71f5b8e06c
Owner        /subscriptions/d17a6b68-0254-4879-8601-3e71f5b8e06c
```

`Contributor` 또는 `Owner`가 보이면 → SP가 워크스페이스 admin. 추가 작업 불필요.
비어 있으면 → Databricks 워크스페이스에 SP를 SCIM으로 admin 추가 필요 (별도 절차).

---

## 완료 체크리스트

- [ ] `az ad app federated-credential list --id <ObjectID> -o table` →
      `github-databricks-bundles-main`, `github-databricks-bundles-pr` 두 줄이 보이고
      subject가 `repo:hellojin97/databricks-dataplay-bundles:...`로 **정확히** 들어가 있음
- [ ] `azure-infra`의 기존 FC 2개는 그대로 보존돼 있음 (건드리지 않음)
- [ ] SP가 구독/RG 범위에 `Contributor` 또는 `Owner` 보유

여기까지면 Azure 사전 준비 끝. 다음은 로컬 번들 골격 → `databricks.yml` → 워크플로우 작성.

# 실습 3: GitHub Actions CI/CD 배포

[실습 1](01-azure-prereq.md)(Azure 사전작업), [실습 2](02-bundle-setup.md)(번들 골격)가 끝났다는 전제. 이 문서는 워크플로우 작성 → GitHub 설정 → push → 첫 배포 검증까지를 다룹니다.

개념 배경: [reference/azure-sp-oidc-federation.md](../reference/azure-sp-oidc-federation.md), [reference/databricks-asset-bundles.md](../reference/databricks-asset-bundles.md)

---

## 3-1. 워크플로우 2개

azure-infra의 plan/apply 분리 패턴과 동일: **PR = validate(읽기전용), main push = deploy(반영)**.

```text
.github/workflows/
├── bundle-validate.yml   ─ pull_request           → databricks bundle validate
└── bundle-deploy.yml     ─ push:main / dispatch    → validate + deploy + Discord
```

핵심 공통 요소:

| 요소 | 이유 |
|---|---|
| `permissions: id-token: write` | OIDC 토큰 발급 필수. 없으면 `azure/login` 실패 |
| `azure/login@v2` + `vars.AZURE_*` | azure-infra와 **동일 SP·동일 변수 재사용** |
| `DATABRICKS_AUTH_TYPE: azure-cli` | azure/login이 만든 Azure CLI 세션을 Databricks CLI가 그대로 사용 |
| `databricks/setup-cli@main` | 러너에 Databricks CLI 설치 |

deploy 전용:

| 요소 | 이유 |
|---|---|
| `concurrency: bundle-deploy` | 동시 배포 충돌 방지 (validate는 읽기전용이라 불필요) |
| `Notify Discord` (`if: always()`) | 성공/실패 모두 알림 (azure-infra 운영 패턴) |
| `workflow_dispatch` | 수동 재실행 경로 |

> `DATABRICKS_HOST`를 워크플로우에 안 둔 이유: 호스트는 `databricks.yml`의 `targets.lab.workspace.host` 한 곳이 단일 소스. 중복 두면 드리프트.

paths 필터에 `bundle_config_schema.json`도 포함 → 스키마만 갱신돼도 validate 재실행.

---

## 3-2. GitHub 레포 설정값 등록

OIDC라 SP 식별자는 비밀 아님 → **Variables**. Discord webhook만 **Secret**.

```bash
R=hellojin97/databricks-dataplay-bundles

gh variable set AZURE_CLIENT_ID       --repo "$R" --body "d27c582a-59a0-4c8f-a12b-97cabd6daeb8"
gh variable set AZURE_TENANT_ID       --repo "$R" --body "3026e9ae-1c6f-48bc-aa40-711484d97639"
gh variable set AZURE_SUBSCRIPTION_ID --repo "$R" --body "d17a6b68-0254-4879-8601-3e71f5b8e06c"

# 시크릿은 프롬프트로 입력 (값이 로그/히스토리에 안 남음)
gh secret set DATABRICKS_BUNDLES_DISCORD_WEBHOOK_URL --repo "$R"
```

확인:

```bash
gh variable list --repo "$R"   # AZURE_* 3개
gh secret   list --repo "$R"   # DATABRICKS_BUNDLES_DISCORD_WEBHOOK_URL
```

---

## 3-3. ⚠️ push 순서 (함정)

`bundle-deploy.yml`은 **main push 즉시 실행**됩니다. 그래서:

> Variables/Secret을 **먼저 등록(3-2)** 한 뒤 push 해야 첫 배포가 한 번에 성공합니다.
> 순서를 바꾸면 첫 실행이 인증 단계에서 실패하고 Discord에 실패 알림이 갑니다(설정 후 재실행하면 해결되지만 불필요한 빨간 X).

권장 순서: **Phase 0(FC) → 3-2(설정) → push**.

```bash
git add -A
git commit -m "Initial Databricks Asset Bundle scaffold"
git push -u origin main
```

---

## 3-4. 첫 배포 검증

push 후 `Bundle Deploy`가 자동 실행됩니다.

```bash
R=hellojin97/databricks-dataplay-bundles
gh run list --repo "$R" --limit 5
gh run watch <RUN_ID> --repo "$R" --exit-status

# 단계별 결과
gh run view <RUN_ID> --repo "$R" \
  --json conclusion,jobs \
  --jq '.jobs[] | .name, (.steps[] | "  - \(.name): \(.conclusion)")'
```

기대 결과 (전부 success):

```text
- Run azure/login@v2: success            ← federated credential 정상 동작
- databricks bundle validate: success
- databricks bundle deploy: success      ← 워크스페이스에 실제 배포
- Notify Discord: success
```

---

## 3-5. PR 경로 검증 (선택)

위는 main push 경로만 탑니다. PR용 federated credential(`...:pull_request`)까지 확인하려면:

```bash
git switch -c test/validate
git commit --allow-empty -m "trigger validate"
git push -u origin test/validate
gh pr create --fill --repo hellojin97/databricks-dataplay-bundles
# → Bundle Validate 워크플로우가 PR에서 실행되는지 확인
```

---

## 완료 체크리스트

- [ ] `gh variable list` → `AZURE_CLIENT_ID/TENANT_ID/SUBSCRIPTION_ID` 3개
- [ ] `gh secret list` → `DATABRICKS_BUNDLES_DISCORD_WEBHOOK_URL`
- [ ] push 후 `Bundle Deploy` 전 단계 success
- [ ] (선택) PR 열어 `Bundle Validate` success
- [ ] (선택) `databricks bundle run example_job --target lab` 로 잡 실제 실행 확인

여기까지면 배포 파이프라인 완성. 이후엔 `src/` + `resources/`에 실제 워크로드를 추가하면 됩니다.

# Contract: Bronze 볼륨 파일 레이아웃

본 문서는 본 잡이 **출력 측 소비자(향후 silver/gold 잡, 분석 노트북, ad-hoc 쿼리)** 에게 보장하는
**볼륨 파일 레이아웃 계약**을 정의한다. 본 계약을 깨는 변경은 다운스트림 회귀를 유발하므로
호환 마이그레이션 없이 변경해서는 안 된다.

## 루트

`/Volumes/<catalog>/<schema>/<volume>/`

기본 운영값:

```
/Volumes/wikimedia-dataplay/bronze/recentchanges_raw/
```

카탈로그/스키마/볼륨 이름은 환경별 파라미터화 가능(target 변수). 다만 본 MVP 는 `lab` target 에서
위 값 그대로 사용.

## 디렉터리 구조 (Hive-style 파티션)

```
<root>/
  wiki=<wiki_id>/
    year=YYYY/month=MM/day=DD/hour=HH/minute=MM/
      <file>.jsonl.gz
```

- `wiki=`: `en.wikipedia` 등. 다른 wiki 가 추가될 때 동일 root 아래 다른 `wiki=...` 디렉터리.
- `year/month/day/hour/minute`: UTC 기준. `MM` 은 2자리 0-padding. `minute` 는 5의 배수만 (`00`,
  `05`, ..., `55`).

## 파일 명명

```
recentchanges-YYYY-MM-DDTHH-MM-SSZ.jsonl.gz
```

(파일명 내에는 `:` 가 들어가지 않도록 ISO 8601 의 `:` 를 `-` 로 치환)

예: `recentchanges-2026-05-22T03-25-00Z.jsonl.gz`

같은 5분 슬롯은 항상 같은 파일명. **재실행 = 동일 파일을 덮어쓴다.**

## 파일 포맷

- **압축**: gzip (`.gz`)
- **외부 포맷**: NDJSON — 1라인 = 1 이벤트 = 1 JSON 객체.
- **줄바꿈**: `\n` (LF)
- **JSON 직렬화**: `ensure_ascii=False`, `separators=(",", ":")`, key 순서는 API 응답 보존 가능
  범위에서 유지.
- **인코딩**: UTF-8 (gzip 압축 전 stream).
- **트레일링 newline**: 마지막 줄도 `\n` 으로 종료(POSIX).

## 정렬

이벤트 순서는 MediaWiki API 응답이 돌려준 그대로(현재 설정상 `rcdir=older` → 윈도우 끝부터 시작
쪽). 다운스트림 silver 는 `rcid` 로 결정성 있는 재정렬을 수행할 수 있으나, bronze 는 정렬을
보장하지 않는다.

## 원자성 (Success Marker 패턴 — 본 계약의 일부)

Databricks Volume FUSE 의 rename 원자성은 공식 보장이 없으므로, 본 계약은 **`.success` marker
패턴** 을 채택한다.

- 잡은 `recentchanges-<window>.jsonl.gz` 를 최종 경로에 직접 stream write 한다 (gzip writer
  finalize → fsync).
- 완료 후 같은 디렉터리(같은 `minute=MM/`)에 0-byte 파일 `_SUCCESS` 를 생성한다.
- **다운스트림 소비자는 `_SUCCESS` 의 존재 여부로 슬롯 완료를 판단해야 한다.** `_SUCCESS` 가
  없는 디렉터리의 파일은 partial 일 수 있으므로 읽지 않는다.
- 재실행(overwrite) 시 잡은 (a) 기존 `_SUCCESS` 가 있어도 무시하고 NDJSON 파일을 덮어쓴 후
  (b) `_SUCCESS` 를 재생성한다 (touch). 멱등성 정의 유지.

`_SUCCESS` 는 빈 파일(`b""`) 로 두며, 미래에 manifest 가 필요해지면 본 계약의 후속 버전에서
확장한다.

## 빈 슬롯

`query.recentchanges` 가 빈 배열인 경우(드물지만 발생 가능), 빈 NDJSON 파일(=gzip 빈 스트림) 을
같은 경로에 저장한다. 다운스트림은 파일 존재 ↔ 슬롯 처리 완료 로 판단할 수 있다.

## 스키마

각 라인의 JSON 은 [data-model.md §3](../data-model.md#3-외부-페이로드-형태-참고) 의 페이로드 형태를
따른다. 단, **본 계약은 페이로드 필드의 유무를 보장하지 않는다** — bronze 는 원본 그대로 보존
이므로 외부 API 가 필드를 추가/제거하면 그대로 반영된다. silver 단계에서 결정적 스키마로 정형화.

## 메타데이터 파일

별도 `_SUCCESS` 또는 매니페스트 파일은 두지 않는다(MVP). 다운스트림이 필요로 하게 되면 그 시점에
계약을 확장한다.

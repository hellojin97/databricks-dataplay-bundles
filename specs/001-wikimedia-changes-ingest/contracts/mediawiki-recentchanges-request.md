# Contract: MediaWiki Action API `list=recentchanges` 호출

본 문서는 본 잡이 외부 시스템(en.wikipedia.org) 에 대해 발사하는 **HTTP 요청 계약**과 그
응답의 사용 방식을 정의한다. 외부 시스템 변경 시 본 계약 위반이 감지되어야 한다.

## 엔드포인트

```
GET https://en.wikipedia.org/w/api.php
```

## 헤더

| Header | Value |
|--------|-------|
| `User-Agent` | `dataplay-bundles/<version> (https://github.com/hellojin97/databricks-dataplay-bundles; <contact>)` (Wikimedia 정책상 필수) |
| `Accept` | `application/json` |
| `Accept-Encoding` | `gzip` (자동) |

## 쿼리 파라미터

| 파라미터 | 값 | 비고 |
|----------|-----|------|
| `action` | `query` | 고정 |
| `format` | `json` | 고정 |
| `formatversion` | `2` | modern JSON |
| `list` | `recentchanges` | 고정 |
| `rcdir` | `older` | rcstart→rcend 으로 시간 진행 |
| `rcstart` | `<window_end ISO8601 UTC>` | newest 쪽 (rcdir=older 의 시작) |
| `rcend` | `<window_start ISO8601 UTC>` | oldest 쪽 (rcdir=older 의 종료) |
| `rclimit` | `500` | 최대값 |
| `rcprop` | `title\|timestamp\|ids\|sizes\|flags\|user\|userid\|comment\|parsedcomment\|tags\|loginfo` | 가능한 한 풍부 |
| `rctype` | `edit\|new\|log\|categorize` | 모든 타입 |
| `rccontinue` | `<token>` | 2번째 호출부터, 직전 응답의 `continue.rccontinue` |
| `continue` | `<token>` | 2번째 호출부터, 직전 응답의 `continue.continue` (보통 `"-||"`) |

`rcstart` / `rcend` 포맷: `YYYY-MM-DDTHH:MM:SSZ` (예: `2026-05-22T03:30:00Z`). 본 잡은 `start` 와
`end` 모두 정확히 분의 배수, 초 0.

### 윈도우 경계 처리 (좌폐우개 `[start, end)`)

MediaWiki API 의 `rcstart`/`rcend` 는 **양 끝 모두 포함**(inclusive) 이다. 본 잡의 윈도우 정의
`[start, end)` 와 어긋나므로, 응답에서 **`event.timestamp == window.end` 인 레코드를 코드에서
제거** 한다.

- API 호출: `rcstart = window.end.isoformat() + "Z"`, `rcend = window.start.isoformat() + "Z"`
- 코드 필터: `events_filtered = [e for e in events if parse_iso(e["timestamp"]) != window.end]`
- 그 결과 윈도우의 좌폐우개 약속(spec FR-002) 이 정확히 지켜지고, 인접 슬롯과의 경계 이벤트
  중복 적재가 발생하지 않는다.

이 규약을 따르지 않으면 두 인접 윈도우가 같은 `rcid` 를 1건 이상 공유할 수 있다 (boundary
double-count).

## 응답 (`200 OK`)

JSON 본문 골자:

```json
{
  "batchcomplete": true,
  "continue": { "rccontinue": "...", "continue": "-||" },
  "query": {
    "recentchanges": [
      { /* event object */ }, ...
    ]
  }
}
```

- `query.recentchanges` 가 본 잡의 핵심 데이터. 각 원소를 가공 없이 NDJSON 라인으로 직렬화한다.
- `continue` 가 존재하면 다음 페이지가 있음. 그 객체 안의 `rccontinue`/`continue` 를 다음 호출에
  그대로 전달한다.
- `continue` 가 없으면 페이지네이션 종료.

## 오류 처리

| 상황 | 본 잡의 동작 |
|------|----------------|
| HTTP `4xx` (e.g. UA 누락) | 즉시 잡 실패. 재시도 안 함. |
| HTTP `5xx` 또는 네트워크 오류 | 동일 호출 최대 3회 지수 backoff (1s, 3s, 9s). 실패 시 잡 실패. |
| HTTP `429` (rate limit) | `Retry-After` 헤더 존중 후 1회 재시도. 그래도 실패 시 잡 실패. |
| 응답이 JSON 파싱 실패 | 잡 실패. 응답 본문 일부를 로그로 남김. |
| `query.recentchanges` 키 부재 | 잡 실패 (shape 위반). |
| 페이지네이션 호출 수 > `max_pages_per_window` (기본 10) | 잡 실패 (상한 exceed). |

## 비기능

- 단일 호출 timeout: 15초.
- 동시 호출 수: 1 (`max_concurrent_runs: 1`). 페이지네이션은 순차.
- IP 기반 rate limit: 5분당 ~10회 이하 호출 — 안전 구간.

## 변경 감지

본 계약 위반(응답 shape 변화) 은 통합 테스트가 잡고, 또한 잡 런타임의 shape 검증
(`RecentChangesResponse`) 이 실패하면 빠르게 fail-fast 한다.

# Data Model: Wikimedia 변경사항 Bronze 적재 파이프라인

본 문서는 본 기능의 데이터 표현(Pydantic 모델, dataclass, 외부 페이로드 형태)을 정의한다. 헌법
원칙 III("외부 입력은 Pydantic, 내부 데이터는 dataclass") 를 그대로 따른다.

## 1. 외부 입력 경계 — Pydantic

### 1.1 `IngestionConfig` (Pydantic v2)

태스크 호출부가 받는 잡 파라미터/환경을 검증·정규화한다.

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|------|------|------|--------|------|
| `wiki_api_url` | `HttpUrl` | Y | — | `https://en.wikipedia.org/w/api.php` |
| `wiki_id` | `str` | Y | `en.wikipedia` | 경로/로그에 쓰는 wiki 식별자 |
| `volume_root` | `str` | Y | `/Volumes/wikimedia-dataplay/bronze/recentchanges_raw` | 출력 볼륨 루트 |
| `user_agent` | `str` | Y | — | Wikimedia 정책상 식별 가능한 UA |
| `request_timeout_seconds` | `float` | N | `15.0` | 단일 HTTP 호출 타임아웃 |
| `max_pages_per_window` | `int` | N | `10` | 1 슬롯당 페이지네이션 호출 상한 |
| `override_window_start` | `datetime \| None` | N | `None` | 수동 백필용. None 이면 자동 직전 슬롯. UTC tz-aware. |

검증 규칙:
- `wiki_api_url` 은 `https` 만 허용 (`@validator`).
- `volume_root` 는 `/Volumes/<catalog>/<schema>/<volume>` 패턴이거나 로컬 테스트용 절대 경로.
- `override_window_start` 가 주어지면 UTC tz-aware 이고 분(minute) 이 5의 배수여야 한다 (벽시계
  정렬).

### 1.2 `RecentChangesResponse` (Pydantic, 부분 검증만)

MediaWiki API 응답의 **shape 검증** 만 수행. 페이로드(이벤트 객체) 자체는 검증 없이 dict 로 보존
— bronze 의 원본 보존 원칙(FR-003).

```python
class RecentChangesResponse(BaseModel):
    batchcomplete: bool | None = None
    continue_: dict[str, str] | None = Field(default=None, alias="continue")
    query: dict                                   # {"recentchanges": [...]}
    model_config = ConfigDict(extra="allow")      # 알 수 없는 필드 허용
```

검증 규칙: `query.recentchanges` 가 list 인지만 확인. 각 원소는 raw dict 그대로 전달.

## 2. 내부 데이터 — frozen dataclass

### 2.1 `IngestWindow`

```python
@dataclass(frozen=True, slots=True)
class IngestWindow:
    start: datetime          # UTC tz-aware, 분이 5의 배수
    end: datetime            # = start + 5min (좌폐우개 [start, end))

    @property
    def key(self) -> str:    # "2026-05-22T03:25:00Z"
        ...

    @property
    def path_segments(self) -> tuple[str, str, str, str, str]:
        # ("year=2026", "month=05", "day=22", "hour=03", "minute=25")
        ...
```

불변성·해시 가능 → 테스트와 로깅에서 안전.

### 2.2 `IngestResult`

잡 호출부가 받아 로그/메트릭으로 사용.

```python
@dataclass(frozen=True, slots=True)
class IngestResult:
    window: IngestWindow
    record_count: int
    file_path: str           # 최종 적재된 파일 절대 경로
    bytes_written: int       # gzip 후 바이트 수
    api_calls: int           # 페이지네이션 포함 총 HTTP 호출 수
```

### 2.3 `PageBatch`

`MediaWikiRecentChangesClient` 내부에서 페이지네이션 1회 결과를 표현.

```python
@dataclass(frozen=True, slots=True)
class PageBatch:
    events: tuple[dict, ...]                 # 원본 raw dict 들 (immutable)
    continue_token: str | None
```

## 3. 외부 페이로드 형태 (참고)

MediaWiki API `query.recentchanges[*]` 의 1개 원소 예시 (`formatversion=2`):

```json
{
  "type": "edit",
  "ns": 0,
  "title": "Example article",
  "pageid": 12345,
  "revid": 67890,
  "old_revid": 67889,
  "rcid": 9876543,
  "user": "Example user",
  "userid": 543,
  "timestamp": "2026-05-22T03:24:31Z",
  "comment": "Fixed typo",
  "parsedcomment": "Fixed typo",
  "oldlen": 1234,
  "newlen": 1240,
  "minor": false,
  "bot": false,
  "tags": ["mobile edit"]
}
```

**불변량**:
- `rcid` 는 wiki 내에서 monotonic 정수 — 멱등 키로 사용 가능.
- `timestamp` 는 항상 ISO 8601 UTC + `Z`.
- 본 모델에서 위 필드의 부재/추가에 대한 강제 검증은 하지 않는다(원본 보존).

## 4. 출력 파일 레이아웃

볼륨 내 경로 (UTC 기준):

```
/Volumes/wikimedia-dataplay/bronze/recentchanges_raw/
  wiki=en.wikipedia/
    year=2026/month=05/day=22/hour=03/minute=25/
      recentchanges-2026-05-22T03-25-00Z.jsonl.gz
      _SUCCESS                                      # 슬롯 완료 marker (계약 일부)
```

파일 본문:
- gzip 압축 NDJSON. 각 라인 = `json.dumps(event, ensure_ascii=False, separators=(",", ":"))`.
- 이벤트 순서는 MediaWiki API 가 돌려준 원본 순서를 그대로 유지 (`rcdir=older` 이므로 윈도우 끝 →
  시작 순).

## 5. 상태 전이 (Lifecycle)

본 도메인의 엔터티는 단방향 흐름이며 lifecycle 상태가 없다.

```
MediaWiki API → (raw dict) → write NDJSON.gz → (volume file) → 후속 silver
```

`IngestResult` 는 1회성이고, 외부 KV 상태도 없으므로 별도 state machine 불필요.

## 6. 변환 함수 시그니처 (헌법 III)

순수 함수, 부수효과 없음:

```python
def compute_previous_slot(now: datetime) -> IngestWindow: ...
def window_to_volume_dir(window: IngestWindow, root: str, wiki_id: str) -> str: ...
def window_to_file_name(window: IngestWindow) -> str: ...    # "recentchanges-<ts>.jsonl.gz"
def serialize_event_line(event: Mapping[str, object]) -> bytes: ...

# 경계 처리 (rcstart/rcend 양끝 inclusive vs 윈도우 [start, end) 의 갭 보정)
def filter_events_within_window(
    events: Iterable[dict], window: IngestWindow
) -> Iterator[dict]: ...    # event.timestamp == window.end 인 레코드 제거
```

I/O 는 클래스:

```python
class MediaWikiRecentChangesClient:
    def __init__(self, session: requests.Session, api_url: str, user_agent: str,
                 timeout: float = 15.0) -> None: ...
    def fetch_window(self, window: IngestWindow, *, max_pages: int = 10) -> Iterable[dict]: ...
    # 주의: 반환된 이벤트는 rcstart/rcend 가 inclusive 이므로, 호출부에서
    # filter_events_within_window 로 좌폐우개 [start, end) 로 좁혀야 한다.

class BronzeVolumeWriter:
    def __init__(self, root: str, wiki_id: str) -> None: ...
    def write_window(self, window: IngestWindow, events: Iterable[dict]) -> IngestResult: ...
    # 동작: NDJSON+gzip 파일을 최종 경로에 stream write 후 같은 디렉터리에 0-byte
    # `_SUCCESS` 파일 생성. 멱등 — 동일 윈도우 재호출 시 둘 다 덮어쓰기.
```

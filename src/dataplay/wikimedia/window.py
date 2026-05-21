"""5분 적재 윈도우와 관련된 순수 변환 함수·데이터 타입.

벽시계 정렬 슬롯(`[HH:MM, HH:MM+5)`) 계산, 볼륨 경로/파일명 생성, NDJSON 직렬화, 경계 이벤트
필터링을 담는다. 모든 함수는 부수효과가 없고 SparkSession 을 요구하지 않는다 (헌법 원칙 III).

UTC 가정: 모든 datetime 입력은 tz-aware UTC 여야 한다 (research.md R11).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# 1 슬롯 길이 — 변경 시 본 패키지 전반의 가정이 무효화됨.
_SLOT_MINUTES = 5

# ISO 8601 UTC 'Z' 형식 (MediaWiki API timestamp 와 동일).
_ISO_Z_FMT = "%Y-%m-%dT%H:%M:%SZ"

# 파일명에 사용할 ISO 변형 — POSIX 파일명에 `:` 가 들어가지 않도록 하이픈 치환.
_FILENAME_ISO_FMT = "%Y-%m-%dT%H-%M-%SZ"


def _ensure_utc(dt: datetime, label: str) -> None:
    """tz-aware UTC 인지 검증. 위반 시 ValueError."""
    if dt.tzinfo is None:
        raise ValueError(f"{label}: naive datetime 은 허용되지 않습니다. tz-aware UTC 사용.")
    if dt.utcoffset() != timedelta(0):
        raise ValueError(f"{label}: UTC 가 아닙니다. utcoffset={dt.utcoffset()}.")


@dataclass(frozen=True, slots=True)
class IngestWindow:
    """5분 적재 윈도우. 좌폐우개 `[start, end)`, end - start == 5분, 벽시계 정렬.

    canonical 생성자는 `compute_previous_slot` 또는 `from_start_iso`. 직접 생성도 허용하지만
    `__post_init__` 가 정합성 검증을 강제한다.
    """

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        _ensure_utc(self.start, "IngestWindow.start")
        _ensure_utc(self.end, "IngestWindow.end")
        if self.end - self.start != timedelta(minutes=_SLOT_MINUTES):
            raise ValueError(
                f"IngestWindow 길이는 {_SLOT_MINUTES}분이어야 합니다. "
                f"start={self.start}, end={self.end}"
            )
        if (
            self.start.minute % _SLOT_MINUTES != 0
            or self.start.second != 0
            or self.start.microsecond != 0
        ):
            raise ValueError(
                f"IngestWindow.start 는 벽시계 5분 경계(분/초/μs = 0)에 정렬되어야 합니다: "
                f"{self.start}"
            )

    @property
    def key(self) -> str:
        """윈도우 식별 키 — 시작 시각의 ISO 8601 UTC 문자열 (예: '2026-05-22T03:25:00Z')."""
        return self.start.strftime(_ISO_Z_FMT)

    @property
    def path_segments(self) -> tuple[str, str, str, str, str]:
        """Hive-style 파티션 경로 세그먼트 (year/month/day/hour/minute)."""
        s = self.start
        return (
            f"year={s.year:04d}",
            f"month={s.month:02d}",
            f"day={s.day:02d}",
            f"hour={s.hour:02d}",
            f"minute={s.minute:02d}",
        )

    @classmethod
    def from_start(cls, start: datetime) -> IngestWindow:
        """시작 시각으로부터 5분 윈도우 생성."""
        return cls(start=start, end=start + timedelta(minutes=_SLOT_MINUTES))


def compute_previous_slot(now: datetime) -> IngestWindow:
    """주어진 시각의 **직전 벽시계 5분 슬롯**을 반환.

    예) now=2026-05-22T03:27:13Z → IngestWindow([03:20Z, 03:25Z))
        now=2026-05-22T03:30:00Z → IngestWindow([03:25Z, 03:30Z))
        now=2026-05-22T03:24:59.999999Z → IngestWindow([03:15Z, 03:20Z))

    초/마이크로초는 무시되며, 결과 윈도우의 start 분은 항상 5의 배수.
    """
    _ensure_utc(now, "compute_previous_slot.now")
    minute_floor = (now.minute // _SLOT_MINUTES) * _SLOT_MINUTES
    current_slot_start = now.replace(minute=minute_floor, second=0, microsecond=0, tzinfo=UTC)
    previous_start = current_slot_start - timedelta(minutes=_SLOT_MINUTES)
    return IngestWindow.from_start(previous_start)


def window_to_volume_dir(window: IngestWindow, root: str, wiki_id: str) -> str:
    """볼륨 내 윈도우 디렉터리의 절대 경로.

    예) root='/Volumes/wikimedia-dataplay/bronze/recentchanges_raw'
        wiki_id='en.wikipedia'
        window.start=2026-05-22T03:20:00Z
        → '/Volumes/wikimedia-dataplay/bronze/recentchanges_raw/wiki=en.wikipedia/
           year=2026/month=05/day=22/hour=03/minute=20'
    """
    root_clean = root.rstrip("/")
    segments = "/".join(window.path_segments)
    return f"{root_clean}/wiki={wiki_id}/{segments}"


def window_to_file_name(window: IngestWindow) -> str:
    """윈도우 파일명 — `recentchanges-<ISO-with-hyphens>.jsonl.gz`."""
    return f"recentchanges-{window.start.strftime(_FILENAME_ISO_FMT)}.jsonl.gz"


def serialize_event_line(event: Mapping[str, object]) -> bytes:
    """1 이벤트 → NDJSON 1라인(UTF-8 + trailing '\\n').

    `ensure_ascii=False` 로 한국어/일본어 등 비ASCII 문자를 압축 효율 좋게 보존.
    `separators=(',',':')` 로 공백을 제거해 파일 크기 최소화.
    """
    return json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"


def filter_events_within_window(
    events: Iterable[Mapping[str, object]], window: IngestWindow
) -> Iterator[dict]:
    """MediaWiki API 응답의 양끝-inclusive timestamp 를 좌폐우개 `[start, end)` 로 좁힌다.

    구체적으로 `event['timestamp'] == window.end (ISO 'Z')` 인 이벤트만 제거한다 — 본 이벤트는
    다음 윈도우에 속하므로 본 윈도우 적재에서는 배제 (contracts/mediawiki-recentchanges-request.md
    의 "윈도우 경계 처리" 절 참조).
    """
    end_iso = window.end.strftime(_ISO_Z_FMT)
    for event in events:
        if event.get("timestamp") == end_iso:
            continue
        yield dict(event)

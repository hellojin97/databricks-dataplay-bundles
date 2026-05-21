"""window 모듈의 순수 변환 함수 단위 테스트 (헌법 V — 변환 함수 단위 테스트 필수)."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from dataplay.wikimedia.window import (
    IngestWindow,
    compute_previous_slot,
    filter_events_within_window,
    serialize_event_line,
    window_to_file_name,
    window_to_volume_dir,
)

# --- IngestWindow 검증 -------------------------------------------------------


def test_ingest_window_rejects_naive_datetime():
    with pytest.raises(ValueError, match="naive"):
        IngestWindow(start=datetime(2026, 5, 22, 3, 0), end=datetime(2026, 5, 22, 3, 5))


def test_ingest_window_rejects_non_utc():
    kst = timezone(timedelta(hours=9))
    with pytest.raises(ValueError, match="UTC"):
        IngestWindow(
            start=datetime(2026, 5, 22, 3, 0, tzinfo=kst),
            end=datetime(2026, 5, 22, 3, 5, tzinfo=kst),
        )


def test_ingest_window_rejects_misaligned_start():
    # 분이 5의 배수가 아닌 경우
    with pytest.raises(ValueError, match="5분 경계"):
        IngestWindow.from_start(datetime(2026, 5, 22, 3, 3, tzinfo=UTC))
    # 초가 0이 아닌 경우
    with pytest.raises(ValueError, match="5분 경계"):
        IngestWindow.from_start(datetime(2026, 5, 22, 3, 5, 1, tzinfo=UTC))


def test_ingest_window_rejects_wrong_length():
    start = datetime(2026, 5, 22, 3, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="5분"):
        IngestWindow(start=start, end=start + timedelta(minutes=10))


def test_ingest_window_key_is_iso_z():
    window = IngestWindow.from_start(datetime(2026, 5, 22, 3, 25, tzinfo=UTC))
    assert window.key == "2026-05-22T03:25:00Z"


def test_ingest_window_path_segments():
    window = IngestWindow.from_start(datetime(2026, 5, 22, 3, 5, tzinfo=UTC))
    assert window.path_segments == (
        "year=2026",
        "month=05",
        "day=22",
        "hour=03",
        "minute=05",
    )


# --- compute_previous_slot --------------------------------------------------


@pytest.mark.parametrize(
    "now,expected_start",
    [
        # 분이 5의 배수가 아닌 경우 — 현재 슬롯의 시작을 직전 슬롯의 종료로 본다.
        (
            datetime(2026, 5, 22, 3, 27, 13, 456789, tzinfo=UTC),
            datetime(2026, 5, 22, 3, 20, tzinfo=UTC),
        ),
        # +9분 — 현재 슬롯 [05,10) 가 진행 중. 직전은 [00,05).
        (
            datetime(2026, 5, 22, 3, 9, 59, 999999, tzinfo=UTC),
            datetime(2026, 5, 22, 3, 0, tzinfo=UTC),
        ),
        # 정각 5분 — 현재 슬롯 [05,10) 시작. 직전은 [00,05).
        (
            datetime(2026, 5, 22, 3, 5, tzinfo=UTC),
            datetime(2026, 5, 22, 3, 0, tzinfo=UTC),
        ),
        # 정각 30분 — 현재 [30,35). 직전 [25,30).
        (
            datetime(2026, 5, 22, 3, 30, tzinfo=UTC),
            datetime(2026, 5, 22, 3, 25, tzinfo=UTC),
        ),
        # 시 경계 넘김 — now=04:00:00 → 직전 [03:55, 04:00).
        (
            datetime(2026, 5, 22, 4, 0, tzinfo=UTC),
            datetime(2026, 5, 22, 3, 55, tzinfo=UTC),
        ),
        # 일 경계 넘김 — now=00:00:00 → 직전 [23:55, 00:00) 전날.
        (
            datetime(2026, 5, 22, 0, 0, tzinfo=UTC),
            datetime(2026, 5, 21, 23, 55, tzinfo=UTC),
        ),
    ],
)
def test_compute_previous_slot_boundaries(now: datetime, expected_start: datetime):
    result = compute_previous_slot(now)
    assert result.start == expected_start
    assert result.end == expected_start + timedelta(minutes=5)


def test_compute_previous_slot_rejects_naive(frozen_now: datetime):
    with pytest.raises(ValueError):
        compute_previous_slot(frozen_now.replace(tzinfo=None))


def test_compute_previous_slot_with_frozen_now(frozen_now: datetime):
    # frozen_now = 2026-05-22T03:27:13.456789Z → 직전 슬롯 [03:25, 03:30)... 잠깐, 27//5=5, 5*5=25.
    # 따라서 현재 슬롯 시작은 03:25 이고 직전 슬롯은 [03:20, 03:25).
    result = compute_previous_slot(frozen_now)
    assert result.start == datetime(2026, 5, 22, 3, 20, tzinfo=UTC)
    assert result.end == datetime(2026, 5, 22, 3, 25, tzinfo=UTC)


# --- 경로/파일명 ------------------------------------------------------------


def test_window_to_volume_dir():
    window = IngestWindow.from_start(datetime(2026, 5, 22, 3, 20, tzinfo=UTC))
    path = window_to_volume_dir(
        window=window,
        root="/Volumes/wikimedia-dataplay/bronze/recentchanges_raw",
        wiki_id="en.wikipedia",
    )
    assert path == (
        "/Volumes/wikimedia-dataplay/bronze/recentchanges_raw"
        "/wiki=en.wikipedia/year=2026/month=05/day=22/hour=03/minute=20"
    )


def test_window_to_volume_dir_strips_trailing_slash():
    window = IngestWindow.from_start(datetime(2026, 5, 22, 3, 20, tzinfo=UTC))
    path = window_to_volume_dir(window=window, root="/tmp/foo/", wiki_id="en.wikipedia")
    assert path.startswith("/tmp/foo/wiki=")


def test_window_to_file_name():
    window = IngestWindow.from_start(datetime(2026, 5, 22, 3, 25, tzinfo=UTC))
    assert window_to_file_name(window) == "recentchanges-2026-05-22T03-25-00Z.jsonl.gz"
    # 파일명에 `:` 가 없어야 함 (POSIX 안전성).
    assert ":" not in window_to_file_name(window)


# --- serialize_event_line ---------------------------------------------------


def test_serialize_event_line_basic():
    event = {"rcid": 12345, "title": "Example", "type": "edit"}
    line = serialize_event_line(event)
    assert line.endswith(b"\n")
    parsed = json.loads(line.decode("utf-8").rstrip("\n"))
    assert parsed == event


def test_serialize_event_line_preserves_non_ascii():
    event = {"title": "한국어 제목", "user": "テスト"}
    line = serialize_event_line(event)
    decoded = line.decode("utf-8").rstrip("\n")
    # ensure_ascii=False 가 한국어/일본어를 그대로 보존
    assert "한국어 제목" in decoded
    assert "テスト" in decoded
    # `\uXXXX` 이스케이프 형태로 변환되지 않았는지
    assert "\\u" not in decoded


def test_serialize_event_line_compact_separators():
    event = {"a": 1, "b": [2, 3]}
    line = serialize_event_line(event)
    # `, ` / `: ` 공백 없이 직렬화되어 파일 크기 최소화
    assert b", " not in line
    assert b": " not in line
    assert line == b'{"a":1,"b":[2,3]}\n'


def test_serialize_event_line_gzip_roundtrip(tmp_path):
    # 통합적으로 작성→gzip 압축→해제→파싱 사이클이 정상 동작하는지
    events = [{"rcid": i, "title": f"page {i}"} for i in range(3)]
    path = tmp_path / "out.jsonl.gz"
    with path.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
        for ev in events:
            gz.write(serialize_event_line(ev))
    with gzip.open(path, "rb") as fh:
        lines = fh.read().decode("utf-8").splitlines()
    assert [json.loads(line) for line in lines] == events


# --- filter_events_within_window --------------------------------------------


def test_filter_drops_event_at_window_end():
    window = IngestWindow.from_start(datetime(2026, 5, 22, 3, 20, tzinfo=UTC))
    # window.end == 03:25Z — 본 이벤트는 제거되어야 한다 (다음 슬롯 소속).
    events = [
        {"rcid": 1, "timestamp": "2026-05-22T03:20:00Z"},  # 경계의 시작 — 포함
        {"rcid": 2, "timestamp": "2026-05-22T03:22:30Z"},  # 중간 — 포함
        {"rcid": 3, "timestamp": "2026-05-22T03:24:59Z"},  # 종료 직전 — 포함
        {"rcid": 4, "timestamp": "2026-05-22T03:25:00Z"},  # window.end — 제거
    ]
    kept = list(filter_events_within_window(events, window))
    assert [e["rcid"] for e in kept] == [1, 2, 3]


def test_filter_passes_through_when_no_boundary_match():
    window = IngestWindow.from_start(datetime(2026, 5, 22, 3, 20, tzinfo=UTC))
    events = [
        {"rcid": 1, "timestamp": "2026-05-22T03:21:00Z"},
        {"rcid": 2, "timestamp": "2026-05-22T03:24:00Z"},
    ]
    kept = list(filter_events_within_window(events, window))
    assert len(kept) == 2


def test_filter_returns_independent_dicts():
    # 입력 dict 와 출력 dict 가 같은 객체가 아니어야 한다 (원본 mutation 방지).
    window = IngestWindow.from_start(datetime(2026, 5, 22, 3, 20, tzinfo=UTC))
    src = [{"rcid": 1, "timestamp": "2026-05-22T03:21:00Z"}]
    out = list(filter_events_within_window(src, window))
    assert out[0] == src[0]
    assert out[0] is not src[0]

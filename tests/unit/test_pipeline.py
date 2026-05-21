"""pipeline.orchestrate 합성 로직 단위 테스트 — source/writer 더블 주입."""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from dataplay.wikimedia.config import IngestionConfig
from dataplay.wikimedia.pipeline import orchestrate
from dataplay.wikimedia.source import PageBatch
from dataplay.wikimedia.window import IngestWindow
from dataplay.wikimedia.writer import LocalDirectoryWriter, WriteResult

# --- 더블 -------------------------------------------------------------------


class FakeSource:
    """미리 정의된 PageBatch 시퀀스를 yield. fetch_batches 가 호출된 윈도우를 기록."""

    def __init__(self, batches: list[PageBatch]) -> None:
        self._batches = batches
        self.calls: list[IngestWindow] = []

    def fetch_batches(self, window: IngestWindow, *, max_pages: int = 10) -> Iterator[PageBatch]:
        self.calls.append(window)
        yield from self._batches


class FakeWriter:
    """write_window 호출 인자를 기록하고, 고정된 WriteResult 를 돌려준다."""

    def __init__(self) -> None:
        self.received_window: IngestWindow | None = None
        self.received_events: list[dict[str, Any]] | None = None

    def write_window(self, window: IngestWindow, events: Iterator[dict]) -> WriteResult:
        self.received_window = window
        self.received_events = list(events)
        return WriteResult(
            file_path="/tmp/fake.jsonl.gz",
            success_marker_path="/tmp/_SUCCESS",
            record_count=len(self.received_events),
            bytes_written=42,
        )


# --- fixture --------------------------------------------------------------


@pytest.fixture
def base_config(tmp_volume_root: str) -> IngestionConfig:
    return IngestionConfig(
        wiki_api_url="https://en.wikipedia.org/w/api.php",
        wiki_id="en.wikipedia",
        volume_root=tmp_volume_root,
        user_agent="dataplay-bundles/test (ci@example)",
    )


# --- 테스트 -----------------------------------------------------------------


def test_orchestrate_uses_previous_slot_when_override_absent(
    frozen_now: datetime, base_config: IngestionConfig
):
    # frozen_now=2026-05-22T03:27:13.456789Z → 직전 슬롯 [03:20, 03:25).
    source = FakeSource(batches=[PageBatch(events=(), continue_token=None)])
    writer = FakeWriter()

    result = orchestrate(base_config, frozen_now, source, writer)

    assert result.window.start == datetime(2026, 5, 22, 3, 20, tzinfo=UTC)
    assert result.window.end == datetime(2026, 5, 22, 3, 25, tzinfo=UTC)


def test_orchestrate_uses_override_window_start(frozen_now: datetime, tmp_volume_root: str):
    override = datetime(2026, 5, 22, 1, 0, tzinfo=UTC)
    config = IngestionConfig(
        wiki_api_url="https://en.wikipedia.org/w/api.php",
        wiki_id="en.wikipedia",
        volume_root=tmp_volume_root,
        user_agent="dataplay-bundles/test",
        override_window_start=override,
    )
    source = FakeSource(batches=[PageBatch(events=(), continue_token=None)])
    writer = FakeWriter()

    result = orchestrate(config, frozen_now, source, writer)

    assert result.window.start == override
    assert result.window.end == datetime(2026, 5, 22, 1, 5, tzinfo=UTC)


def test_orchestrate_counts_api_calls(frozen_now: datetime, base_config: IngestionConfig):
    batches = [
        PageBatch(
            events=({"rcid": 1, "timestamp": "2026-05-22T03:21:00Z"},),
            continue_token={"rccontinue": "x"},
        ),
        PageBatch(
            events=({"rcid": 2, "timestamp": "2026-05-22T03:22:00Z"},),
            continue_token={"rccontinue": "y"},
        ),
        PageBatch(events=({"rcid": 3, "timestamp": "2026-05-22T03:23:00Z"},), continue_token=None),
    ]
    source = FakeSource(batches=batches)
    writer = FakeWriter()

    result = orchestrate(base_config, frozen_now, source, writer)

    assert result.api_calls == 3
    assert result.record_count == 3


def test_orchestrate_applies_boundary_filter(frozen_now: datetime, base_config: IngestionConfig):
    # 윈도우 = [03:20, 03:25). 03:25:00Z 이벤트는 제거되어야 한다.
    batches = [
        PageBatch(
            events=(
                {"rcid": 1, "timestamp": "2026-05-22T03:24:59Z"},
                {"rcid": 2, "timestamp": "2026-05-22T03:25:00Z"},  # 제거 대상
                {"rcid": 3, "timestamp": "2026-05-22T03:20:00Z"},
            ),
            continue_token=None,
        ),
    ]
    source = FakeSource(batches=batches)
    writer = FakeWriter()

    result = orchestrate(base_config, frozen_now, source, writer)

    assert result.record_count == 2
    assert writer.received_events is not None
    received_ids = sorted(e["rcid"] for e in writer.received_events)
    assert received_ids == [1, 3]


def test_orchestrate_returns_writer_paths(frozen_now: datetime, base_config: IngestionConfig):
    source = FakeSource(batches=[PageBatch(events=(), continue_token=None)])
    writer = FakeWriter()

    result = orchestrate(base_config, frozen_now, source, writer)

    assert result.file_path == "/tmp/fake.jsonl.gz"
    assert result.success_marker_path == "/tmp/_SUCCESS"
    assert result.bytes_written == 42


def test_orchestrate_end_to_end_with_real_writer(
    frozen_now: datetime, base_config: IngestionConfig
):
    # source 만 더블, writer 는 진짜 LocalDirectoryWriter — 결과 파일/marker 생성 검증.
    events = (
        {"rcid": 1, "timestamp": "2026-05-22T03:21:00Z", "title": "한 페이지"},
        {"rcid": 2, "timestamp": "2026-05-22T03:22:00Z", "title": "Another"},
    )
    source = FakeSource(batches=[PageBatch(events=events, continue_token=None)])
    writer = LocalDirectoryWriter(root=base_config.volume_root, wiki_id="en.wikipedia")

    result = orchestrate(base_config, frozen_now, source, writer)

    assert result.record_count == 2
    # 파일이 실제로 존재하고 라인 수가 맞는지
    from pathlib import Path

    file_path = Path(result.file_path)
    success_path = Path(result.success_marker_path)
    assert file_path.exists()
    assert success_path.exists()
    assert success_path.read_bytes() == b""
    with gzip.open(file_path, "rb") as fh:
        lines = fh.read().decode("utf-8").splitlines()
    parsed = [json.loads(line) for line in lines]
    assert len(parsed) == 2
    assert parsed[0]["title"] == "한 페이지"


def test_orchestrate_passes_max_pages_to_source(frozen_now: datetime, tmp_volume_root: str):
    config = IngestionConfig(
        wiki_api_url="https://en.wikipedia.org/w/api.php",
        wiki_id="en.wikipedia",
        volume_root=tmp_volume_root,
        user_agent="dataplay-bundles/test",
        max_pages_per_window=3,
    )

    captured: dict[str, int] = {}

    class CapturingSource:
        def fetch_batches(
            self, window: IngestWindow, *, max_pages: int = 10
        ) -> Iterator[PageBatch]:
            captured["max_pages"] = max_pages
            yield PageBatch(events=(), continue_token=None)

    orchestrate(config, frozen_now, CapturingSource(), FakeWriter())
    assert captured["max_pages"] == 3

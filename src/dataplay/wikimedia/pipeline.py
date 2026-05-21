"""소스·라이터·윈도우 계산을 합성하는 파이프라인 함수와 결과 dataclass.

본 모듈은 헌법 원칙 III 의 "변환은 함수로 합성" 케이스다 (DataFrame 대신 일반 함수 합성 —
plan.md Complexity #1). SparkSession 을 요구하지 않으므로 원칙 IV 는 N/A.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .config import IngestionConfig
from .source import PageBatch
from .window import (
    IngestWindow,
    compute_previous_slot,
    filter_events_within_window,
)
from .writer import WriteResult


@dataclass(frozen=True, slots=True)
class IngestResult:
    """잡 1회 실행의 최종 결과 — 호출부가 로그/메트릭으로 사용."""

    window: IngestWindow
    record_count: int
    file_path: str
    success_marker_path: str
    bytes_written: int
    api_calls: int


class _SourceLike(Protocol):
    """`MediaWikiRecentChangesClient` 와 호환되는 minimal 인터페이스 (테스트 더블 친화)."""

    def fetch_batches(
        self, window: IngestWindow, *, max_pages: int = ...
    ) -> Iterator[PageBatch]: ...


class _WriterLike(Protocol):
    """`LocalDirectoryWriter` / `BronzeVolumeWriter` 와 호환되는 인터페이스."""

    def write_window(self, window: IngestWindow, events: Iterator[dict]) -> WriteResult: ...


def _resolve_window(config: IngestionConfig, now: datetime) -> IngestWindow:
    """`override_window_start` 가 있으면 그 슬롯을, 없으면 `now` 의 직전 슬롯을 선택."""
    if config.override_window_start is not None:
        return IngestWindow.from_start(config.override_window_start)
    return compute_previous_slot(now)


def orchestrate(
    config: IngestionConfig,
    now: datetime,
    source: _SourceLike,
    writer: _WriterLike,
) -> IngestResult:
    """본 잡의 핵심 합성 — fetch → 경계 필터 → write → 메트릭 합산.

    SparkSession 을 받지 않으며, 모든 외부 자원 접근은 `source` / `writer` 를 통해서만 이뤄
    진다. 테스트는 두 더블을 주입해 결정적으로 검증할 수 있다.
    """
    window = _resolve_window(config, now)
    api_calls = 0
    raw_events: list[dict] = []
    for batch in source.fetch_batches(window, max_pages=config.max_pages_per_window):
        api_calls += 1
        raw_events.extend(batch.events)
    filtered = filter_events_within_window(raw_events, window)
    write_result = writer.write_window(window, filtered)
    return IngestResult(
        window=window,
        record_count=write_result.record_count,
        file_path=write_result.file_path,
        success_marker_path=write_result.success_marker_path,
        bytes_written=write_result.bytes_written,
        api_calls=api_calls,
    )

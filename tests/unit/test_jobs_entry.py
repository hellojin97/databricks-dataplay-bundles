"""dataplay.jobs.wikimedia_recentchanges 호출부 단위 테스트 — 구조화 로그 검증 (FR-011, US3)."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from datetime import UTC, datetime
from typing import Any

import pytest

from dataplay.jobs import wikimedia_recentchanges as entry
from dataplay.wikimedia.pipeline import IngestResult
from dataplay.wikimedia.window import IngestWindow


def _make_result() -> IngestResult:
    window = IngestWindow.from_start(datetime(2026, 5, 22, 3, 20, tzinfo=UTC))
    return IngestResult(
        window=window,
        record_count=123,
        file_path="/Volumes/x/y/z/recentchanges-2026-05-22T03-20-00Z.jsonl.gz",
        success_marker_path="/Volumes/x/y/z/_SUCCESS",
        bytes_written=4567,
        api_calls=3,
    )


def test_log_payload_contains_required_fields():
    payload = entry._ingest_result_to_log_payload(_make_result())

    # FR-011: 윈도우 시각 + 적재 레코드 수가 반드시 포함되어야 한다.
    assert payload["window"]["start_iso"] == "2026-05-22T03:20:00Z"
    assert payload["window"]["end_iso"] == "2026-05-22T03:25:00Z"
    assert payload["window"]["key"] == "2026-05-22T03:20:00Z"
    assert payload["record_count"] == 123
    assert payload["file_path"].endswith(".jsonl.gz")
    assert payload["success_marker_path"].endswith("/_SUCCESS")
    assert payload["bytes_written"] == 4567
    assert payload["api_calls"] == 3
    assert payload["event"] == "ingest_complete"


def test_log_payload_serializes_to_single_json_line():
    payload = entry._ingest_result_to_log_payload(_make_result())
    line = json.dumps(payload, ensure_ascii=False)
    parsed = json.loads(line)
    # round-trip 가 깨지지 않아야 한다 (다운스트림 grep/파싱 안정성).
    assert parsed["event"] == "ingest_complete"
    assert parsed["record_count"] == 123


def test_main_emits_log_line_to_stdout(monkeypatch: pytest.MonkeyPatch, tmp_path: Any):
    """main 의 stdout 마지막 라인이 파싱 가능한 JSON 이며 핵심 필드를 가지는지 검증.

    `orchestrate` 와 `requests.Session` 을 패치해 실제 HTTP 호출 없이 검증한다.
    """
    result = _make_result()

    def fake_orchestrate(*, config, now, source, writer):  # noqa: ANN001
        return result

    monkeypatch.setattr(entry, "orchestrate", fake_orchestrate)
    # requests.Session 자체는 그대로 두고, 클라이언트 객체는 패치 후 사용되지 않음.

    argv = [
        "--volume-root",
        str(tmp_path),
        "--user-agent",
        "dataplay-bundles/test (ci@example)",
    ]

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        rc = entry.main(argv)

    assert rc == 0
    lines = [line for line in buffer.getvalue().splitlines() if line.strip()]
    last_line = lines[-1]
    parsed = json.loads(last_line)
    assert parsed["event"] == "ingest_complete"
    assert parsed["record_count"] == 123
    assert parsed["window"]["start_iso"] == "2026-05-22T03:20:00Z"

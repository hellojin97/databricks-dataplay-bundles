"""LocalDirectoryWriter 통합 테스트 — 파일 형태·_SUCCESS marker·멱등성 검증."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

from dataplay.wikimedia.window import IngestWindow
from dataplay.wikimedia.writer import LocalDirectoryWriter

WIKI_ID = "en.wikipedia"


def _window() -> IngestWindow:
    return IngestWindow.from_start(datetime(2026, 5, 22, 3, 20, tzinfo=UTC))


def test_writer_creates_jsonl_gz_and_success_marker(tmp_volume_root: str):
    writer = LocalDirectoryWriter(root=tmp_volume_root, wiki_id=WIKI_ID)
    events = [
        {"rcid": 1, "title": "Page 1", "timestamp": "2026-05-22T03:21:00Z"},
        {"rcid": 2, "title": "한국어 페이지", "timestamp": "2026-05-22T03:22:00Z"},
    ]
    result = writer.write_window(_window(), iter(events))

    file_path = Path(result.file_path)
    marker_path = Path(result.success_marker_path)

    assert file_path.exists()
    assert marker_path.exists()
    assert marker_path.name == "_SUCCESS"
    assert marker_path.read_bytes() == b""

    # 파일 경로가 계약대로
    assert "wiki=en.wikipedia/year=2026/month=05/day=22/hour=03/minute=20" in str(file_path)
    assert file_path.name == "recentchanges-2026-05-22T03-20-00Z.jsonl.gz"


def test_writer_content_is_ndjson_gzip_with_all_records(tmp_volume_root: str):
    writer = LocalDirectoryWriter(root=tmp_volume_root, wiki_id=WIKI_ID)
    events = [{"rcid": i, "title": f"Page {i}"} for i in range(5)]
    result = writer.write_window(_window(), iter(events))

    with gzip.open(result.file_path, "rb") as fh:
        decoded = fh.read().decode("utf-8")
    lines = decoded.splitlines()
    assert len(lines) == 5
    assert decoded.endswith("\n")
    parsed = [json.loads(line) for line in lines]
    assert parsed == events


def test_writer_returns_record_count_and_bytes_written(tmp_volume_root: str):
    writer = LocalDirectoryWriter(root=tmp_volume_root, wiki_id=WIKI_ID)
    events = [{"rcid": i} for i in range(7)]
    result = writer.write_window(_window(), iter(events))

    assert result.record_count == 7
    assert result.bytes_written > 0
    assert result.bytes_written == Path(result.file_path).stat().st_size


def test_writer_is_idempotent_on_rerun(tmp_volume_root: str):
    writer = LocalDirectoryWriter(root=tmp_volume_root, wiki_id=WIKI_ID)
    window = _window()

    first = writer.write_window(window, iter([{"rcid": 1}]))
    # 같은 윈도우 재실행 시 동일 경로에 덮어쓰기
    second = writer.write_window(window, iter([{"rcid": 1}, {"rcid": 2}]))

    assert first.file_path == second.file_path
    assert first.success_marker_path == second.success_marker_path
    # 두 번째 실행 결과로 파일이 갱신됨 (라인 수 변화)
    with gzip.open(second.file_path, "rb") as fh:
        lines = fh.read().decode("utf-8").splitlines()
    assert [json.loads(line)["rcid"] for line in lines] == [1, 2]


def test_writer_handles_empty_events(tmp_volume_root: str):
    # 빈 윈도우도 정상 파일 + _SUCCESS 를 만들어야 한다 (다운스트림이 marker 로 완료 판단).
    writer = LocalDirectoryWriter(root=tmp_volume_root, wiki_id=WIKI_ID)
    result = writer.write_window(_window(), iter([]))

    assert result.record_count == 0
    assert Path(result.file_path).exists()
    assert Path(result.success_marker_path).exists()
    with gzip.open(result.file_path, "rb") as fh:
        assert fh.read() == b""


def test_writer_preserves_non_ascii_characters(tmp_volume_root: str):
    writer = LocalDirectoryWriter(root=tmp_volume_root, wiki_id=WIKI_ID)
    events = [{"title": "한국어", "user": "テスト", "comment": "中文评论"}]
    result = writer.write_window(_window(), iter(events))

    with gzip.open(result.file_path, "rb") as fh:
        decoded = fh.read().decode("utf-8")
    parsed = json.loads(decoded.strip())
    assert parsed["title"] == "한국어"
    assert parsed["user"] == "テスト"
    assert parsed["comment"] == "中文评论"


def test_writer_creates_partition_directories(tmp_volume_root: str):
    writer = LocalDirectoryWriter(root=tmp_volume_root, wiki_id=WIKI_ID)
    result = writer.write_window(_window(), iter([{"rcid": 1}]))

    file_path = Path(result.file_path)
    # 부모 디렉터리 5단계가 자동 생성되었는지
    expected_parts = [
        "wiki=en.wikipedia",
        "year=2026",
        "month=05",
        "day=22",
        "hour=03",
        "minute=20",
    ]
    assert all(part in file_path.parts for part in expected_parts)

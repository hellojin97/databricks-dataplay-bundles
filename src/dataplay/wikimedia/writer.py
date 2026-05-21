"""볼륨/로컬 디렉터리 적재 클래스 (I/O).

NDJSON+gzip 으로 1 윈도우 = 1 파일을 stream write 하고 같은 디렉터리에 0-byte `_SUCCESS`
marker 를 생성한다 (contracts/bronze-file-layout.md 의 "원자성" 절). 같은 윈도우 재호출 시
파일과 marker 모두 덮어쓴다 (FR-006 멱등성).

`LocalDirectoryWriter` 는 `tmp_path` 등 로컬 디렉터리를 루트로 사용하는 테스트용 어댑터이며,
`BronzeVolumeWriter` 는 `/Volumes/...` FUSE 경로를 루트로 사용하는 운영용 어댑터다. 두 클래스
는 현재 동일 인터페이스로 동작하며, 향후 볼륨 특화 처리(예: SDK 업로드) 가 필요해지면
`BronzeVolumeWriter` 만 재정의한다.
"""

from __future__ import annotations

import gzip
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .window import (
    IngestWindow,
    serialize_event_line,
    window_to_file_name,
    window_to_volume_dir,
)


@dataclass(frozen=True, slots=True)
class WriteResult:
    """writer 가 호출부에 돌려주는 적재 결과의 부분 정보.

    `api_calls` 같은 source 측 메트릭은 이 결과에 포함되지 않으며, 호출부(pipeline)가 합쳐
    최종 `IngestResult` 를 만든다.
    """

    file_path: str
    success_marker_path: str
    record_count: int
    bytes_written: int


class LocalDirectoryWriter:
    """로컬 파일시스템 어댑터. 테스트(`tmp_path`) 또는 로컬 실험용.

    Databricks Volume FUSE(`/Volumes/...`) 도 POSIX 호환이라 동일 구현으로 동작한다 — 본
    클래스를 그대로 `BronzeVolumeWriter` 로 상속시켜 사용.
    """

    def __init__(self, root: str, wiki_id: str) -> None:
        self._root = root
        self._wiki_id = wiki_id

    def write_window(
        self, window: IngestWindow, events: Iterable[Mapping[str, object]]
    ) -> WriteResult:
        """`events` 를 NDJSON+gzip 으로 윈도우 경로에 stream write 하고 `_SUCCESS` 생성.

        멱등: 같은 윈도우로 재호출 시 두 파일을 모두 덮어쓴다. 외부 상태 저장 없음.
        """
        dir_path = Path(window_to_volume_dir(window, self._root, self._wiki_id))
        file_name = window_to_file_name(window)
        file_path = dir_path / file_name
        success_path = dir_path / "_SUCCESS"

        dir_path.mkdir(parents=True, exist_ok=True)

        record_count = 0
        # `mtime=0` 으로 gzip 헤더 결정성 확보 — 동일 입력 → 동일 바이트 출력.
        with file_path.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            for event in events:
                gz.write(serialize_event_line(event))
                record_count += 1

        bytes_written = file_path.stat().st_size
        # _SUCCESS marker — 0-byte. 다운스트림 소비자는 본 파일 존재로 슬롯 완료를 판단.
        success_path.write_bytes(b"")

        return WriteResult(
            file_path=str(file_path),
            success_marker_path=str(success_path),
            record_count=record_count,
            bytes_written=bytes_written,
        )


class BronzeVolumeWriter(LocalDirectoryWriter):
    """Databricks Unity Catalog Volume(FUSE) 어댑터.

    현재는 `LocalDirectoryWriter` 를 그대로 사용한다 — POSIX FUSE 이므로 일반 파일 I/O 로
    동작. 향후 볼륨 특화 동작(예: SDK 기반 업로드) 이 필요해지면 본 클래스에서 재정의한다.
    """

"""Databricks Lakeflow Job 태스크 엔트리포인트 — 위키미디어 RecentChanges → bronze 적재.

본 스크립트는 **호출부(caller) only** 다 (헌법 원칙 II). 비즈니스 로직은 모두
`dataplay.wikimedia.*` 모듈에 있고, 본 파일은 다음만 수행한다:
  1. argparse 로 잡 파라미터를 받는다.
  2. `IngestionConfig` 와 의존성(requests.Session, source, writer) 을 생성한다.
  3. `orchestrate(...)` 를 호출한다.
  4. 결과 `IngestResult` 를 1라인 JSON 으로 stdout 에 출력한다 (FR-011, US3 부분).

CLI 사용 예:

    python -m dataplay.jobs.wikimedia_recentchanges \\
        --wiki-api-url https://en.wikipedia.org/w/api.php \\
        --volume-root /Volumes/wikimedia-dataplay/bronze/recentchanges_raw \\
        --user-agent "dataplay-bundles/0.1 (contact@example)"
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime

import requests

from dataplay.wikimedia.config import IngestionConfig
from dataplay.wikimedia.pipeline import IngestResult, orchestrate
from dataplay.wikimedia.source import MediaWikiRecentChangesClient
from dataplay.wikimedia.writer import BronzeVolumeWriter


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dataplay.jobs.wikimedia_recentchanges",
        description="Wikimedia RecentChanges 1 윈도우 적재 (Databricks Job 태스크 엔트리포인트).",
    )
    parser.add_argument(
        "--wiki-api-url",
        default="https://en.wikipedia.org/w/api.php",
        help="MediaWiki Action API 엔드포인트 (기본: en.wikipedia).",
    )
    parser.add_argument("--wiki-id", default="en.wikipedia", help="볼륨 경로의 wiki 식별자.")
    parser.add_argument(
        "--volume-root",
        required=True,
        help="적재 볼륨 루트 (예: /Volumes/wikimedia-dataplay/bronze/recentchanges_raw).",
    )
    parser.add_argument(
        "--user-agent",
        required=True,
        help="HTTP User-Agent (Wikimedia 정책상 식별 가능한 값 필수).",
    )
    parser.add_argument(
        "--request-timeout-seconds",
        type=float,
        default=15.0,
        help="단일 HTTP 호출 timeout (초).",
    )
    parser.add_argument(
        "--max-pages-per-window",
        type=int,
        default=10,
        help="1 슬롯당 최대 페이지네이션 호출 수 (초과 시 잡 실패).",
    )
    parser.add_argument(
        "--override-window-start",
        type=_parse_iso_utc,
        default=None,
        help=(
            "수동 백필용 — 적재할 윈도우의 시작 시각 (ISO 8601 UTC, 분이 5의 배수). "
            "미지정 시 자동으로 직전 슬롯을 사용."
        ),
    )
    return parser


def _parse_iso_utc(text: str) -> datetime:
    """``2026-05-22T03:25:00Z`` / ``...+00:00`` 형식을 tz-aware UTC datetime 으로 파싱."""
    normalized = text.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        raise argparse.ArgumentTypeError("override-window-start 는 tz-aware UTC 여야 합니다.")
    return dt.astimezone(UTC)


def _ingest_result_to_log_payload(result: IngestResult) -> dict:
    """`IngestResult` → 구조화 로그 1라인용 dict.

    `window` 는 ISO 'Z' 형식의 시작/종료 시각으로 평탄화해 다운스트림 파싱이 단순해지도록 한다.
    """
    payload = asdict(result)
    payload["window"] = {
        "start_iso": result.window.start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_iso": result.window.end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "key": result.window.key,
    }
    payload["event"] = "ingest_complete"
    return payload


def main(argv: list[str] | None = None) -> int:
    """잡 본문. 정상 종료 시 0, 예외 시 비-0 (Databricks 가 실패로 인식)."""
    args = _build_parser().parse_args(argv)

    config = IngestionConfig(
        wiki_api_url=args.wiki_api_url,
        wiki_id=args.wiki_id,
        volume_root=args.volume_root,
        user_agent=args.user_agent,
        request_timeout_seconds=args.request_timeout_seconds,
        max_pages_per_window=args.max_pages_per_window,
        override_window_start=args.override_window_start,
    )

    session = requests.Session()
    source = MediaWikiRecentChangesClient(
        session=session,
        api_url=str(config.wiki_api_url),
        user_agent=config.user_agent,
        timeout=config.request_timeout_seconds,
    )
    writer = BronzeVolumeWriter(root=config.volume_root, wiki_id=config.wiki_id)

    result = orchestrate(
        config=config,
        now=datetime.now(UTC),
        source=source,
        writer=writer,
    )

    # 마지막 줄을 구조화된 JSON 으로 출력 — 운영자가 잡 로그에서 grep 가능 (FR-011, US3 부분).
    print(json.dumps(_ingest_result_to_log_payload(result), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

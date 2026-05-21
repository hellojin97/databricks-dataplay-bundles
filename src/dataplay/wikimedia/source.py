"""MediaWiki Action API `list=recentchanges` 호출 클라이언트 (I/O 클래스).

헌법 원칙 III 에 따라 외부 시스템 호출은 클래스로 캡슐화한다. 본 클라이언트는 윈도우 1개에
대해 `rcstart`/`rcend` 시간 윈도우로 페이지네이션을 수행하며, 페이지 단위 결과를 `PageBatch`
로 묶어 yield 한다. 오류 정책은 contracts/mediawiki-recentchanges-request.md 의 "오류 처리"
표 참조.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass

import requests

from .config import RecentChangesResponse
from .window import IngestWindow

# `rcprop` 에 가능한 한 풍부한 필드를 요청 — bronze 의 원본 보존 원칙(FR-003).
_RC_PROPS = "title|timestamp|ids|sizes|flags|user|userid|comment|parsedcomment|tags|loginfo"
# 모든 변경 유형을 수집.
_RC_TYPES = "edit|new|log|categorize"
# API 가 허용하는 최대 페이지 크기 (익명 호출 기준).
_RC_LIMIT = 500
# ISO 8601 UTC 'Z' (MediaWiki rcstart/rcend 입력 형식).
_ISO_Z_FMT = "%Y-%m-%dT%H:%M:%SZ"

# 5xx/네트워크 오류 시 백오프 지연 (초). 최대 3회 재시도.
_RETRY_DELAYS_SEC = (1.0, 3.0, 9.0)


@dataclass(frozen=True, slots=True)
class PageBatch:
    """페이지네이션 1회 결과.

    `events` 는 응답의 `query.recentchanges` 배열을 그대로 보존한 immutable tuple.
    `continue_token` 은 다음 페이지가 있을 때만 None 이 아니다.
    """

    events: tuple[dict, ...]
    continue_token: dict[str, str] | None


class MediaWikiRecentChangesClient:
    """단일 wiki 의 RecentChanges 윈도우를 페이지 단위로 가져오는 클라이언트."""

    def __init__(
        self,
        session: requests.Session,
        api_url: str,
        user_agent: str,
        timeout: float = 15.0,
    ) -> None:
        self._session = session
        self._api_url = api_url
        self._user_agent = user_agent
        self._timeout = timeout

    def fetch_batches(self, window: IngestWindow, *, max_pages: int = 10) -> Iterator[PageBatch]:
        """윈도우의 이벤트를 페이지 단위로 yield.

        각 yield = 정확히 1 회의 HTTP 호출 결과 = 1 `PageBatch`. 호출자는 이를 카운트해 잡
        실행의 `api_calls` 메트릭으로 사용한다.

        `max_pages` 초과 시 `RuntimeError` 를 발생시켜 잡을 시끄럽게 실패시킨다 (이벤트 폭증
        의심 신호 — research.md R2).
        """
        base_params = self._build_base_params(window)
        continue_params: dict[str, str] = {}
        for _ in range(max_pages):
            params = {**base_params, **continue_params}
            response = self._request_with_retry(params)
            body = response.json()
            # shape 검증 — 페이로드 자체는 그대로 보존
            parsed = RecentChangesResponse.model_validate(body)
            events_tuple = tuple(parsed.query["recentchanges"])
            cont = body.get("continue")
            yield PageBatch(events=events_tuple, continue_token=cont)
            if not cont:
                return
            continue_params = {str(k): str(v) for k, v in cont.items()}
        raise RuntimeError(f"max_pages_per_window={max_pages} 초과 — 이벤트 폭증 의심. 잡 실패.")

    def _build_base_params(self, window: IngestWindow) -> dict[str, str | int]:
        # rcstart = 윈도우 종료 시각, rcend = 윈도우 시작 시각, rcdir=older 로 newer→older 진행.
        return {
            "action": "query",
            "format": "json",
            "formatversion": 2,
            "list": "recentchanges",
            "rcdir": "older",
            "rcstart": window.end.strftime(_ISO_Z_FMT),
            "rcend": window.start.strftime(_ISO_Z_FMT),
            "rclimit": _RC_LIMIT,
            "rcprop": _RC_PROPS,
            "rctype": _RC_TYPES,
        }

    def _request_with_retry(self, params: dict[str, str | int]) -> requests.Response:
        """contracts/mediawiki-recentchanges-request.md 의 "오류 처리" 표 그대로 구현.

        - 5xx/network: 1s, 3s, 9s 지수 백오프 최대 3회 재시도.
        - 4xx: 즉시 실패 (재시도 없음).
        - 429: `Retry-After` 헤더 존중 후 1회 재시도. 그래도 실패 시 잡 실패.
        - 응답 JSON 파싱 실패: 잡 실패 (호출부의 `.json()` 단계에서 자연스럽게 raise).
        """
        headers = {"User-Agent": self._user_agent, "Accept": "application/json"}
        backoff_idx = 0
        retried_429 = False
        while True:
            try:
                response = self._session.get(
                    self._api_url,
                    params=params,
                    headers=headers,
                    timeout=self._timeout,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                if backoff_idx >= len(_RETRY_DELAYS_SEC):
                    raise RuntimeError(
                        f"MediaWiki 호출이 네트워크/타임아웃 재시도 후 실패: {exc}"
                    ) from exc
                time.sleep(_RETRY_DELAYS_SEC[backoff_idx])
                backoff_idx += 1
                continue

            status = response.status_code
            if status == 429 and not retried_429:
                retry_after = float(response.headers.get("Retry-After", "1"))
                time.sleep(retry_after)
                retried_429 = True
                continue
            if 400 <= status < 500:
                raise requests.HTTPError(
                    f"MediaWiki HTTP {status}: {response.text[:200]}",
                    response=response,
                )
            if 500 <= status < 600:
                if backoff_idx >= len(_RETRY_DELAYS_SEC):
                    raise requests.HTTPError(
                        f"MediaWiki HTTP {status} 재시도 후에도 실패: {response.text[:200]}",
                        response=response,
                    )
                time.sleep(_RETRY_DELAYS_SEC[backoff_idx])
                backoff_idx += 1
                continue
            # 2xx
            return response

"""외부 입력 검증용 Pydantic 모델 (헌법 원칙 III — 외부 입력은 Pydantic).

본 모듈의 모델은 잡 호출부와 외부 API 응답의 경계에서만 사용한다. 내부 변환 함수 간 데이터
전달은 `window` 모듈의 frozen dataclass 를 사용한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

# 5분 슬롯 가정 (window 모듈과 동기화).
_SLOT_MINUTES = 5


class IngestionConfig(BaseModel):
    """잡 호출부가 받는 잡 파라미터·환경의 검증·정규화 컨테이너.

    필드 의미는 data-model.md §1.1 표 참조.
    """

    wiki_api_url: HttpUrl
    wiki_id: str = "en.wikipedia"
    volume_root: str
    user_agent: str
    request_timeout_seconds: float = Field(default=15.0, gt=0)
    max_pages_per_window: int = Field(default=10, gt=0)
    override_window_start: datetime | None = None

    model_config = ConfigDict(frozen=True)

    @field_validator("wiki_api_url")
    @classmethod
    def _https_only(cls, value: HttpUrl) -> HttpUrl:
        # 평문 HTTP 는 위키미디어 정책상 비권장 + 자격증명 노출 위험으로 금지.
        if value.scheme != "https":
            raise ValueError("wiki_api_url 은 https 만 허용됩니다.")
        return value

    @field_validator("user_agent")
    @classmethod
    def _user_agent_nonempty(cls, value: str) -> str:
        # 위키미디어 정책상 식별 가능한 UA 필수 — 빈 문자열/공백은 거부.
        if not value or not value.strip():
            raise ValueError("user_agent 는 비어 있을 수 없습니다 (Wikimedia 정책).")
        return value

    @field_validator("volume_root")
    @classmethod
    def _absolute_path(cls, value: str) -> str:
        # `/Volumes/...` 또는 테스트용 절대 경로. 상대 경로는 거부.
        if not value.startswith("/"):
            raise ValueError("volume_root 는 절대 경로여야 합니다.")
        return value.rstrip("/")

    @field_validator("override_window_start")
    @classmethod
    def _window_start_aligned(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("override_window_start 는 tz-aware UTC 여야 합니다.")
        if value.utcoffset() != timedelta(0):
            raise ValueError("override_window_start 는 UTC 여야 합니다.")
        if value.minute % _SLOT_MINUTES != 0 or value.second != 0 or value.microsecond != 0:
            raise ValueError("override_window_start 는 벽시계 5분 경계여야 합니다 (분/초/μs = 0).")
        return value


class RecentChangesResponse(BaseModel):
    """MediaWiki API 응답의 shape 검증 — 본문 페이로드는 가공 없이 보존 (FR-003).

    `extra='allow'` 로 알 수 없는 최상위 키를 무시. `query.recentchanges` 가 list 인지만 강제.
    """

    batchcomplete: Any = None
    continue_token: dict[str, Any] | None = Field(default=None, alias="continue")
    query: dict[str, Any]

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    @field_validator("query")
    @classmethod
    def _has_recentchanges_list(cls, value: dict[str, Any]) -> dict[str, Any]:
        if "recentchanges" not in value:
            raise ValueError("응답의 query.recentchanges 필드가 없습니다.")
        if not isinstance(value["recentchanges"], list):
            raise ValueError("query.recentchanges 는 list 여야 합니다.")
        return value

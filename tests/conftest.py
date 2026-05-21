"""테스트 공용 fixture.

외부 자원(워크스페이스·HTTP·파일시스템) 의존을 최소화하기 위해, 단위·통합 테스트에서 공통으로
사용하는 결정적 fixture 를 모아둔다 (헌법 원칙 V — 외부 자원 접근 금지).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest


@pytest.fixture
def frozen_now() -> datetime:
    """결정적 테스트를 위한 고정 UTC datetime.

    값은 임의로 선택한 ``2026-05-22T03:27:13.456789Z``. 분이 5의 배수가 아닌(=직전 슬롯 계산이
    의미 있는) 시각이고, 초·마이크로초도 포함되어 슬롯 계산 함수가 이를 정확히 무시하는지
    확인하는 데 적합하다.
    """
    return datetime(2026, 5, 22, 3, 27, 13, 456789, tzinfo=UTC)


@pytest.fixture
def tmp_volume_root(tmp_path: Path) -> str:
    """볼륨 루트 역할을 하는 임시 디렉터리 경로(POSIX 문자열).

    실제 운영에서는 ``/Volumes/<catalog>/<schema>/<volume>`` 이지만, 테스트에서는 동일
    인터페이스의 ``LocalDirectoryWriter`` 가 tmp_path 를 루트로 사용한다.
    """
    root = tmp_path / "Volumes" / "wikimedia-dataplay" / "bronze" / "recentchanges_raw"
    root.mkdir(parents=True, exist_ok=True)
    return str(root)

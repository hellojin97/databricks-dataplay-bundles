"""MediaWikiRecentChangesClient 통합 테스트 — HTTP 는 ``responses`` 라이브러리로 더블링."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import requests
import responses

from dataplay.wikimedia.source import MediaWikiRecentChangesClient
from dataplay.wikimedia.window import IngestWindow

API_URL = "https://en.wikipedia.org/w/api.php"


def _window_at(year=2026, month=5, day=22, hour=3, minute=20) -> IngestWindow:
    return IngestWindow.from_start(datetime(year, month, day, hour, minute, tzinfo=UTC))


def _ok_response(events: list[dict], continue_token: dict | None = None) -> dict:
    body: dict = {
        "batchcomplete": True,
        "query": {"recentchanges": events},
    }
    if continue_token is not None:
        body["continue"] = continue_token
    return body


def _make_client(
    user_agent: str = "dataplay-bundles/test (ci@example)",
) -> MediaWikiRecentChangesClient:
    return MediaWikiRecentChangesClient(
        session=requests.Session(),
        api_url=API_URL,
        user_agent=user_agent,
        timeout=5.0,
    )


@responses.activate
def test_fetch_batches_single_page_yields_one_batch():
    events = [{"rcid": 1, "timestamp": "2026-05-22T03:21:00Z"}]
    responses.add(responses.GET, API_URL, json=_ok_response(events), status=200)

    client = _make_client()
    batches = list(client.fetch_batches(_window_at(), max_pages=5))

    assert len(batches) == 1
    assert batches[0].events == tuple(events)
    assert batches[0].continue_token is None


@responses.activate
def test_fetch_batches_paginates_until_continue_absent():
    page1 = _ok_response(
        [{"rcid": 1, "timestamp": "2026-05-22T03:24:00Z"}],
        continue_token={"rccontinue": "20260522032300|2", "continue": "-||"},
    )
    page2 = _ok_response(
        [{"rcid": 2, "timestamp": "2026-05-22T03:23:00Z"}],
        continue_token={"rccontinue": "20260522032200|3", "continue": "-||"},
    )
    page3 = _ok_response([{"rcid": 3, "timestamp": "2026-05-22T03:22:00Z"}])

    responses.add(responses.GET, API_URL, json=page1, status=200)
    responses.add(responses.GET, API_URL, json=page2, status=200)
    responses.add(responses.GET, API_URL, json=page3, status=200)

    client = _make_client()
    batches = list(client.fetch_batches(_window_at(), max_pages=5))

    assert len(batches) == 3
    assert [b.events[0]["rcid"] for b in batches] == [1, 2, 3]
    assert batches[-1].continue_token is None


@responses.activate
def test_fetch_batches_sends_user_agent_header():
    responses.add(responses.GET, API_URL, json=_ok_response([]), status=200)

    client = _make_client(user_agent="dataplay-bundles/0.1 (contact@example)")
    list(client.fetch_batches(_window_at(), max_pages=1))

    assert len(responses.calls) == 1
    assert responses.calls[0].request.headers["User-Agent"] == (
        "dataplay-bundles/0.1 (contact@example)"
    )


@responses.activate
def test_fetch_batches_includes_required_query_params():
    responses.add(responses.GET, API_URL, json=_ok_response([]), status=200)

    client = _make_client()
    list(client.fetch_batches(_window_at(), max_pages=1))

    request_url = responses.calls[0].request.url
    assert request_url is not None
    # 필수 파라미터들이 모두 들어가 있는지 (값 자체는 contracts 가 강제)
    for key in (
        "action=query",
        "format=json",
        "formatversion=2",
        "list=recentchanges",
        "rcdir=older",
        "rcstart=2026-05-22T03",
        "rcend=2026-05-22T03",
        "rclimit=500",
    ):
        assert key in request_url


@responses.activate
def test_fetch_batches_raises_when_max_pages_exceeded():
    cont = {"rccontinue": "abc", "continue": "-||"}
    # 3페이지 모두 continue 가 붙어있어 페이지네이션이 끝나지 않는 시나리오
    for _ in range(3):
        responses.add(responses.GET, API_URL, json=_ok_response([{"rcid": 0}], cont), status=200)

    client = _make_client()
    with pytest.raises(RuntimeError, match="max_pages_per_window"):
        list(client.fetch_batches(_window_at(), max_pages=2))


@responses.activate
def test_fetch_batches_fails_immediately_on_4xx():
    responses.add(responses.GET, API_URL, json={"error": "bad UA"}, status=403)

    client = _make_client()
    with pytest.raises(requests.HTTPError, match="403"):
        list(client.fetch_batches(_window_at(), max_pages=1))


@responses.activate
def test_fetch_batches_retries_once_on_429(monkeypatch):
    # time.sleep 을 패치해 테스트가 실제로 대기하지 않게.
    import dataplay.wikimedia.source as source_module

    sleeps: list[float] = []
    monkeypatch.setattr(source_module.time, "sleep", lambda s: sleeps.append(s))

    responses.add(
        responses.GET,
        API_URL,
        json={"error": "rate"},
        status=429,
        headers={"Retry-After": "2"},
    )
    responses.add(responses.GET, API_URL, json=_ok_response([{"rcid": 7}]), status=200)

    client = _make_client()
    batches = list(client.fetch_batches(_window_at(), max_pages=1))

    assert len(batches) == 1
    assert batches[0].events[0]["rcid"] == 7
    assert sleeps == [2.0]  # Retry-After 헤더 그대로 적용


@responses.activate
def test_fetch_batches_retries_5xx_then_succeeds(monkeypatch):
    import dataplay.wikimedia.source as source_module

    sleeps: list[float] = []
    monkeypatch.setattr(source_module.time, "sleep", lambda s: sleeps.append(s))

    responses.add(responses.GET, API_URL, status=503)
    responses.add(responses.GET, API_URL, status=502)
    responses.add(responses.GET, API_URL, json=_ok_response([{"rcid": 9}]), status=200)

    client = _make_client()
    batches = list(client.fetch_batches(_window_at(), max_pages=1))

    assert len(batches) == 1
    # 5xx 2회 발생 → 백오프 2회 (1s, 3s)
    assert sleeps == [1.0, 3.0]


@responses.activate
def test_fetch_batches_fails_after_5xx_retries_exhausted(monkeypatch):
    import dataplay.wikimedia.source as source_module

    monkeypatch.setattr(source_module.time, "sleep", lambda s: None)

    for _ in range(4):
        responses.add(responses.GET, API_URL, status=500)

    client = _make_client()
    with pytest.raises(requests.HTTPError, match="500"):
        list(client.fetch_batches(_window_at(), max_pages=1))

"""HTTP behavior is tested with a mock transport and a virtual clock."""
from collections.abc import Iterator

import httpx
import pytest

from dv.config import SECSettings
from dv.sec_client import SECClient


@pytest.fixture()
def identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEC_TEST_IDENTITY", "Offline Tester tester@invalid.test")


def test_identity_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEC_TEST_IDENTITY", raising=False)
    with pytest.raises(ValueError, match="real name and email"):
        SECClient(SECSettings(user_agent_env="SEC_TEST_IDENTITY"))


def test_rate_limit_and_header(identity: None) -> None:
    now = [0.0]
    seen: list[float] = []

    def sleep(seconds: float) -> None:
        now[0] += seconds

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["user-agent"] == "Offline Tester tester@invalid.test"
        seen.append(now[0])
        return httpx.Response(200, json={"ok": True})

    with SECClient(SECSettings(user_agent_env="SEC_TEST_IDENTITY"), transport=httpx.MockTransport(handler),
                   sleep=sleep, clock=lambda: now[0]) as client:
        for _ in range(3):
            client.get_json("https://data.sec.gov/test", ticker="TEST", step="test")
    assert seen == [0, 0.125, 0.25]


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_status_retries(identity: None, status: int) -> None:
    statuses: Iterator[int] = iter([status, status, 200])
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        code = next(statuses)
        calls.append(code)
        return httpx.Response(code, json={"ok": True})

    with SECClient(SECSettings(user_agent_env="SEC_TEST_IDENTITY"), transport=httpx.MockTransport(handler),
                   sleep=lambda _: None) as client:
        assert client.get_json("https://data.sec.gov/test", ticker="TEST", step="test") == {"ok": True}
    assert calls == [status, status, 200]


def test_nontransient_error_does_not_retry(identity: None) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(403)
        return httpx.Response(403)

    with SECClient(SECSettings(user_agent_env="SEC_TEST_IDENTITY"), transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            client.get_json("https://data.sec.gov/test", ticker="TEST", step="test")
    assert calls == [403]

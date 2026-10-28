"""Offline provider gates using scripted responses and temporary SQLite databases."""
import json
from pathlib import Path
from typing import Literal

import httpx
import pytest
from pydantic import BaseModel

from dv.config import LLMSettings, load_config
from dv.llm import AllProvidersFailed, CallContext, CompatibleProvider, FakeProvider, LLMClient, ProviderResponse, configured_providers


class Answer(BaseModel):
    ok: Literal[True]


@pytest.fixture()
def settings() -> LLMSettings:
    settings = load_config().llm
    return settings.model_copy(update={"providers": [entry.model_copy(update={"model": "FILL_IN_TEST_MODEL"}) for entry in settings.providers]})


@pytest.fixture()
def context() -> CallContext:
    return CallContext(run_id="test", mode="baseline", ticker="TEST", step="extract")


def good(tokens_in: int = 1000, tokens_out: int = 200) -> ProviderResponse:
    return ProviderResponse(content='{"ok": true}', input_tokens=tokens_in, output_tokens=tokens_out)


def limited() -> httpx.HTTPStatusError:
    response = httpx.Response(429, request=httpx.Request("POST", "https://offline.test"))
    return httpx.HTTPStatusError("rate limited", request=response.request, response=response)


def test_fallback_order_after_three_429s(settings: LLMSettings, context: CallContext, tmp_path: Path) -> None:
    first = FakeProvider("first", [limited(), limited(), limited()])
    second = FakeProvider("second", [good()])
    sleeps: list[float] = []
    with LLMClient(settings, tmp_path / "runs.db", [first, second], sleep=sleeps.append) as client:
        assert client.complete("JSON please", Answer, context).ok
        rows = client.db.execute("SELECT provider, error FROM llm_calls ORDER BY id").fetchall()
    assert [row["provider"] for row in rows] == ["first", "first", "first", "second"]
    assert rows[0]["error"] == "HTTPStatusError"
    assert sleeps == [2, 4]


def test_cache_hit_and_cost_math(settings: LLMSettings, context: CallContext, tmp_path: Path) -> None:
    provider = FakeProvider("local", [good()])
    with LLMClient(settings, tmp_path / "runs.db", [provider]) as client:
        first = client.complete("same JSON prompt", Answer, context)
        second = client.complete("same JSON prompt", Answer, context.model_copy(update={"mode": "verified"}))
        rows = client.db.execute("SELECT * FROM llm_calls ORDER BY id").fetchall()
    assert first == second
    assert len(provider.prompts) == 1
    assert len(rows) == 2
    assert rows[0]["input_tokens"] == 1000
    assert rows[0]["output_tokens"] == 200
    assert rows[0]["cost_actual_usd"] == 0
    assert rows[0]["cost_reference_usd"] == pytest.approx(0.006)
    assert rows[1]["cache_hit"] == 1
    assert rows[1]["mode"] == "verified"
    assert rows[1]["input_tokens"] == rows[1]["output_tokens"] == 0
    assert rows[1]["cost_reference_usd"] == 0


def test_cache_survives_client_restart(settings: LLMSettings, context: CallContext, tmp_path: Path) -> None:
    db_path = tmp_path / "runs.db"
    with LLMClient(settings, db_path, [FakeProvider("local", [good()])]) as client:
        client.complete("JSON prompt", Answer, context)
    provider = FakeProvider("local", [])
    with LLMClient(settings, db_path, [provider]) as client:
        assert client.complete("JSON prompt", Answer, context).ok
    assert provider.prompts == []


def test_json_repair_logs_both_calls(settings: LLMSettings, context: CallContext, tmp_path: Path) -> None:
    bad = ProviderResponse(content="not JSON", input_tokens=30, output_tokens=10)
    provider = FakeProvider("local", [bad, good()])
    with LLMClient(settings, tmp_path / "runs.db", [provider]) as client:
        assert client.complete("JSON please", Answer, context).ok
        rows = client.db.execute("SELECT step, input_tokens FROM llm_calls ORDER BY id").fetchall()
    assert [row["step"] for row in rows] == ["extract", "extract.repair"]
    assert "Validation error:" in provider.prompts[1]
    assert "not JSON" in provider.prompts[1]


def test_invalid_repair_falls_back(settings: LLMSettings, context: CallContext, tmp_path: Path) -> None:
    bad = ProviderResponse(content='{"ok": false}', input_tokens=10, output_tokens=10)
    first = FakeProvider("first", [bad, bad])
    second = FakeProvider("second", [good()])
    with LLMClient(settings, tmp_path / "runs.db", [first, second]) as client:
        assert client.complete("JSON please", Answer, context).ok
        assert client.db.execute("SELECT count(*) FROM llm_calls").fetchone()[0] == 3
    assert len(first.prompts) == 2
    assert len(second.prompts) == 1


def test_pinned_never_switches_and_retries_five_times(settings: LLMSettings, context: CallContext, tmp_path: Path) -> None:
    first = FakeProvider("first", [RuntimeError("unavailable") for _ in range(6)])
    second = FakeProvider("second", [good()])
    sleeps: list[float] = []
    with LLMClient(settings, tmp_path / "runs.db", [first, second], sleep=sleeps.append) as client:
        with pytest.raises(AllProvidersFailed):
            client.complete("JSON please", Answer, context, pin_model=True)
        assert client.db.execute("SELECT count(*) FROM llm_calls").fetchone()[0] == 6
    assert len(first.prompts) == 6
    assert second.prompts == []
    assert sleeps == [60] * 5


def test_placeholder_providers_warn_and_skip(settings: LLMSettings, caplog: pytest.LogCaptureFixture) -> None:
    assert configured_providers(settings) == []
    assert caplog.text.count("placeholder model") == 4


def test_no_provider_fails_explicitly(settings: LLMSettings, context: CallContext, tmp_path: Path) -> None:
    with LLMClient(settings, tmp_path / "runs.db", []) as client:
        with pytest.raises(AllProvidersFailed, match="No configured provider"):
            client.complete("JSON please", Answer, context)


def test_changed_model_or_prompt_does_not_reuse_cache(settings: LLMSettings, context: CallContext, tmp_path: Path) -> None:
    provider = FakeProvider("local", [good(), good(), good()])
    with LLMClient(settings, tmp_path / "runs.db", [provider]) as client:
        client.complete("first JSON prompt", Answer, context)
        client.complete("different JSON prompt", Answer, context)
        provider.model = "different-model"
        client.complete("first JSON prompt", Answer, context)
        assert client.db.execute("SELECT count(*) FROM llm_cache").fetchone()[0] == 3
    assert len(provider.prompts) == 3


def test_schema_is_part_of_cache_key(settings: LLMSettings, tmp_path: Path) -> None:
    class DifferentAnswer(BaseModel):
        value: int

    provider = FakeProvider("local", [])
    with LLMClient(settings, tmp_path / "runs.db", [provider]) as client:
        assert client.cache_key(provider, "JSON", Answer) != client.cache_key(provider, "JSON", DifferentAnswer)


def test_cache_contains_validated_json(settings: LLMSettings, context: CallContext, tmp_path: Path) -> None:
    provider = FakeProvider("local", [good()])
    with LLMClient(settings, tmp_path / "runs.db", [provider]) as client:
        client.complete("JSON", Answer, context)
        cached = client.db.execute("SELECT content FROM llm_cache").fetchone()[0]
        assert json.loads(cached) == {"ok": True}


def test_thinking_configuration_changes_cache_key(settings: LLMSettings,tmp_path: Path) -> None:
    provider=FakeProvider("local",[])
    with LLMClient(settings,tmp_path/"runs.db",[provider]) as client:
        first=client.cache_key(provider,"JSON",Answer)
        provider.thinking_level="minimal"
        assert client.cache_key(provider,"JSON",Answer)!=first


def test_compatible_provider_sends_documented_thinking_options(settings: LLMSettings,monkeypatch: pytest.MonkeyPatch) -> None:
    from openai import OpenAI
    monkeypatch.setenv("DV_TEST_KEY","offline-only")
    entry=settings.providers[0].model_copy(update={"api_key_env":"DV_TEST_KEY","model":"gemma-4-31b-it","thinking_level":"minimal"})
    provider=CompatibleProvider(entry,1)
    provider._client.close()

    def handler(request: httpx.Request) -> httpx.Response:
        body=json.loads(request.content)
        assert body["temperature"]==0
        assert body["response_format"]=={"type":"json_object"}
        assert body["extra_body"]["google"]["thinking_config"]=={"thinking_level":"minimal","include_thoughts":False}
        return httpx.Response(200,json={"id":"fake","object":"chat.completion","created":0,"model":"gemma-4-31b-it",
            "choices":[{"index":0,"message":{"role":"assistant","content":'{"ok":true}'},"finish_reason":"stop"}],
            "usage":{"prompt_tokens":4,"completion_tokens":3,"total_tokens":7}})

    provider._client=OpenAI(api_key="offline-only",base_url="https://offline.test/v1",max_retries=0,
                            http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        result=provider.complete("JSON",temperature=0,max_tokens=2000)
        assert result.input_tokens==4
        assert result.output_tokens==3
    finally:
        provider.close()

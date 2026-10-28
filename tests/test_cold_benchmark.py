"""Cold-run measurement wrappers preserve prompts/cache identity; tests offline."""
from pathlib import Path

import pytest

from dv.config import load_config
from dv.llm import CallContext, FakeProvider, ProviderResponse
from dv.models import ExtractedFact
from scripts import cold_benchmark as benchmark


def test_attempt_cost_labels_do_not_change_prompts_or_cache_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fact = ExtractedFact(metric="revenue", value_as_written=None, scale_as_written=None, period_end=None,
                         source_chunk_id=None, source_quote=None)
    provider = FakeProvider("fixture", [ProviderResponse(content=fact.model_dump_json(), input_tokens=10, output_tokens=5)])
    monkeypatch.setattr(benchmark, "PacedProvider", lambda settings, interval: provider)
    with benchmark.MeasuredClient(load_config().llm, tmp_path / "runs.db") as client:
        assert client.db.execute("SELECT count(*) FROM llm_cache").fetchone()[0] == 0
        context = CallContext(run_id="cold", mode="verified", ticker="TEST", step="revenue")
        assert client.complete("unchanged prompt", ExtractedFact, context, pin_model=True) == fact
        assert client.complete("unchanged prompt", ExtractedFact, context, pin_model=True) == fact
        calls = list(client.db.execute("SELECT step,cache_hit FROM llm_calls ORDER BY id"))
        assert [tuple(row) for row in calls] == [("revenue.attempt_1", 0), ("revenue.attempt_2", 1)]
        identity = list(client.db.execute("SELECT prompt_sha256,cache_key FROM benchmark_request_identity ORDER BY extraction_attempt"))
        assert tuple(identity[0]) == tuple(identity[1])
    assert provider.prompts == ["unchanged prompt"]


def test_request_pacing_preserves_generation_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = object.__new__(benchmark.PacedProvider)
    provider.interval = 5.0
    provider.last_started = 0.0
    times = iter([3.0, 5.0])
    sleeps: list[float] = []
    monkeypatch.setattr(benchmark.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(benchmark.time, "sleep", sleeps.append)

    def complete(self: object, prompt: str, *, temperature: int, max_tokens: int) -> ProviderResponse:
        assert prompt == "unaltered" and temperature == 0 and max_tokens == 2000
        return ProviderResponse(content="{}", input_tokens=1, output_tokens=1)

    monkeypatch.setattr(benchmark.CompatibleProvider, "complete", complete)
    provider.complete("unaltered", temperature=0, max_tokens=2000)
    assert sleeps == [2.0]

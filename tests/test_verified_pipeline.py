"""Retry feedback, unverified abstention and missing-fact behavior with fake models."""
from pathlib import Path

from dv.config import load_config
from dv.llm import FakeProvider, LLMClient, ProviderResponse
from dv.models import Chunk, ExtractedFact, FilingMetadata
from dv.pipeline import prepare_database, verified_fact
from dv.retrieve import FilingIndex


def fixture_inputs() -> tuple[FilingMetadata, FilingIndex, ExtractedFact]:
    filing = FilingMetadata(ticker="TEST", cik=1, accession="acc", period_of_report="2025-12-31",
                            filing_date="2026-02-01", primary_document="test.htm")
    chunks = [Chunk(chunk_id=f"c{i}", ticker="TEST", accession="acc", section="item_8",
                    text=f" | 2025\nRevenue | 100\nSource {i}", is_table=True,
                    detected_scale="units", scale_excludes_per_share=False) for i in range(12)]
    fact = ExtractedFact(metric="revenue", value_as_written="100", scale_as_written="units",
                         period_end="2025-12-31", source_chunk_id="c0", source_quote="Revenue | 100")
    return filing, FilingIndex(chunks), fact


def response(fact: ExtractedFact) -> ProviderResponse:
    return ProviderResponse(content=fact.model_dump_json(), input_tokens=100, output_tokens=50)


def test_failed_quote_gets_feedback_and_extra_chunks(tmp_path: Path) -> None:
    filing, index, fact = fixture_inputs()
    bad = fact.model_copy(update={"source_quote": "Revenue | 999", "value_as_written": "999"})
    provider = FakeProvider("local", [response(bad), response(fact)])
    config = load_config()
    with LLMClient(config.llm, tmp_path / "runs.db", [provider]) as client:
        prepare_database(client.db)
        result = verified_fact(client, config, "r", "TEST", "revenue", filing, index, {})
        assert client.db.execute("SELECT count(*) FROM verification_attempts").fetchone()[0] == 2
    assert result.status == "answered"
    assert result.attempts == 2
    assert result.verification is not None and result.verification.passed
    assert result.final_value == 100
    assert "Previous answer failed V2:" in provider.prompts[1]
    assert provider.prompts[0].count("END CHUNK") == 5
    assert provider.prompts[1].count("END CHUNK") == 10


def test_three_failures_abstain_without_final_value(tmp_path: Path) -> None:
    filing, index, fact = fixture_inputs()
    bad = fact.model_copy(update={"scale_as_written": "billions"})
    provider = FakeProvider("local", [response(bad)] * 3)
    config = load_config()
    with LLMClient(config.llm, tmp_path / "runs.db", [provider]) as client:
        prepare_database(client.db)
        result = verified_fact(client, config, "r", "TEST", "revenue", filing, index, {})
    assert result.status == "unverified"
    assert result.attempts == 3
    assert result.final_value is None
    assert result.verification is not None and result.verification.failed_check == "V5"
    assert len(provider.prompts) == 3


def test_null_value_stops_without_retries(tmp_path: Path) -> None:
    filing, index, fact = fixture_inputs()
    missing = fact.model_copy(update={"value_as_written": None, "source_quote": None, "source_chunk_id": None,
                                      "scale_as_written": None, "period_end": None})
    provider = FakeProvider("local", [response(missing)])
    config = load_config()
    with LLMClient(config.llm, tmp_path / "runs.db", [provider]) as client:
        prepare_database(client.db)
        result = verified_fact(client, config, "r", "TEST", "revenue", filing, index, {})
    assert result.status == "not_found"
    assert result.attempts == 1
    assert result.verification is None
    assert len(provider.prompts) == 1

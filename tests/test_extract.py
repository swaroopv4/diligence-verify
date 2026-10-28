"""Extraction contracts and first-attempt parity, without a real LLM."""
from pathlib import Path

import pytest

from dv.config import load_config
from dv.extract import extract_fact
from dv.llm import CallContext, FakeProvider, LLMClient, ProviderResponse
from dv.models import Chunk, ExtractedFact, FilingMetadata
from dv.pipeline import empty_fact, prepare_database, save_result
from dv.prompts import extraction_prompt, without_titles


def test_base_prompt_and_first_answer_shared_between_modes(tmp_path: Path) -> None:
    filing = FilingMetadata(ticker="TEST", cik=1, accession="acc", period_of_report="2025-12-31",
                            filing_date="2026-02-01", primary_document="test.htm")
    chunk = Chunk(chunk_id="TEST_acc_item_8_0000", ticker="TEST", accession="acc", section="item_8",
                  text="In millions\n2025\nRevenue | 1,234", is_table=True,
                  detected_scale="millions", scale_excludes_per_share=False)
    fact = ExtractedFact(metric="revenue", value_as_written="1,234", scale_as_written="In millions",
                         period_end="2025-12-31", source_chunk_id=chunk.chunk_id, source_quote="Revenue | 1,234")
    provider = FakeProvider("local", [ProviderResponse(content=fact.model_dump_json(), input_tokens=100, output_tokens=50)])
    with LLMClient(load_config().llm, tmp_path / "runs.db", [provider]) as client:
        context = CallContext(run_id="test", mode="baseline", ticker="TEST", step="revenue")
        first = extract_fact(client, context, "revenue", "revenue", filing, [chunk])
        second = extract_fact(client, context.model_copy(update={"mode": "verified"}), "revenue", "revenue", filing, [chunk])
    assert first == second == fact
    assert len(provider.prompts) == 1
    assert "2025-12-31" in provider.prompts[0]
    assert "never" in provider.prompts[0].lower()
    assert extraction_prompt("revenue", "revenue", filing, [chunk]) == provider.prompts[0]


def test_result_commit_is_immediate_and_unique(tmp_path: Path) -> None:
    import sqlite3
    import pytest
    from dv.models import FactResult

    path = tmp_path / "runs.db"
    with sqlite3.connect(path) as db:
        prepare_database(db)
        result = FactResult(run_id="r", mode="baseline", ticker="TEST", metric="revenue",
                            fact=empty_fact("revenue"), verification=None, attempts=1,
                            status="not_found", final_value=None)
        save_result(db, result)
        with sqlite3.connect(path) as reader:
            assert reader.execute("SELECT count(*) FROM fact_results").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            save_result(db, result)


def test_wrong_metric_label_uses_schema_repair(tmp_path: Path) -> None:
    filing = FilingMetadata(ticker="TEST", cik=1, accession="acc", period_of_report="2025-12-31",
                            filing_date="2026-02-01", primary_document="test.htm")
    correct = empty_fact("revenue")
    wrong = correct.model_copy(update={"metric": "total revenue"})
    provider = FakeProvider("local", [ProviderResponse(content=item.model_dump_json(), input_tokens=10, output_tokens=10)
                                      for item in [wrong, correct]])
    with LLMClient(load_config().llm, tmp_path / "runs.db", [provider]) as client:
        context = CallContext(run_id="test", mode="baseline", ticker="TEST", step="revenue")
        assert extract_fact(client, context, "revenue", "revenue", filing, []) == correct
        steps = [row[0] for row in client.db.execute("SELECT step FROM llm_calls ORDER BY id")]
    assert steps == ["revenue", "revenue.repair"]
    assert "revenue" in provider.prompts[1]


def test_compact_retry_schema_preserves_constraints() -> None:
    schema = ExtractedFact.model_json_schema()
    cleaned = without_titles(schema)
    assert cleaned["required"] == schema["required"]
    assert cleaned["additionalProperties"] is False
    assert cleaned["properties"]["source_quote"]["anyOf"][0]["maxLength"] == 300
    assert "title" not in cleaned


def test_answer_key_import_boundary() -> None:
    import ast
    from dv.config import project_root

    for path in (project_root() / "src" / "dv").glob("*.py"):
        if path.name in {"evaluate.py", "groundtruth.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        assert not any(name.endswith("groundtruth") for name in imports), path.name


def test_run_resume_skips_committed_facts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlite3
    import dv.pipeline as pipeline

    config = load_config()
    config.companies.dev = ["TEST"]
    filing = FilingMetadata(ticker="TEST", cik=1, accession="acc", period_of_report="2025-12-31",
                            filing_date="2026-02-01", primary_document="test.htm")
    chunk = Chunk(chunk_id="TEST_acc_item_8_0000", ticker="TEST", accession="acc", section="item_8",
                  text="2025 Revenue income assets cash equity EPS | 100", is_table=True,
                  detected_scale="units", scale_excludes_per_share=False)
    raw = tmp_path / "data" / "raw"
    processed = tmp_path / "data" / "processed"
    raw.mkdir(parents=True)
    processed.mkdir(parents=True)
    (raw / "TEST_filing.json").write_text(filing.model_dump_json(), encoding="utf-8")
    (processed / "TEST_acc.jsonl").write_text(chunk.model_dump_json() + "\n", encoding="utf-8")
    events = [ProviderResponse(content=empty_fact(metric).model_dump_json(), input_tokens=10, output_tokens=10)
              for metric in config.metrics]
    provider = FakeProvider("local", events)
    real_client = LLMClient
    monkeypatch.setattr(pipeline, "project_root", lambda: tmp_path)
    monkeypatch.setattr(pipeline, "load_config", lambda: config)
    monkeypatch.setattr(pipeline, "LLMClient", lambda settings, path: real_client(settings, path, [provider]))
    first = pipeline.run_extraction("resume", "baseline", "dev")
    second = pipeline.run_extraction("resume", "baseline", "dev")
    assert first == second
    assert len(first) == 9
    assert len(provider.prompts) == 9
    with sqlite3.connect(tmp_path / "data" / "runs.db") as db:
        assert db.execute("SELECT count(*) FROM fact_results").fetchone()[0] == 9

"""Source highlighting preserves evidence while escaping HTML."""
from pathlib import Path
import pytest

from app.streamlit_app import highlighted_quote


def test_highlight_uses_verifier_whitespace_and_unicode_rules() -> None:
    rendered,found=highlighted_quote("2025\n‘Cash’ —   1,234", "'Cash' - 1,234")
    assert found
    assert "<mark>‘Cash’ —   1,234</mark>" in rendered


def test_source_html_is_escaped_and_missing_quote_is_safe() -> None:
    rendered,found=highlighted_quote("<script>alert(1)</script>","<script>")
    assert found
    assert "<script>" not in rendered
    assert "<mark>&lt;script&gt;</mark>" in rendered
    rendered,found=highlighted_quote("Revenue | 100", "Revenue | 999")
    assert not found
    assert "<mark>" not in rendered


def test_financial_display_and_exact_table_cell_highlight() -> None:
    import json
    from pathlib import Path
    from app.streamlit_app import format_number, highlighted_evidence
    from dv.models import Chunk, FactResult, ExtractedFact

    assert format_number(35_934_000_000) == "$35.93B"
    assert format_number(7.46, "eps_diluted") == "$7.46"
    assert format_number(-267_000_000) == "−$267.00M"
    assert format_number(None) == "—"
    cases = json.loads((Path(__file__).parent / "fixtures" / "phase5b_cases.json").read_text(encoding="utf-8"))
    case = next(row for row in cases if row["filing"]["ticker"] == "AAPL")
    fact = FactResult(run_id="fixture", mode="verified", ticker="AAPL", metric="eps_diluted",
                      fact=ExtractedFact.model_validate(case["fact"]), verification=None,
                      attempts=1, status="answered", final_value=7.46)
    rendered, caption = highlighted_evidence(Chunk.model_validate(case["chunk"]), fact)
    assert '<span class="selected-row">Diluted | $ |<mark class="selected-cell"> 7.46 </mark>' in rendered
    assert "September 27, 2025" in caption


def test_study_pairing_and_cache_costs_use_provenance() -> None:
    """A verified-only repair run must not replace first-study costs or baseline."""
    import json
    import sqlite3
    from app.streamlit_app import select_studies, caught_errors, call_usage
    from dv.config import load_config
    from dv.models import EvaluationRow, ExtractedFact, FactResult, VerificationResult

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE runs(run_id TEXT,model TEXT,created_at TEXT,settings_json TEXT);
        CREATE TABLE fact_results(run_id TEXT,mode TEXT,ticker TEXT,metric TEXT,result_json TEXT);
        CREATE TABLE evaluations(run_id TEXT,mode TEXT,ticker TEXT,metric TEXT,classification TEXT,result_json TEXT);
        CREATE TABLE run_filings(run_id TEXT,ticker TEXT,filing_json TEXT,chunk_sha256 TEXT);
        CREATE TABLE llm_calls(run_id TEXT,mode TEXT,input_tokens INT,output_tokens INT,cost_reference_usd REAL,cost_actual_usd REAL,cache_hit INT);
        CREATE TABLE company_timings(run_id TEXT,mode TEXT,latency_ms INT);
        CREATE TABLE verification_attempts(run_id TEXT,ticker TEXT,metric TEXT,attempt INT,verification_json TEXT);
    """)
    settings = load_config().model_dump()
    settings["selected_companies"] = settings["companies"]["full"] = ["ONE"]
    settings["metrics"] = {"revenue": settings["metrics"]["revenue"]}
    settings["extraction_code_sha256"] = "same-extraction"
    fact = ExtractedFact(metric="revenue", value_as_written="100", scale_as_written="units", period_end="2025-12-31",
                         source_chunk_id="c", source_quote="Revenue | 100")
    for number, run in enumerate(["first", "cache", "repair"]):
        config = json.loads(json.dumps(settings))
        if run == "repair":
            config["verifier_code_sha256"] = "new-checks"
        db.execute("INSERT INTO runs VALUES (?,?,?,?)", (run, "fixture-model", str(number), json.dumps(config)))
        db.execute("INSERT INTO run_filings VALUES (?,?,?,?)", (run, "ONE", "same-filing", "same-chunks"))
        modes = ["baseline", "verified"] if run == "first" else ["verified"]
        for mode in modes:
            value = 200 if run == "repair" else 100
            saved = FactResult(run_id=run, mode=mode, ticker="ONE", metric="revenue", fact=fact,
                               verification=None, attempts=1, status="answered", final_value=value)
            db.execute("INSERT INTO fact_results VALUES (?,?,?,?,?)", (run, mode, "ONE", "revenue", saved.model_dump_json()))
            if run != "cache":
                classification = "correct" if run == "repair" else "wrong"
                evaluated = EvaluationRow(run_id=run, mode=mode, ticker="ONE", metric="revenue", provider="fake",
                    model="fixture-model", final_value=value, ground_truth=200, ground_truth_tag="Fixture",
                    classification=classification, extraction_status="answered", source_quote=fact.source_quote)
                db.execute("INSERT INTO evaluations VALUES (?,?,?,?,?,?)", (run, mode, "ONE", "revenue", classification, evaluated.model_dump_json()))
            db.execute("INSERT INTO llm_calls VALUES (?,?,?,?,?,?,?)", (run, mode, 0 if run == "cache" else 100, 0 if run == "cache" else 10,
                                                                      0 if run == "cache" else 0.2, 0, int(run == "cache")))
            db.execute("INSERT INTO company_timings VALUES (?,?,?)", (run, mode, 10 if run == "cache" else 1000))
    failure = VerificationResult(passed=False, failed_check="V8", reason="wrong row", normalized_value=None)
    db.execute("INSERT INTO verification_attempts VALUES (?,?,?,?,?)", ("repair", "ONE", "revenue", 1, failure.model_dump_json()))
    study = select_studies(db)[0]
    assert study.baseline_run == study.first_baseline_run == study.first_verified_run == "first"
    assert study.verified_run == "repair" and study.cache_run == "cache"
    assert call_usage(db, study.first_verified_run, "verified").cost == 0.2
    assert call_usage(db, study.cache_run, "verified").cost == 0
    assert call_usage(db, study.cache_run, "verified").hit_rate == 1
    caught = caught_errors(db, study)
    assert len(caught) == 1 and caught[0].outcome == "Corrected to $200.00"
    assert "V8" in caught[0].checks and "scope" in caught[0].checks
    db.execute("UPDATE run_filings SET chunk_sha256='different-source' WHERE run_id='repair'")
    assert select_studies(db)[0].verified_run == "first"
    db.close()


def test_cloud_source_paths_accept_windows_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cloud must read the original Windows metadata without rewriting results."""
    import hashlib
    import pytest
    import app.streamlit_app as dashboard
    from dv.models import Chunk

    path = tmp_path / "data" / "processed" / "fixture.jsonl"
    path.parent.mkdir(parents=True)
    chunk = Chunk(chunk_id="c", ticker="TEST", accession="a", section="item_8", text="Revenue | 100",
                  is_table=True, detected_scale="units", scale_excludes_per_share=False)
    path.write_text(chunk.model_dump_json() + "\n", encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(dashboard, "ROOT", tmp_path)
    dashboard.load_chunks.clear()
    assert dashboard.load_chunks("data\\processed\\fixture.jsonl", digest)["c"] == chunk
    with pytest.raises(ValueError, match="outside"):
        dashboard.load_chunks("../private.jsonl", digest)
    dashboard.load_chunks.clear()

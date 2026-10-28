"""Heuristic red flags never alter verified facts or evaluation status."""
from dv.config import load_config
from dv.consistency import find_flags
from dv.models import Chunk, ExtractedFact, FactResult, FilingMetadata, VerificationResult


def test_same_year_prose_disagrees_with_table() -> None:
    filing = FilingMetadata(ticker="TEST", cik=1, accession="acc", period_of_report="2025-12-31",
                            filing_date="2026-02-01", primary_document="test.htm")
    fact = ExtractedFact(metric="revenue", value_as_written="1,000", scale_as_written="millions",
                         period_end="2025-12-31", source_chunk_id="table", source_quote="Revenue | 1,000")
    result = FactResult(run_id="r", mode="verified", ticker="TEST", metric="revenue", fact=fact,
                        verification=VerificationResult(passed=True, failed_check=None, reason=None, normalized_value=1e9),
                        attempts=1, status="answered", final_value=1e9)
    chunk = Chunk(chunk_id="prose", ticker="TEST", accession="acc", section="item_7", is_table=False,
                  text="For 2025, revenue was $1.2 billion.", detected_scale=None, scale_excludes_per_share=False)
    flags = find_flags([result], [chunk], filing, load_config())
    assert len(flags) == 1
    assert flags[0].table_value == 1e9
    assert flags[0].prose_value == 1.2e9
    assert flags[0].table_quote == "Revenue | 1,000"
    assert result.final_value == 1e9 and result.status == "answered"
    chunk.text = "For 2025, revenue was $1 billion."
    assert find_flags([result], [chunk], filing, load_config()) == []
    chunk.text = "For 2024, revenue was $1.2 billion."
    assert find_flags([result], [chunk], filing, load_config()) == []
    income = result.model_copy(update={"metric": "net_income", "fact": fact.model_copy(update={"metric": "net_income"})})
    chunk.text = "In 2025, net income per share was $1.20. Cash provided by operations was $2 billion."
    assert find_flags([income], [chunk], filing, load_config()) == []

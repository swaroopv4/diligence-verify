"""Offline regressions from the frozen filing evidence, with no XBRL inputs."""
import json
from pathlib import Path

import pytest

from dv.config import load_config
from dv.models import Chunk, DataModel, ExtractedFact, FilingMetadata, VerificationResult
from dv.table import locate_cells
from dv.verify import retry_feedback, verify


class SourceCase(DataModel):
    filing: FilingMetadata
    chunk: Chunk
    fact: ExtractedFact


def source_case(ticker: str, metric: str) -> SourceCase:
    rows = json.loads((Path(__file__).parent / "fixtures" / "phase5b_cases.json").read_text(encoding="utf-8"))
    return next(case for row in rows if (case := SourceCase.model_validate(row)).filing.ticker == ticker and case.fact.metric == metric)


def check(case: SourceCase, fact: ExtractedFact | None = None) -> VerificationResult:
    return verify(fact or case.fact, {case.chunk.chunk_id: case.chunk}, case.filing)


@pytest.mark.parametrize("ticker", ["AAPL", "AMZN", "CRM", "CSCO", "MSFT", "NVDA", "ORCL"])
def test_v5_real_null_eps_scale_uses_source_exception(ticker: str) -> None:
    case = source_case(ticker, "eps_diluted")
    assert case.fact.scale_as_written is None
    assert case.chunk.scale_excludes_per_share
    result = check(case)
    assert result.passed, result.reason
    assert result.normalized_value == float(case.fact.value_as_written)


@pytest.mark.parametrize("change", [{"scale_as_written": "millions"}, {"scale_as_written": "unspecified"}])
def test_v5_eps_conflicting_or_ambiguous_scale_still_fails(change: dict[str, str]) -> None:
    case = source_case("AAPL", "eps_diluted")
    assert check(case, case.fact.model_copy(update=change)).failed_check == "V5"


def test_v5_eps_requires_independent_units_evidence() -> None:
    case = source_case("AAPL", "eps_diluted")
    case.chunk.scale_excludes_per_share = False
    assert check(case).passed  # Visible exception is sufficient independently.
    case.chunk.text = case.chunk.text.replace("and per-share amounts", "")
    assert check(case).failed_check == "V5"
    case.chunk.detected_scale = "units"
    assert check(case).passed


def test_v5_unknown_scale_is_not_inferred_from_model() -> None:
    case = source_case("AMZN", "cash")
    assert check(case).reason == "scale unknown"


def test_v2_real_quote_separators_are_required() -> None:
    case = source_case("MSFT", "cash")
    assert check(case).failed_check == "V2"
    case.fact.source_quote = "Cash and cash equivalents |  | $ | 20,935"
    assert check(case).passed


def test_v6_real_current_and_prior_columns() -> None:
    case = source_case("AAPL", "eps_diluted")
    assert check(case).passed
    case.fact.value_as_written = "6.08"
    case.fact.source_quote = "Diluted | $ | 7.46 |  |  | $ | 6.08"
    result = check(case)
    assert result.failed_check == "V6"
    assert result.reason == "value is in column September 28, 2024, expected 2025-09-27"


def test_v6_real_ascending_columns_and_truncated_quote() -> None:
    case = source_case("AMZN", "eps_diluted")
    cells = locate_cells(case.fact, case.chunk)
    assert len(cells) == 1 and cells[0].numeric_column == 2
    assert check(case).passed
    case.fact.value_as_written = "5.53"
    case.fact.source_quote = "Diluted earnings per share | $ | 2.90 |  |  | $ | 5.53"
    assert check(case).failed_check == "V6"


def test_v6_ambiguous_equal_values_fail_closed() -> None:
    case = source_case("AAPL", "eps_diluted")
    case.chunk.text = case.chunk.text.replace("6.08", "7.46")
    case.fact.source_quote = "Diluted | $ | 7.46 |  |  | $ | 7.46"
    result = check(case)
    assert result.failed_check == "V6" and "ambiguous" in result.reason


def test_v6_real_nested_period_headers() -> None:
    case = source_case("INTU", "cash")
    assert check(case).passed
    case.fact.value_as_written = "2,884"
    case.fact.source_quote = "Cash and cash equivalents | $ | 4,705 |  |  | $ | 4,705 |  |  | $ | 2,884"
    result = check(case)
    assert result.failed_check == "V6" and "July 31, 2025 / Amortized Cost" in result.reason


@pytest.mark.parametrize("ticker,metric", [("CSCO", "stockholders_equity"), ("GOOGL", "revenue")])
def test_v8_real_equivalent_labels(ticker: str, metric: str) -> None:
    assert check(source_case(ticker, metric)).passed


def test_v6_single_period_multidimensional_cash_table() -> None:
    case = source_case("NFLX", "cash")
    cells = locate_cells(case.fact, case.chunk)
    assert len(cells) == 1 and cells[0].numeric_column == 4
    assert cells[0].header.end.isoformat() == "2025-12-31"
    assert check(case).failed_check == "V8"
    case.chunk.text = case.chunk.text.replace(" | As of December 31, 2025", " | As of December 31, 2024")
    assert check(case).failed_check == "V6"


@pytest.mark.parametrize("ticker,metric,quote,value", [
    ("INTC", "net_income", "Net income (loss) attributable to Intel |  | $ | ( 267 )", "( 267 )"),
    ("INTC", "stockholders_equity", "Total Intel stockholders' equity |  | 114,281", "114,281"),
    ("ORCL", "stockholders_equity", "Total Oracle Corporation stockholders’ equity |  |  | 42,508", "42,508"),
])
def test_v8_parent_scope_rejects_total_and_accepts_parent(ticker: str, metric: str, quote: str, value: str) -> None:
    case = source_case(ticker, metric)
    result = check(case)
    assert result.failed_check == "V8" and "Expected parent row:" in result.reason
    case.fact.source_quote, case.fact.value_as_written = quote, value
    assert check(case).passed, check(case).reason


def test_v8_cash_component_is_not_cash_and_equivalents() -> None:
    case = source_case("NFLX", "cash")
    result = check(case)
    assert result.failed_check == "V8" and "row 'Cash'" in result.reason


def test_v8_segment_prose_is_not_consolidated_operating_income() -> None:
    case = source_case("INTC", "operating_income")
    # The saved source is a one-cell layout table containing prose. Without
    # column evidence it fails V6. Also exercise V8 on the same text as prose.
    assert check(case).failed_check == "V6"
    case.chunk.is_table = False
    assert check(case).failed_check == "V8"
    case.chunk.text = "Consolidated operating income was $12.7 billion in 2025."
    case.fact.source_quote = "Consolidated operating income was $12.7 billion in 2025"
    assert check(case).passed


def test_v8_eps_denominator_and_basic_rows_fail() -> None:
    case = source_case("AAPL", "eps_diluted")
    case.fact.value_as_written = "15,004,697"
    case.fact.source_quote = "Diluted | 15,004,697"
    # Sanity precedes row-label checks; use check_row to establish the label
    # defect independently rather than weakening the sanity bound.
    from dv.verify import check_row
    cell = locate_cells(case.fact, case.chunk)[0]
    assert "share-count" in check_row(case.fact, case.chunk, cell, load_config().metrics["eps_diluted"])
    case.fact.value_as_written = "7.49"
    case.fact.source_quote = "Basic | $ | 7.49"
    assert check(case).failed_check == "V8"


def test_retry_feedback_names_source_column_and_expected_parent_row() -> None:
    case = source_case("INTC", "net_income")
    result = check(case)
    feedback = retry_feedback(result, case.fact, {case.chunk.chunk_id: case.chunk}, case.filing,
                              load_config().metrics["net_income"])
    assert "Previous answer failed V8:" in feedback
    assert "Net income (loss) attributable to Intel" in feedback
    assert "Expected fiscal column: 2025-12-27" in feedback


def test_retry_quote_feedback_preserves_actual_delimiters() -> None:
    case = source_case("MSFT", "cash")
    feedback = retry_feedback(check(case), case.fact, {case.chunk.chunk_id: case.chunk}, case.filing,
                              load_config().metrics["cash"])
    assert "Previous answer failed V2:" in feedback
    assert "Cash and cash equivalents |  | $ | 20,935" in feedback


@pytest.mark.parametrize("check_name", ["V6", "V8"])
def test_real_failed_check_feedback_can_correct_on_retry(tmp_path: Path, check_name: str) -> None:
    from dv.llm import FakeProvider, LLMClient, ProviderResponse
    from dv.pipeline import prepare_database, verified_fact
    from dv.retrieve import FilingIndex

    if check_name == "V6":
        case = source_case("AAPL", "eps_diluted")
        bad = case.fact.model_copy(update={"value_as_written": "6.08", "source_quote": "Diluted | $ | 7.46 |  |  | $ | 6.08"})
        good = case.fact
    else:
        case = source_case("INTC", "net_income")
        bad = case.fact
        good = case.fact.model_copy(update={"value_as_written": "( 267 )", "source_quote": "Net income (loss) attributable to Intel |  | $ | ( 267 )"})
    provider = FakeProvider("local", [ProviderResponse(content=f.model_dump_json(), input_tokens=10, output_tokens=10) for f in [bad, good]])
    config = load_config()
    with LLMClient(config.llm, tmp_path / "runs.db", [provider]) as client:
        prepare_database(client.db)
        result = verified_fact(client, config, "offline", case.filing.ticker, case.fact.metric, case.filing,
                               FilingIndex([case.chunk]), {})
    assert result.status == "answered" and result.attempts == 2
    assert f"Previous answer failed {check_name}:" in provider.prompts[1]
    assert "Expected fiscal column:" in provider.prompts[1]
    assert "Expected " + case.fact.metric + " row labels:" in provider.prompts[1]

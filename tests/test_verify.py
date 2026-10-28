"""Every V1–V7 check has a passing path and a first-failure case."""
import pytest

from dv.models import Chunk, ExtractedFact, FilingMetadata
from dv.verify import verify


@pytest.fixture()
def filing() -> FilingMetadata:
    return FilingMetadata(ticker="TEST", cik=1, accession="acc", period_of_report="2025-12-31",
                          filing_date="2026-02-01", primary_document="test.htm")


@pytest.fixture()
def chunk() -> Chunk:
    return Chunk(chunk_id="c", ticker="TEST", accession="acc", section="item_8",
                  text="In millions, except per-share amounts\n2025\nRevenue | 1,234\nDiluted EPS | 7.46\nCash and cash equivalents | 50\nAssets | 100",
                  is_table=True, detected_scale="millions", scale_excludes_per_share=True)


@pytest.fixture()
def fact() -> ExtractedFact:
    return ExtractedFact(metric="revenue", value_as_written="1,234", scale_as_written="in millions",
                         period_end="2025-12-31", source_chunk_id="c", source_quote="Revenue | 1,234")


def test_passing_path_reaches_every_check(fact: ExtractedFact, chunk: Chunk, filing: FilingMetadata) -> None:
    result = verify(fact, {"c": chunk}, filing)
    assert result.passed
    assert result.failed_check is None
    assert result.normalized_value == 1_234_000_000


def test_v1_missing_chunk(fact: ExtractedFact, filing: FilingMetadata) -> None:
    assert verify(fact, {}, filing).failed_check == "V1"


def test_v1_wrong_filing(fact: ExtractedFact, chunk: Chunk, filing: FilingMetadata) -> None:
    assert verify(fact, {"c": chunk.model_copy(update={"accession": "other"})}, filing).failed_check == "V1"


def test_v2_invented_quote(fact: ExtractedFact, chunk: Chunk, filing: FilingMetadata) -> None:
    assert verify(fact.model_copy(update={"source_quote": "Sales | 1,234"}), {"c": chunk}, filing).failed_check == "V2"


def test_v2_unicode_and_whitespace_normalization(fact: ExtractedFact, chunk: Chunk, filing: FilingMetadata) -> None:
    chunk.text = "2025 In millions\n‘Revenue’ —   1,234"
    chunk.is_table = False
    fact.source_quote = "'Revenue' - 1,234"
    assert verify(fact, {"c": chunk}, filing).passed


def test_v3_value_not_in_quote(fact: ExtractedFact, chunk: Chunk, filing: FilingMetadata) -> None:
    assert verify(fact.model_copy(update={"value_as_written": "999"}), {"c": chunk}, filing).failed_check == "V3"


def test_v4_unparseable_cell(fact: ExtractedFact, chunk: Chunk, filing: FilingMetadata) -> None:
    chunk.text += "\nRevenue | —"
    fact.value_as_written = "—"
    fact.source_quote = "Revenue | —"
    assert verify(fact, {"c": chunk}, filing).failed_check == "V4"


def test_v5_scale_mismatch(fact: ExtractedFact, chunk: Chunk, filing: FilingMetadata) -> None:
    assert verify(fact.model_copy(update={"scale_as_written": "billions"}), {"c": chunk}, filing).failed_check == "V5"


def test_v5_unknown_scale(fact: ExtractedFact, chunk: Chunk, filing: FilingMetadata) -> None:
    chunk.detected_scale = None
    result = verify(fact, {"c": chunk}, filing)
    assert result.failed_check == "V5"
    assert result.reason == "scale unknown"


def test_v5_explicit_word_scale_without_header(fact: ExtractedFact, chunk: Chunk, filing: FilingMetadata) -> None:
    chunk.detected_scale = None
    chunk.text = "2025 Revenue was 1.2 billion."
    chunk.is_table = False
    fact.value_as_written = "1.2"
    fact.source_quote = "Revenue was 1.2 billion."
    fact.scale_as_written = "billion"
    assert verify(fact, {"c": chunk}, filing).normalized_value == 1_200_000_000


def test_v5_eps_exception(fact: ExtractedFact, chunk: Chunk, filing: FilingMetadata) -> None:
    fact.metric = "eps_diluted"
    fact.value_as_written = "7.46"
    fact.source_quote = "Diluted EPS | 7.46"
    fact.scale_as_written = "units"
    assert verify(fact, {"c": chunk}, filing).normalized_value == 7.46
    chunk.scale_excludes_per_share = False
    chunk.text = chunk.text.replace(", except per-share amounts", "")
    assert verify(fact, {"c": chunk}, filing).failed_check == "V5"


def test_v5_rejects_scaled_eps(fact: ExtractedFact, chunk: Chunk, filing: FilingMetadata) -> None:
    fact.metric = "eps_diluted"
    fact.value_as_written = "7.46"
    fact.source_quote = "Diluted EPS | 7.46"
    assert verify(fact, {"c": chunk}, filing).failed_check == "V5"


def test_v6_missing_year(fact: ExtractedFact, chunk: Chunk, filing: FilingMetadata) -> None:
    chunk.text = chunk.text.replace("2025", "2024")
    assert verify(fact, {"c": chunk}, filing).failed_check == "V6"


def test_v6_wrong_period_even_if_comparative_year_appears(fact: ExtractedFact, chunk: Chunk, filing: FilingMetadata) -> None:
    chunk.text += "\n2024"
    fact.period_end = "2024-12-31"
    assert verify(fact, {"c": chunk}, filing).failed_check == "V6"


def test_v7_negative_revenue(fact: ExtractedFact, chunk: Chunk, filing: FilingMetadata) -> None:
    chunk.text += "\nRevenue | (1,234)"
    fact.value_as_written = "(1,234)"
    fact.source_quote = "Revenue | (1,234)"
    assert verify(fact, {"c": chunk}, filing).failed_check == "V7"


def test_v7_eps_sanity_boundary(fact: ExtractedFact, chunk: Chunk, filing: FilingMetadata) -> None:
    chunk.text += "\nDiluted EPS | 1000"
    fact.metric = "eps_diluted"
    fact.value_as_written = "1000"
    fact.source_quote = "Diluted EPS | 1000"
    fact.scale_as_written = "units"
    assert verify(fact, {"c": chunk}, filing).failed_check == "V7"


def test_v7_cash_and_assets(fact: ExtractedFact, chunk: Chunk, filing: FilingMetadata) -> None:
    fact.metric = "cash"
    fact.value_as_written = "50"
    fact.source_quote = "Cash and cash equivalents | 50"
    assert verify(fact, {"c": chunk}, filing, {"total_assets": 100_000_000}).passed
    assert verify(fact, {"c": chunk}, filing, {"total_assets": 40_000_000}).failed_check == "V7"


def test_first_failure_wins(fact: ExtractedFact, filing: FilingMetadata) -> None:
    fact.value_as_written = "nonsense"
    fact.source_quote = "invented"
    assert verify(fact, {}, filing).failed_check == "V1"

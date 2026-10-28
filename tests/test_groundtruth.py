"""Answer-key matching against a saved real SEC companyfacts response; no network."""
from datetime import timedelta
from pathlib import Path

import pytest

from dv.config import MetricSettings, load_config
from dv.groundtruth import CompanyFacts, XBRLConcept, XBRLFact, match_metric, matches
from dv.models import FilingMetadata

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def facts() -> CompanyFacts:
    return CompanyFacts.model_validate_json((FIXTURES / "AAPL_companyfacts.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def filing() -> FilingMetadata:
    return FilingMetadata.model_validate_json((FIXTURES / "AAPL_filing.json").read_text(encoding="utf-8"))


def metric(kind: str = "duration", tags: list[str] | None = None) -> MetricSettings:
    return MetricSettings.model_validate({"kind": kind, "unit": "USD", "query": "test",
                                         "xbrl_tags": tags or ["RevenueFromContractWithCustomerExcludingAssessedTax"]})


def test_real_snapshot_matches_all_nine(facts: CompanyFacts, filing: FilingMetadata) -> None:
    results = [match_metric(facts, filing, name, definition) for name, definition in load_config().metrics.items()]
    assert len(results) == 9
    assert all(result.status == "matched" for result in results)
    assert results[0].value == 416161000000


def test_tag_fallback_order(facts: CompanyFacts, filing: FilingMetadata) -> None:
    result = match_metric(facts, filing, "revenue", metric(tags=["DoesNotExist", "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"]))
    assert result.tag == "RevenueFromContractWithCustomerExcludingAssessedTax"


def test_first_matching_tag_wins(facts: CompanyFacts, filing: FilingMetadata) -> None:
    definition = metric(tags=["NetIncomeLoss", "RevenueFromContractWithCustomerExcludingAssessedTax"])
    result = match_metric(facts, filing, "test", definition)
    assert result.tag == "NetIncomeLoss"
    assert result.value == 112010000000


def test_accession_filter(facts: CompanyFacts, filing: FilingMetadata) -> None:
    result = match_metric(facts, filing.model_copy(update={"accession": "wrong-accession"}), "revenue", metric())
    assert result.value is None
    assert result.status == "no_ground_truth"


def test_end_date_filter(facts: CompanyFacts, filing: FilingMetadata) -> None:
    changed = filing.model_copy(update={"period_of_report": filing.period_of_report + timedelta(days=1)})
    assert match_metric(facts, changed, "revenue", metric()).value is None


def test_unit_must_match(facts: CompanyFacts, filing: FilingMetadata) -> None:
    definition = metric().model_copy(update={"unit": "USD/shares"})
    assert match_metric(facts, filing, "revenue", definition).value is None


@pytest.mark.parametrize(("days", "expected"), [(90, False), (349, False), (350, True), (364, True), (371, True), (380, True), (381, False)])
def test_duration_window(filing: FilingMetadata, days: int, expected: bool) -> None:
    fact = XBRLFact(val=1, accn=filing.accession, end=filing.period_of_report,
                    start=filing.period_of_report - timedelta(days=days))
    assert matches(fact, filing, metric()) is expected


def test_instant_requires_no_start(filing: FilingMetadata) -> None:
    fact = XBRLFact(val=1, accn=filing.accession, end=filing.period_of_report)
    assert matches(fact, filing, metric("instant"))
    assert not matches(fact, filing, metric("duration"))
    duration = fact.model_copy(update={"start": filing.period_of_report - timedelta(days=365)})
    assert not matches(duration, filing, metric("instant"))


def test_missing_tag_is_no_ground_truth(facts: CompanyFacts, filing: FilingMetadata) -> None:
    result = match_metric(facts, filing, "unknown", metric(tags=["DoesNotExist"]))
    assert result.status == "no_ground_truth"
    assert result.value is None


def test_duplicate_uses_first_and_warns(filing: FilingMetadata, caplog: pytest.LogCaptureFixture) -> None:
    common = {"accn": filing.accession, "end": filing.period_of_report,
              "start": filing.period_of_report - timedelta(days=365)}
    concept = XBRLConcept(units={"USD": [XBRLFact(val=11, **common), XBRLFact(val=22, **common)]})
    facts = CompanyFacts(cik=filing.cik, entityName="fixture", facts={"us-gaap": {"Test": concept}})
    result = match_metric(facts, filing, "test", metric(tags=["Test"]))
    assert result.value == 11
    assert "matches=2; using first" in caplog.text


def test_cik_mismatch_rejected(facts: CompanyFacts, filing: FilingMetadata) -> None:
    with pytest.raises(ValueError, match="does not match"):
        match_metric(facts, filing.model_copy(update={"cik": 1}), "revenue", metric())

"""SEC XBRL answer key. Import ONLY from evaluate.py; never extraction code."""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field

from dv.config import MetricSettings
from dv.models import FilingMetadata, GroundTruthResult
from dv.sec_client import SECClient

logger = logging.getLogger(__name__)


class XBRLFact(BaseModel):
    val: float = Field(allow_inf_nan=False)
    accn: str
    end: date
    start: date | None = None
    form: str | None = None


class XBRLConcept(BaseModel):
    units: dict[str, list[XBRLFact]]


class CompanyFacts(BaseModel):
    cik: int
    entityName: str
    facts: dict[str, dict[str, XBRLConcept]]


def fetch_companyfacts(client: SECClient, filing: FilingMetadata, destination: Path) -> CompanyFacts:
    payload = client.get_json(
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{filing.cik:010d}.json",
        ticker=filing.ticker, step="groundtruth_download",
    )
    facts = CompanyFacts.model_validate(payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return facts


def matches(fact: XBRLFact, filing: FilingMetadata, metric: MetricSettings) -> bool:
    if fact.accn != filing.accession or fact.end != filing.period_of_report:
        return False
    if metric.kind == "instant":
        return fact.start is None
    return fact.start is not None and 350 <= (fact.end - fact.start).days <= 380


def match_metric(facts: CompanyFacts, filing: FilingMetadata, name: str,
                 metric: MetricSettings) -> GroundTruthResult:
    if facts.cik != filing.cik:
        raise ValueError(f"Companyfacts CIK {facts.cik} does not match filing CIK {filing.cik}")
    concepts = facts.facts.get("us-gaap", {})
    for tag in metric.xbrl_tags:
        concept = concepts.get(tag)
        if concept is None:
            continue
        candidates = [fact for fact in concept.units.get(metric.unit, []) if matches(fact, filing, metric)]
        if candidates:
            if len(candidates) > 1:
                logger.warning("ticker=%s step=groundtruth_match mode=evaluation metric=%s tag=%s matches=%s; using first",
                               filing.ticker, name, tag, len(candidates))
            return GroundTruthResult(ticker=filing.ticker, metric=name, value=candidates[0].val,
                                     tag=tag, unit=metric.unit, accession=filing.accession,
                                     period_end=filing.period_of_report, status="matched")
    return GroundTruthResult(ticker=filing.ticker, metric=name, value=None, tag=None,
                             unit=metric.unit, accession=filing.accession,
                             period_end=filing.period_of_report, status="no_ground_truth")


def candidate_diagnostics(facts: CompanyFacts, name: str, metric: MetricSettings) -> list[str]:
    lines: list[str] = []
    for tag in metric.xbrl_tags:
        concept = facts.facts.get("us-gaap", {}).get(tag)
        if concept is not None:
            for unit, values in concept.units.items():
                for fact in values:
                    lines.append(f"{name} tag={tag} unit={unit} start={fact.start} end={fact.end} accn={fact.accn} form={fact.form}")
    return lines

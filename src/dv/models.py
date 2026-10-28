"""Shared structured data models."""
from typing import Literal
from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class DataModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Chunk(DataModel):
    chunk_id: str
    ticker: str
    accession: str
    section: str
    text: str
    is_table: bool
    detected_scale: Literal["units", "thousands", "millions", "billions"] | None
    scale_excludes_per_share: bool


class ExtractedFact(DataModel):
    metric: str
    value_as_written: str | None
    scale_as_written: str | None
    period_end: str | None
    source_chunk_id: str | None
    source_quote: str | None = Field(max_length=300)


class VerificationResult(DataModel):
    passed: bool
    failed_check: Literal["V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8"] | None
    reason: str | None
    normalized_value: float | None


class FactResult(DataModel):
    run_id: str
    mode: Literal["baseline", "verified"]
    ticker: str
    metric: str
    fact: ExtractedFact
    verification: VerificationResult | None
    attempts: int = Field(ge=1)
    status: Literal["answered", "unverified", "not_found", "error"]
    final_value: float | None


class LLMCall(DataModel):
    run_id: str
    mode: str
    ticker: str
    step: str
    provider: str
    model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    cache_hit: bool
    cost_actual_usd: float = Field(ge=0)
    cost_reference_usd: float = Field(ge=0)
    error: str | None = None


class FilingMetadata(DataModel):
    ticker: str
    cik: int = Field(gt=0)
    accession: str
    period_of_report: date
    filing_date: date
    primary_document: str


class GroundTruthResult(DataModel):
    ticker: str
    metric: str
    value: float | None
    tag: str | None
    unit: str
    accession: str
    period_end: date
    status: Literal["matched", "no_ground_truth"]


class ConsistencyFlag(DataModel):
    run_id: str
    ticker: str
    metric: str
    table_value: float
    prose_value: float
    table_quote: str
    prose_quote: str
    source_chunk_id: str
    reason: str


class EvaluationRow(DataModel):
    run_id: str
    mode: Literal["baseline", "verified"]
    ticker: str
    metric: str
    provider: str
    model: str
    final_value: float | None
    ground_truth: float | None
    ground_truth_tag: str | None
    classification: Literal["correct", "wrong", "unverified", "not_found", "error", "no_ground_truth"]
    extraction_status: str
    source_quote: str | None
    evaluation_error: str | None = None


class ModeSummary(DataModel):
    run_id: str
    mode: str
    model: str
    correct: int
    wrong: int
    unverified: int
    not_found: int
    error: int
    no_ground_truth: int
    total_with_ground_truth: int
    precision_on_answered: float | None
    correct_rate: float | None
    wrong_rate: float | None
    unverified_rate: float | None
    avg_seconds_per_company: float | None
    input_tokens: int
    output_tokens: int
    cost_actual_usd: float
    cost_reference_usd: float
    calls: int
    cache_hits: int
    cache_hit_rate: float | None

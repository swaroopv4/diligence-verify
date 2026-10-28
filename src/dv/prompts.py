"""Identical extraction prompt for baseline and verified attempt one."""
import json

from dv.models import Chunk, ExtractedFact, FilingMetadata


def without_titles(value: object) -> object:
    """Remove JSON Schema display labels while preserving every validation rule."""
    if isinstance(value, dict):
        return {key: without_titles(item) for key, item in value.items() if key != "title"}
    if isinstance(value, list):
        return [without_titles(item) for item in value]
    return value


def extraction_prompt(metric: str, query: str, filing: FilingMetadata, chunks: list[Chunk],
                      feedback: str | None = None) -> str:
    prompt = (
        f"Extract ONE financial fact for {filing.ticker} from its 10-K.\n"
        f"Metric: {metric}. Relevant labels: {query}.\n"
        f"Filing fiscal period end: {filing.period_of_report.isoformat()}.\n"
        "Use the column for that fiscal period end, not a comparative prior year.\n"
        "Copy value_as_written and source_quote EXACTLY from one provided chunk. "
        "Never calculate, round, sum or guess. source_quote must be at most 300 characters "
        "and must include the value. Copy a short quote spanning the metric label and value. "
        "Report the displayed scale (in millions/thousands/billions), or units for EPS. "
        "EPS per-share amounts are never multiplied by a table scale.\n"
        "If the value is absent, return metric and null for ALL other fields. "
        "Return only a JSON object matching this schema:\n"
        + json.dumps(ExtractedFact.model_json_schema(), separators=(",", ":"))
        + "\nSOURCE CHUNKS:\n"
    )
    if feedback:
        # Retries carry extra evidence. Remove redundant phrasing/schema labels
        # while keeping the first-attempt prompt byte-for-byte identical in both modes.
        prompt = (
            f"Extract {metric} ({query}) for {filing.ticker}, 10-K fiscal end {filing.period_of_report.isoformat()}.\n"
            "Use that fiscal-period column. Copy value_as_written and source_quote exactly from one chunk; "
            "quote <=300 characters including the value and metric label. Never compute, round, sum, or guess. "
            "Report the displayed scale; EPS uses units and is never scaled. "
            "If absent, return metric and null for every other field. Return JSON only. Schema:\n"
            + json.dumps(without_titles(ExtractedFact.model_json_schema()), separators=(",", ":"))
            + "\nSOURCE CHUNKS:\n"
        )
    for chunk in chunks:
        prompt += (
            f"\nCHUNK {chunk.chunk_id} section={chunk.section} table={chunk.is_table}\n"
            + chunk.text + "\nEND CHUNK\n"
        )
    if feedback:
        prompt += "\n" + feedback + "\nUse the source text to correct the failed answer; never invent a value.\n"
    return prompt

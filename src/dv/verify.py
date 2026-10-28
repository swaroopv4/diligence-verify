"""Deterministic V1–V8 evidence checks. No network, LLM, or answer-key access."""
import re
from datetime import date

from dv.config import MetricSettings, load_config
from dv.models import Chunk, ExtractedFact, FilingMetadata, VerificationResult
from dv.numbers import MULTIPLIERS, parse_detail, scale_name
from dv.table import TRANSLATION, CellEvidence, locate_cells, normalize_quote, normalized_label, per_share_exception, period_matches


def failure(check: str, reason: str) -> VerificationResult:
    return VerificationResult(passed=False, failed_check=check, reason=reason, normalized_value=None)


def contains_label(label: str, phrase: str) -> bool:
    return f" {normalized_label(phrase)} " in f" {normalized_label(label)} "


def check_row(fact: ExtractedFact, chunk: Chunk, cell: CellEvidence | None,
              rules: MetricSettings) -> str | None:
    label = cell.row_label if cell else (fact.source_quote or "").split(fact.value_as_written or "\0", 1)[0]
    expected = ", ".join(rules.row_labels)
    if not rules.row_labels or not any(contains_label(label, item) for item in rules.row_labels):
        return f"row {label!r} does not match expected {fact.metric} row labels: {expected}"
    excluded = next((item for item in rules.exclude_labels if contains_label(label, item)), None)
    if excluded:
        return f"row {label!r} contains excluded label {excluded!r}; expected {fact.metric} row: {expected}"
    if fact.metric == "eps_diluted" and cell:
        # 'Diluted' also labels share-count denominators. Keep the nearest
        # section label, rather than treating all diluted rows as EPS.
        for line in reversed(chunk.text.splitlines()[:cell.row_index]):
            parts = line.split("|")
            if len(parts) > 1 and not any(parse_detail(p.strip()) is not None for p in parts[1:] if p.strip()):
                heading = normalized_label(parts[0])
                if heading:
                    if re.search(r"shares (?:used|outstanding)|weighted average shares|per share calculation", heading):
                        return f"row {label!r} is under share-count heading {parts[0]!r}; expected diluted earnings per share"
                    break
    if fact.metric in {"net_income", "stockholders_equity"} and cell:
        labels = [line.split("|")[0].strip() for line in chunk.text.splitlines() if "|" in line]
        nci = any(re.search(r"non\s*controlling", normalized_label(item)) for item in labels)
        if nci:
            if fact.metric == "net_income":
                parent = [item for item in labels if any(contains_label(item, term) for term in rules.row_labels)
                          and "attributable to" in normalized_label(item)
                          and not any(contains_label(item, term) for term in rules.exclude_labels)]
            else:
                generic = {"total stockholders equity", "total shareholders equity", "stockholders equity", "shareholders equity", "total equity"}
                parent = [item for item in labels if normalized_label(item).startswith("total ")
                          and any(contains_label(item, term) for term in rules.row_labels)
                          and normalized_label(item) not in generic
                          and not any(contains_label(item, term) for term in rules.exclude_labels)]
            if not parent or normalized_label(label) not in {normalized_label(item) for item in parent}:
                return (f"row {label!r} does not establish parent-only {fact.metric} scope; "
                        f"noncontrolling interests are disclosed. Expected parent row: {', '.join(parent) or 'parent-attributable amount excluding noncontrolling interests'}")
    return None


def verify(fact: ExtractedFact, chunk_store: dict[str, Chunk], filing: FilingMetadata,
           known_values: dict[str, float] | None = None,
           metric_settings: MetricSettings | None = None) -> VerificationResult:
    chunk = chunk_store.get(fact.source_chunk_id or "")
    if chunk is None or chunk.ticker != filing.ticker or chunk.accession != filing.accession:
        return failure("V1", "source chunk does not exist in this filing")
    if not fact.source_quote or normalize_quote(fact.source_quote) not in normalize_quote(chunk.text):
        return failure("V2", "source quote is not an exact substring after whitespace/quote/dash normalization")
    if not fact.value_as_written or fact.value_as_written not in fact.source_quote:
        return failure("V3", "displayed value is absent from the source quote")
    parsed = parse_detail(fact.value_as_written)
    if parsed is None:
        return failure("V4", "displayed value cannot be parsed as a financial number")
    reported = scale_name(fact.scale_as_written)
    embedded = parsed.word_scale
    # A prose amount can express its scale immediately after the quoted number.
    if embedded is None:
        start = fact.source_quote.index(fact.value_as_written) + len(fact.value_as_written)
        suffix = re.match(r"\s*(thousands?|millions?|billions?|bn|k|m)\b", fact.source_quote[start:], re.I)
        if suffix:
            embedded = scale_name(suffix.group(1))
    if embedded and reported and embedded != reported:
        return failure("V5", "reported scale conflicts with the number's word scale")
    effective = embedded or reported
    if fact.metric == "eps_diluted":
        excludes_per_share = per_share_exception(chunk)
        # A missing reported scale is not a conflicting scale. The source must
        # independently establish units through an explicit per-share exception.
        if effective is None and fact.scale_as_written is None and (excludes_per_share or chunk.detected_scale == "units"):
            effective = "units"
        if effective != "units":
            return failure("V5", "EPS scale must be units; per-share amounts are never scaled")
        if chunk.detected_scale is None and not excludes_per_share:
            return failure("V5", "scale unknown")
        if chunk.detected_scale != "units" and not excludes_per_share:
            return failure("V5", "scaled table header does not exclude per-share amounts")
        normalized = parsed.value
    else:
        if chunk.detected_scale is None:
            if embedded is None:
                return failure("V5", "scale unknown")
        elif effective != chunk.detected_scale:
            return failure("V5", f"reported scale {effective!r} does not match detected scale {chunk.detected_scale!r}")
        if effective not in MULTIPLIERS:
            return failure("V5", "reported scale missing or ambiguous")
        normalized = parsed.value * MULTIPLIERS[effective]
    if not fact.period_end or re.fullmatch(r"\d{4}-\d{2}-\d{2}", fact.period_end) is None:
        return failure("V6", "period end is not an ISO fiscal date")
    try:
        period = date.fromisoformat(fact.period_end)
    except ValueError:
        return failure("V6", "period end is not a valid fiscal date")
    if period != filing.period_of_report:
        return failure("V6", "reported period end differs from the filing fiscal period end")
    cell = None
    if chunk.is_table:
        cells = locate_cells(fact, chunk)
        if len(cells) != 1:
            return failure("V6", f"value cell is missing or ambiguous ({len(cells)} matches); expected column {period.isoformat()}")
        cell = cells[0]
        if cell.header is None or not period_matches(cell.header, period):
            header = cell.header.label if cell.header else "<unresolved>"
            return failure("V6", f"value is in column {header}, expected {period.isoformat()}")
    elif re.search(rf"(?<!\d){period.year}(?!\d)", chunk.text) is None:
        return failure("V6", "fiscal year does not appear in the source chunk or table header")
    if fact.metric == "revenue" and normalized <= 0:
        return failure("V7", "revenue must be positive")
    if fact.metric == "eps_diluted" and abs(normalized) >= 1000:
        return failure("V7", "absolute diluted EPS must be below 1000")
    values = dict(known_values or {})
    values[fact.metric] = normalized
    if "cash" in values and "total_assets" in values and values["cash"] > values["total_assets"]:
        return failure("V7", "cash exceeds total assets for the same filing")
    rules = metric_settings or load_config().metrics[fact.metric]
    row_error = check_row(fact, chunk, cell, rules)
    if row_error:
        return failure("V8", row_error)
    return VerificationResult(passed=True, failed_check=None, reason=None, normalized_value=normalized)


def retry_feedback(result: VerificationResult, fact: ExtractedFact, store: dict[str, Chunk],
                   filing: FilingMetadata, rules: MetricSettings) -> str:
    """Actionable source-only correction, without changing the first prompt."""
    feedback = f"Previous answer failed {result.failed_check}: {result.reason}"
    feedback += (f"\nExpected fiscal column: {filing.period_of_report.isoformat()}. "
                 f"Expected {fact.metric} row labels: {', '.join(rules.row_labels)}. "
                 f"Excluded labels: {', '.join(rules.exclude_labels)}.")
    if result.failed_check == "V2":
        chunk = store.get(fact.source_chunk_id or "")
        if chunk and fact.value_as_written:
            rows = [line for line in chunk.text.splitlines() if fact.value_as_written in line]
            if rows:
                feedback += f"\nCopy separators literally. Source row example: {rows[0][:300]}"
    if result.failed_check == "V5":
        feedback += "\nUse a source with an explicit scale header; EPS uses units, never a table multiplier."
    return feedback

"""Conservative cell/period evidence from visible pipe tables; no answer-key access.

SEC colspan/currency layout is absent from the saved display text. Match ordered
financial cells to ordered period cells, retaining dashes as column placeholders.
When that mapping is not unique, callers must abstain rather than infer a year.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from dv.models import Chunk, DataModel, ExtractedFact
from dv.numbers import parse_detail

TRANSLATION = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
})
MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
DATE = re.compile(rf"\b{MONTH}\s+\d{{1,2}},?\s+(?:19|20)\d{{2}}\b|\b(?:19|20)\d{{2}}-\d{{2}}-\d{{2}}\b", re.I)
YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")


def normalize_quote(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(TRANSLATION)).strip()


def normalized_label(text: str) -> str:
    """Case/punctuation folding for label phrases, keeping word boundaries."""
    return re.sub(r"[^a-z0-9]+", " ", normalize_quote(text).lower()).strip()


class PeriodHeader(DataModel):
    label: str
    year: int | None
    end: date | None = None


class CellEvidence(DataModel):
    row_index: int
    cell_index: int
    numeric_column: int
    row_label: str
    row_text: str
    header: PeriodHeader | None


def numeric_cell(text: str) -> bool:
    cleaned = normalize_quote(text)
    return cleaned == "-" or parse_detail(cleaned) is not None or bool(re.fullmatch(r"[-+]?\d[\d,.]*\s*%", cleaned))


def per_share_exception(chunk: Chunk) -> bool:
    if chunk.scale_excludes_per_share:
        return True
    # Honor an explicit visible header even if the saved metadata missed it.
    # Stop at the first body row so a later footnote cannot supply the scope.
    for line in chunk.text.splitlines():
        if "|" in line and any(numeric_cell(cell) and period_header(cell) is None for cell in line.split("|")[1:] if cell.strip()):
            break
        if re.search(r"except[^\n]*(?:per[\s-]share|share amounts)", line, re.I):
            return True
    return False


def period_header(text: str) -> PeriodHeader | None:
    text = normalize_quote(text)
    match = DATE.search(text)
    if match and len(YEAR.findall(text)) == 1:
        displayed = match.group(0)
        end = None
        for fmt in ("%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y", "%Y-%m-%d"):
            try:
                end = datetime.strptime(displayed, fmt).date()
                break
            except ValueError:
                continue
        return PeriodHeader(label=text, year=int(YEAR.search(displayed).group()), end=end)
    if re.fullmatch(r"(?:19|20)\d{2}", text):
        return PeriodHeader(label=text, year=int(text))
    return None


def headers_before(lines: list[str], row_index: int) -> list[PeriodHeader]:
    """Only recognize header-shaped rows, never years mentioned in body labels."""
    result: list[PeriodHeader] = []
    for line in lines[:row_index]:
        cells = [normalize_quote(cell) for cell in line.split("|")]
        first = cells[0].lower()
        header_shaped = not first or bool(re.search(r"^(?:\(?in |\(?dollars |years? ended|fiscal year|as of|" + MONTH + r"\s+\d)", first, re.I))
        if "|" not in line:
            # Legacy/small tables may have a single period on its own line.
            parsed = period_header(line)
            if parsed and re.fullmatch(r"(?:19|20)\d{2}", normalize_quote(line)):
                result = [parsed]
            continue
        if not header_shaped:
            continue
        candidate: list[PeriodHeader] = []
        for cell in cells:
            parsed = period_header(cell)
            if parsed:
                candidate.append(parsed)
            elif re.search(r"\bchange\b|\bvs\.?\b|%", cell, re.I):
                candidate.append(PeriodHeader(label=cell, year=None))
        if any(header.year for header in candidate):
            result = candidate
        elif len(result) > 1 and not any(header.year is None for header in result):
            # E.g. INTU has two dates, each spanning Amortized Cost / Fair
            # Value. Expand only when the visible child-header sequence is an
            # exact repetition; uneven or unexplained layouts stay unresolved.
            children = [cell for cell in cells[1:] if cell]
            if children and len(children) > len(result) and len(children) % len(result) == 0:
                width = len(children) // len(result)
                pattern = children[:width]
                if all(children[i:i + width] == pattern for i in range(0, len(children), width)):
                    result = [parent.model_copy(update={"label": f"{parent.label} / {child}"})
                              for parent in result for child in pattern]
    return result


def locate_cells(fact: ExtractedFact, chunk: Chunk) -> list[CellEvidence]:
    """Locate the quoted occurrence of a complete numeric cell, not a substring.

    Quote spans constrain the occurrence even when the same amount appears in
    multiple rows. Duplicate quoted occurrences/columns remain ambiguous.
    """
    if not fact.source_quote or not fact.value_as_written:
        return []
    lines = [normalize_quote(line) for line in chunk.text.splitlines()]
    flat = " ".join(lines)
    quote, value = normalize_quote(fact.source_quote), normalize_quote(fact.value_as_written)
    spans: list[tuple[int, int]] = []
    for match in re.finditer(re.escape(quote), flat):
        for amount in re.finditer(re.escape(value), quote):
            start = match.start() + amount.start()
            spans.append((start, start + len(value)))
    candidates: list[CellEvidence] = []
    row_start = 0
    for row_index, line in enumerate(lines):
        cells = line.split("|")
        numeric = [i for i, cell in enumerate(cells) if i > 0 and numeric_cell(cell)]
        cell_start = row_start
        headers = headers_before(lines, row_index)
        for i, cell in enumerate(cells):
            if i in numeric:
                trimmed = cell.strip()
                # Currency can share a cell; parentheses/signs must match the
                # complete financial number. Never accept 26 from 126 or (26).
                expected = normalize_quote(trimmed).removeprefix("$").strip()
                supplied = value.removeprefix("$").strip()
                if expected == supplied and any(cell_start <= a and b <= cell_start + len(cell) for a, b in spans):
                    column = numeric.index(i)
                    header = None
                    if len(headers) == 1:
                        header = headers[0]
                    elif column < len(headers) and (len(numeric) == len(headers) or any(h.year is None for h in headers)):
                        header = headers[column]
                    candidates.append(CellEvidence(row_index=row_index, cell_index=i, numeric_column=column,
                        row_label=" ".join(c.strip() for c in cells[:numeric[0]] if c.strip() and c.strip() != "$"),
                        row_text=line, header=header))
            cell_start += len(cell) + 1
        row_start += len(line) + 1
    return candidates


def period_matches(header: PeriodHeader, expected: date) -> bool:
    return header.year == expected.year and (header.end is None or header.end == expected)

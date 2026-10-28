"""Table-aware chunks retaining visible headers and local scale context."""
from __future__ import annotations

import re
from collections import defaultdict

from bs4 import Tag

from dv.models import Chunk, DataModel


class DocumentBlock(DataModel):
    section: str
    text: str
    is_table: bool
    context: str = ""
    header: str = ""


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def table_rows(table: Tag) -> tuple[list[str], list[str]]:
    rows: list[str] = []
    headers: list[str] = []
    in_header = True
    for row in table.find_all("tr"):
        if row.find_parent("table") is not table:
            continue
        cells = row.find_all(["td", "th"], recursive=False)
        values: list[str] = []
        for cell in cells:
            value = normalize_space(cell.get_text(" ", strip=True))
            # SEC display tables sometimes put a negative number's parentheses in
            # separate cells. Keep the displayed signed number together.
            if value == ")" and values and re.search(r"\(\s*[\d, .]+$", values[-1]):
                values[-1] += ")"
            elif values and values[-1] == "(" and re.fullmatch(r"[\d,.]+", value):
                values[-1] += value
            else:
                values.append(value)
        if not any(values):
            continue
        text = " | ".join(values)
        rows.append(text)
        # Year-only cells belong to the header; monetary amounts start the body.
        amounts = [value for value in values if re.fullmatch(r"\(?[-$]?\s*\d[\d,]*(?:\.\d+)?\)?", value)]
        money = [value for value in amounts if not re.fullmatch(r"(?:19|20)\d{2}", value)]
        if in_header and (not money or any(cell.name == "th" for cell in cells)):
            headers.append(text)
        else:
            in_header = False
    return rows, headers


def detect_scale(header: str, context: str) -> tuple[str | None, bool]:
    text = (context + "\n" + header).lower()
    match = re.search(r"\bin\s+(thousands|millions|billions)\b", text)
    scale = match.group(1) if match else None
    if scale is None and re.search(r"\bin\s+(?:us\s*)?dollars\b", text):
        scale = "units"
    excludes = bool(re.search(r"except[^\n]*(?:per[\s-]share|share amounts)", text))
    scoped_components = re.search(
        r"(?:net income|dollars?|dollar amounts)\s+in\s+(?:thousands|millions|billions)"
        r"\s+and\s+shares\s+in\s+(?:thousands|millions|billions)", text
    )
    if scoped_components and re.search(r"earnings per share", text):
        # The scale is explicitly scoped to the numerator/share count, rather
        # than to EPS. This is the same per-share exclusion expressed by scope.
        excludes = True
    return scale, excludes


def text_pieces(text: str, size: int = 1500, overlap: int = 200) -> list[str]:
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            space = text.rfind(" ", start + size // 2, end)
            if space > start:
                end = space
        pieces.append(text[start:end].strip())
        if end == len(text):
            break
        start = end - overlap
    return [piece for piece in pieces if piece]


def table_pieces(block: DocumentBlock, limit: int = 6000) -> list[str]:
    prefix = block.context.strip()
    full = "\n".join(part for part in [prefix, block.text] if part)
    if len(full) <= limit:
        return [full]
    headers = block.header.splitlines() if block.header else []
    rows = block.text.splitlines()
    # Remove headers once; reintroduce the same exact header in every piece.
    body = rows[len(headers):] if headers and rows[:len(headers)] == headers else rows
    repeated = "\n".join(part for part in [prefix, block.header] if part)
    if len(repeated) >= limit - 1:
        raise ValueError("Table header/context exceeds the chunk size budget")
    pieces: list[str] = []
    current = repeated
    for row in body:
        if len(row) + len(repeated) + 1 > limit:
            raise ValueError("One table row exceeds the chunk size budget; cannot split it without losing columns")
        if len(current) + len(row) + 1 > limit:
            pieces.append(current)
            current = repeated
        current = "\n".join(part for part in [current, row] if part)
    if current and (not pieces or current != repeated):
        pieces.append(current)
    return pieces


def make_chunks(blocks: list[DocumentBlock], ticker: str, accession: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    counters: defaultdict[str, int] = defaultdict(int)
    for block in blocks:
        scale, excludes = detect_scale(block.header, block.context) if block.is_table else (None, False)
        pieces = table_pieces(block) if block.is_table else text_pieces(block.text)
        for text in pieces:
            n = counters[block.section]
            counters[block.section] += 1
            chunks.append(Chunk(chunk_id=f"{ticker}_{accession}_{block.section}_{n:04d}",
                                ticker=ticker, accession=accession, section=block.section,
                                text=text, is_table=block.is_table, detected_scale=scale,
                                scale_excludes_per_share=excludes))
    return chunks

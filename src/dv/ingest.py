"""Download only filing HTML, remove hidden content, and retain Item boundaries."""
from __future__ import annotations

import logging
import os
import re
from collections import deque
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString

from dv.chunk import DocumentBlock, make_chunks, normalize_space, table_rows
from dv.config import load_config, project_root
from dv.models import Chunk, FilingMetadata
from dv.sec_client import SECClient

logger = logging.getLogger(__name__)
ITEM = re.compile(r"^item\s+(\d{1,2}[a-c]?)\s*(?:[.:\-–—]\s*|$)", re.I)
MARKER = re.compile(r"^DV_TABLE_(\d+)$")


def parse_html(html: str) -> list[DocumentBlock]:
    # Inline-XBRL filings are XHTML; their XML declaration does not change HTML
    # display semantics. Strip only the declaration before using the HTML parser.
    html = re.sub(r"^\s*<\?xml[^?]*\?>", "", html, count=1)
    soup = BeautifulSoup(html, "lxml")
    for tag in list(soup.find_all(["script", "style", "head", "noscript", "ix:hidden", "ix:header"])):
        tag.decompose()
    for tag in list(soup.find_all(True)):
        if tag.attrs is None:
            continue
        style = re.sub(r"\s", "", str(tag.get("style", ""))).lower()
        if tag.has_attr("hidden") or "display:none" in style or "visibility:hidden" in style:
            tag.decompose()
    tables: list[tuple[str, str]] = []
    for table in list(soup.find_all("table")):
        if table.find_parent("table") is not None:
            continue
        rows, headers = table_rows(table)
        tables.append(("\n".join(rows), "\n".join(headers)))
        table.replace_with(NavigableString(f"\nDV_TABLE_{len(tables) - 1}\n"))
    for tag in list(soup.find_all(["div", "p", "h1", "h2", "h3", "h4", "br", "li"])):
        tag.insert_before(NavigableString("\n"))
        tag.insert_after(NavigableString("\n"))
    lines = [normalize_space(line) for line in soup.get_text(" ", strip=False).splitlines()]
    blocks: list[DocumentBlock] = []
    section = "unknown"
    paragraph: list[str] = []
    previous: deque[str] = deque(maxlen=3)

    def flush() -> None:
        if paragraph:
            blocks.append(DocumentBlock(section=section, text="\n".join(paragraph), is_table=False))
            paragraph.clear()

    for line in lines:
        if not line:
            continue
        table_match = MARKER.fullmatch(line)
        heading = ITEM.match(line) if len(line) <= 220 else None
        if heading:
            flush()
            section = "item_" + heading.group(1).lower()
            previous.clear()
            paragraph.append(line)
        elif table_match:
            flush()
            text, header = tables[int(table_match.group(1))]
            # Long narrative lines are not a table's scale header.
            context = "\n".join(line for line in previous if len(line) <= 250)
            if text:
                blocks.append(DocumentBlock(section=section, text=text, is_table=True, context=context, header=header))
        else:
            paragraph.append(line)
        if not table_match:
            previous.append(line)
    flush()
    return blocks


def download_html(filing: FilingMetadata, identity: str, path: Path, rate: float) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    os.environ["EDGAR_RATE_LIMIT_PER_SEC"] = str(max(1, int(rate)))
    from edgar import Filing, set_identity

    set_identity(identity)
    source = Filing(cik=filing.cik, company=filing.ticker, form="10-K",
                    filing_date=filing.filing_date.isoformat(), accession_no=filing.accession)
    html = source.html()  # Raw HTML only: never .xbrl(), .obj() or financials.
    if not html:
        raise ValueError(f"No filing HTML returned for {filing.ticker}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return html


def ingest_filing(ticker: str) -> list[Chunk]:
    config = load_config()
    ticker = ticker.upper()
    try:
        with SECClient(config.sec) as client:
            filing = client.latest_filing(ticker)
            raw = project_root() / "data" / "raw"
            raw.mkdir(parents=True, exist_ok=True)
            (raw / f"{ticker}_filing.json").write_text(filing.model_dump_json(indent=2), encoding="utf-8")
            html = download_html(filing, client.user_agent, raw / f"{ticker}_{filing.accession}.html",
                                 config.sec.max_requests_per_second)
        blocks = parse_html(html)
        sections = {block.section for block in blocks}
        if not {"item_7", "item_8"} <= sections:
            # EdgarTools' section helper exposes HTML/text passages, not XBRL.
            from edgar import Filing
            source = Filing(cik=filing.cik, company=ticker, form="10-K",
                            filing_date=filing.filing_date.isoformat(), accession_no=filing.accession)
            passages = source.sections()
            fallback = parse_html("<div>" + "</div><div>".join(passages) + "</div>") if passages else []
            if {"item_7", "item_8"} <= {block.section for block in fallback}:
                logger.warning("ticker=%s step=sections mode=ingest fallback=edgartools", ticker)
                blocks = fallback
            else:
                logger.warning("ticker=%s step=sections mode=ingest fallback=whole_document_unknown", ticker)
                for block in blocks:
                    block.section = "unknown"
        chunks = make_chunks(blocks, ticker, filing.accession)
        destination = project_root() / "data" / "processed" / f"{ticker}_{filing.accession}.jsonl"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("\n".join(chunk.model_dump_json() for chunk in chunks) + "\n", encoding="utf-8")
        return chunks
    except Exception:
        logger.exception("ticker=%s step=ingest mode=ingest", ticker)
        raise

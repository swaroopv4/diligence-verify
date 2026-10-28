"""Table layout, section provenance, limits and scale context stay deterministic."""
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from dv.chunk import DocumentBlock, detect_scale, make_chunks, table_pieces, table_rows, text_pieces
from dv.ingest import parse_html


def test_table_conversion_retains_rows_and_columns() -> None:
    soup = BeautifulSoup("<table><tr><th>Year</th><th>2025</th></tr><tr><td>Revenue</td><td>$1,234</td></tr></table>", "lxml")
    rows, headers = table_rows(soup.table)
    assert rows == ["Year | 2025", "Revenue | $1,234"]
    assert headers == ["Year | 2025"]


def test_realistic_html_fixture() -> None:
    html = (Path(__file__).parent / "fixtures" / "filing_small.html").read_text(encoding="utf-8")
    blocks = parse_html(html)
    assert {"item_1", "item_1a", "item_7", "item_7a", "item_8"} <= {block.section for block in blocks}
    chunks = make_chunks(blocks, "TEST", "0001")
    table = next(chunk for chunk in chunks if chunk.is_table)
    assert table.section == "item_8"
    assert table.detected_scale == "millions"
    assert table.scale_excludes_per_share is True
    assert "Hidden" not in "\n".join(chunk.text for chunk in chunks)
    assert "Revenue | $1,234 | $1,100" in table.text
    assert "in millions" in table.text


def test_negative_parentheses_in_separate_display_cells() -> None:
    soup = BeautifulSoup("<table><tr><td>Loss</td><td>( 3,284</td><td>)</td></tr><tr><td>Loss</td><td>(</td><td>42</td><td>)</td></tr></table>", "lxml")
    rows, _ = table_rows(soup.table)
    assert rows == ["Loss | ( 3,284)", "Loss | (42)"]


def test_chunk_ids_are_unique_and_stable() -> None:
    blocks = [DocumentBlock(section="item_8", text="x " * 2000, is_table=False)]
    chunks = make_chunks(blocks, "TEST", "acc")
    assert [chunk.chunk_id for chunk in chunks] == [f"TEST_acc_item_8_{i:04d}" for i in range(len(chunks))]
    assert len(set(chunk.chunk_id for chunk in chunks)) == len(chunks)


@pytest.mark.parametrize(("text", "scale", "excludes"), [
    ("in thousands", "thousands", False),
    ("(In millions, except per share amounts)", "millions", True),
    ("in billions, except per-share amounts", "billions", True),
    ("in dollars", "units", False), ("2025 2024", None, False),
])
def test_scale_detection(text: str, scale: str | None, excludes: bool) -> None:
    assert detect_scale(text, "") == (scale, excludes)


def test_scale_uses_three_line_context() -> None:
    assert detect_scale("Year | 2025 | 2024", "Statement\nIn millions\nYear ended") == ("millions", False)


def test_long_real_filing_per_share_exception() -> None:
    header = "(In millions, except number of shares, which are reflected in thousands, and per-share amounts)"
    assert detect_scale(header, "") == ("millions", True)


def test_scoped_eps_computation_header() -> None:
    context = "Note 3 - Earnings Per Share\nThe computation of diluted earnings per share (net income in millions and shares in thousands):"
    assert detect_scale("2025 | 2024", context) == ("millions", True)


def test_long_table_repeats_headers_without_losing_rows() -> None:
    header = "Year | 2025 | 2024"
    rows = [f"Metric {i:04d} | 12,345 | 10,000" for i in range(800)]
    block = DocumentBlock(section="item_8", is_table=True, context="in millions",
                          header=header, text="\n".join([header] + rows))
    pieces = table_pieces(block)
    assert len(pieces) > 1
    assert all(piece.startswith("in millions\n" + header) for piece in pieces)
    assert all(len(piece) <= 6000 for piece in pieces)
    recovered = [line for piece in pieces for line in piece.splitlines()[2:]]
    assert recovered == rows


def test_oversized_row_fails_explicitly() -> None:
    block = DocumentBlock(section="item_8", is_table=True, text="x" * 9000)
    with pytest.raises(ValueError, match="One table row"):
        table_pieces(block)


def test_text_chunks_overlap_and_preserve_end() -> None:
    text = " ".join(f"word{i}" for i in range(1000))
    pieces = text_pieces(text)
    assert all(len(piece) <= 1500 for piece in pieces)
    assert pieces[0].startswith("word0")
    assert pieces[-1].endswith("word999")
    assert pieces[0][-180:] in pieces[1]

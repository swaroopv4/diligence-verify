"""Ranking gates use visible fixture text only."""
from pathlib import Path

from dv.chunk import make_chunks
from dv.ingest import parse_html
from dv.models import Chunk
from dv.retrieve import FilingIndex


def test_financial_metric_ranks_statement_table_first() -> None:
    html = (Path(__file__).parent / "fixtures" / "filing_small.html").read_text(encoding="utf-8")
    chunks = make_chunks(parse_html(html), "TEST", "acc")
    found = FilingIndex(chunks).retrieve("total revenue sales", 1)
    assert len(found) == 1
    assert found[0].section == "item_8"
    assert found[0].is_table
    assert "$1,234" in found[0].text


def test_item8_table_boost_breaks_identical_text_tie() -> None:
    template = dict(ticker="TEST", accession="acc", text="total revenue sales amount", detected_scale=None,
                    scale_excludes_per_share=False)
    chunks = [Chunk(chunk_id="prose", section="item_7", is_table=False, **template),
              Chunk(chunk_id="table", section="item_8", is_table=True, **template),
              Chunk(chunk_id="other", section="item_1", is_table=False,
                    **{**template, "text": "business products people industry"})]
    assert FilingIndex(chunks).retrieve("revenue", 1)[0].chunk_id == "table"


def test_retry_offset_returns_new_chunks() -> None:
    html = (Path(__file__).parent / "fixtures" / "filing_small.html").read_text(encoding="utf-8")
    index = FilingIndex(make_chunks(parse_html(html), "TEST", "acc"))
    first = index.retrieve("revenue", 2)
    extra = index.retrieve("revenue", 2, offset=2)
    assert not {chunk.chunk_id for chunk in first} & {chunk.chunk_id for chunk in extra}


def test_empty_index_is_safe() -> None:
    assert FilingIndex([]).retrieve("revenue", 5) == []

"""BM25 retrieval over visible filing chunks, with an Item 8 table boost."""
import re

from rank_bm25 import BM25Plus

from dv.models import Chunk


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class FilingIndex:
    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self.index = BM25Plus([tokenize(chunk.text) for chunk in chunks]) if chunks else None

    def retrieve(self, query: str, top_k: int, *, offset: int = 0) -> list[Chunk]:
        if self.index is None:
            return []
        scores = self.index.get_scores(tokenize(query))
        ranked = sorted(
            enumerate(self.chunks),
            key=lambda pair: (float(scores[pair[0]]) * (1.5 if pair[1].section == "item_8" and pair[1].is_table else 1),
                              -pair[0]),
            reverse=True,
        )
        return [chunk for _, chunk in ranked[offset:offset + top_k]]

"""Optional deterministic Item 7 versus verified-table discrepancy flags."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import sqlite3

from dv.config import AppConfig, project_root
from dv.models import Chunk, ConsistencyFlag, FactResult, FilingMetadata
from dv.numbers import normalize_baseline

logger = logging.getLogger(__name__)
LABELS = {
    "revenue": r"(?:total revenues?|revenues?|net sales)",
    "net_income": r"(?:net income|net earnings)(?!\s+per share)",
    "operating_income": r"(?:operating income|income from operations)",
    "operating_cash_flow": r"(?:cash (?:provided by|from) operating activities)",
    "eps_diluted": r"(?:diluted (?:earnings|net income) per share|diluted EPS)",
    "total_assets": r"total assets",
    "total_liabilities": r"total liabilities",
    "cash": r"cash and cash equivalents",
    "stockholders_equity": r"(?:stockholders|shareholders)[’']? equity",
}
AMOUNT = re.compile(r"\(?[-−]?\$?\s*\d[\d,]*(?:\.\d+)?\)?\s*(?:thousands?|millions?|billions?|bn|k|m)\b", re.I)
EPS_AMOUNT = re.compile(r"\$[-−]?\s*\d[\d,]*\.\d+")
BOUNDARY = re.compile(r"\.(?!\d)|[!?•\n]")


def find_flags(results: list[FactResult], chunks: list[Chunk], filing: FilingMetadata,
               config: AppConfig) -> list[ConsistencyFlag]:
    flags: list[ConsistencyFlag] = []
    seen: set[tuple[str, str]] = set()
    for result in results:
        if result.mode != "verified" or result.status != "answered" or result.final_value is None:
            continue
        if not result.verification or not result.verification.passed:
            continue
        label = LABELS.get(result.metric)
        if not label:
            continue
        for chunk in chunks:
            if chunk.section != "item_7" or chunk.is_table:
                continue
            for match in re.finditer(label, chunk.text, re.I):
                left = list(BOUNDARY.finditer(chunk.text, 0, match.start()))
                right = BOUNDARY.search(chunk.text, match.end())
                start = max(left[-1].end() if left else 0, match.start() - 100)
                end = min(right.end() if right else len(chunk.text), start + 300)
                quote = chunk.text[start:end].strip()
                if str(filing.period_of_report.year) not in quote:
                    continue
                amounts = EPS_AMOUNT if result.metric == "eps_diluted" else AMOUNT
                # Use the nearest amount following the label in this sentence;
                # do not flag comparative prior-year amounts or adjacent metrics.
                relative_label_end = max(0, match.end() - start)
                nearest = amounts.search(quote, relative_label_end)
                for amount in ([nearest] if nearest else []):
                    value = normalize_baseline(amount.group(), None, result.metric)
                    if value is None:
                        continue
                    tolerance = config.verification
                    close = math.isclose(value, result.final_value,
                                         rel_tol=0 if result.metric == "eps_diluted" else tolerance.relative_tolerance,
                                         abs_tol=tolerance.eps_absolute_tolerance if result.metric == "eps_diluted" else 0)
                    key = (result.metric, quote)
                    if not close and key not in seen:
                        seen.add(key)
                        flags.append(ConsistencyFlag(run_id=result.run_id, ticker=result.ticker, metric=result.metric,
                                     table_value=result.final_value, prose_value=value,
                                     table_quote=result.fact.source_quote or "", prose_quote=quote,
                                     source_chunk_id=chunk.chunk_id,
                                     reason="Nearby same-year prose amount differs from the verified table; review scope/rounding"))
    return flags


def scan_run(run_id: str) -> list[ConsistencyFlag]:
    flags: list[ConsistencyFlag] = []
    with sqlite3.connect(project_root() / "data" / "runs.db") as db:
        db.row_factory = sqlite3.Row
        run = db.execute("SELECT settings_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None:
            raise ValueError(f"Unknown run {run_id}")
        saved = json.loads(run["settings_json"])
        config = AppConfig.model_validate({key: saved[key] for key in AppConfig.model_fields})
        db.execute("""CREATE TABLE IF NOT EXISTS consistency_flags (
            run_id TEXT NOT NULL, ticker TEXT NOT NULL, metric TEXT NOT NULL,
            flag_json TEXT NOT NULL, UNIQUE (run_id, ticker, metric, flag_json)
        )""")
        for record in db.execute("SELECT * FROM run_filings WHERE run_id=?", (run_id,)).fetchall():
            ticker = record["ticker"]
            try:
                path = project_root() / record["chunk_path"]
                content = path.read_bytes()
                if hashlib.sha256(content).hexdigest() != record["chunk_sha256"]:
                    raise ValueError("Source chunk snapshot hash mismatch")
                chunks = [Chunk.model_validate_json(line) for line in content.decode("utf-8").splitlines() if line]
                filing = FilingMetadata.model_validate_json(record["filing_json"])
                results = [FactResult.model_validate_json(row["result_json"]) for row in db.execute(
                    "SELECT result_json FROM fact_results WHERE run_id=? AND ticker=? AND mode='verified'", (run_id, ticker))]
                for flag in find_flags(results, chunks, filing, config):
                    db.execute("INSERT OR IGNORE INTO consistency_flags VALUES (?, ?, ?, ?)",
                               (run_id, ticker, flag.metric, flag.model_dump_json()))
                    flags.append(flag)
                db.commit()
            except Exception:
                logger.exception("ticker=%s step=consistency mode=verified run_id=%s", ticker, run_id)
                raise
    return flags

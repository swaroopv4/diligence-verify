"""Resumable, pinned-model financial extraction from visible filing chunks only."""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Literal

from dv.config import AppConfig, load_config, project_root
from dv.extract import extract_fact
from dv.ingest import ingest_filing
from dv.llm import AllProvidersFailed, CallContext, LLMClient
from dv.models import Chunk, ExtractedFact, FactResult, FilingMetadata
from dv.numbers import normalize_baseline
from dv.retrieve import FilingIndex
from dv.verify import retry_feedback, verify

logger = logging.getLogger(__name__)


def prepare_database(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY, provider TEXT NOT NULL, model TEXT NOT NULL,
            config_hash TEXT NOT NULL, settings_json TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS run_filings (
            run_id TEXT NOT NULL, ticker TEXT NOT NULL, filing_json TEXT NOT NULL,
            chunk_path TEXT NOT NULL, chunk_sha256 TEXT NOT NULL,
            PRIMARY KEY (run_id, ticker)
        );
        CREATE TABLE IF NOT EXISTS fact_results (
            run_id TEXT NOT NULL, mode TEXT NOT NULL, ticker TEXT NOT NULL,
            metric TEXT NOT NULL, status TEXT NOT NULL, final_value REAL,
            attempts INTEGER NOT NULL, result_json TEXT NOT NULL,
            PRIMARY KEY (run_id, ticker, metric, mode)
        );
        CREATE TABLE IF NOT EXISTS company_timings (
            run_id TEXT NOT NULL, ticker TEXT NOT NULL, mode TEXT NOT NULL,
            latency_ms INTEGER NOT NULL, PRIMARY KEY (run_id, ticker, mode)
        );
        CREATE TABLE IF NOT EXISTS verification_attempts (
            run_id TEXT NOT NULL, ticker TEXT NOT NULL, metric TEXT NOT NULL,
            attempt INTEGER NOT NULL, fact_json TEXT NOT NULL,
            verification_json TEXT NOT NULL,
            PRIMARY KEY (run_id, ticker, metric, attempt)
        );
    """)
    db.commit()


def save_result(db: sqlite3.Connection, result: FactResult) -> None:
    db.execute("INSERT INTO fact_results VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
               (result.run_id, result.mode, result.ticker, result.metric, result.status,
                result.final_value, result.attempts, result.model_dump_json()))
    db.commit()


def empty_fact(metric: str) -> ExtractedFact:
    return ExtractedFact(metric=metric, value_as_written=None, scale_as_written=None,
                         period_end=None, source_chunk_id=None, source_quote=None)


def load_filing(db: sqlite3.Connection, run_id: str, ticker: str) -> tuple[FilingMetadata, list[Chunk]]:
    saved = db.execute("SELECT * FROM run_filings WHERE run_id=? AND ticker=?", (run_id, ticker)).fetchone()
    if saved is None:
        raw_metadata = project_root() / "data" / "raw" / f"{ticker}_filing.json"
        if not raw_metadata.exists():
            ingest_filing(ticker)
        filing = FilingMetadata.model_validate_json(raw_metadata.read_text(encoding="utf-8"))
        path = project_root() / "data" / "processed" / f"{ticker}_{filing.accession}.jsonl"
        if not path.exists():
            ingest_filing(ticker)
            filing = FilingMetadata.model_validate_json(raw_metadata.read_text(encoding="utf-8"))
            path = project_root() / "data" / "processed" / f"{ticker}_{filing.accession}.jsonl"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        snapshot_path = path.with_name(f"{path.stem}_{digest[:12]}.jsonl")
        if not snapshot_path.exists():
            snapshot_path.write_bytes(path.read_bytes())
        if hashlib.sha256(snapshot_path.read_bytes()).hexdigest() != digest:
            raise ValueError("Immutable source snapshot hash mismatch")
        path = snapshot_path
        db.execute("INSERT INTO run_filings VALUES (?, ?, ?, ?, ?)",
                   (run_id, ticker, filing.model_dump_json(), str(path.relative_to(project_root())), digest))
        db.commit()
    else:
        filing = FilingMetadata.model_validate_json(saved["filing_json"])
        path = project_root() / saved["chunk_path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != saved["chunk_sha256"]:
            raise ValueError(f"Source chunks changed since run {run_id} was created")
    chunks = [Chunk.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if not chunks or len({chunk.chunk_id for chunk in chunks}) != len(chunks):
        raise ValueError("Filing must contain nonempty chunks with unique ids")
    if any(chunk.ticker != ticker or chunk.accession != filing.accession for chunk in chunks):
        raise ValueError("Chunk provenance does not match the selected filing")
    return filing, chunks


def baseline_fact(client: LLMClient, config: AppConfig, run_id: str, ticker: str,
                  metric: str, filing: FilingMetadata, index: FilingIndex) -> FactResult:
    definition = config.metrics[metric]
    chunks = index.retrieve(definition.query, config.retrieval.top_k)
    context = CallContext(run_id=run_id, mode="baseline", ticker=ticker, step=metric)
    fact = extract_fact(client, context, metric, definition.query, filing, chunks)
    value = normalize_baseline(fact.value_as_written, fact.scale_as_written, metric)
    return FactResult(run_id=run_id, mode="baseline", ticker=ticker, metric=metric,
                      fact=fact, verification=None, attempts=1,
                      status="not_found" if fact.value_as_written is None else "answered", final_value=value)


def verified_fact(client: LLMClient, config: AppConfig, run_id: str, ticker: str,
                  metric: str, filing: FilingMetadata, index: FilingIndex,
                  known_values: dict[str, float]) -> FactResult:
    definition = config.metrics[metric]
    chunks = index.retrieve(definition.query, config.retrieval.top_k)
    store = {chunk.chunk_id: chunk for chunk in index.chunks}
    feedback = None
    last_verification = None
    for attempt in range(1, 2 + config.verification.max_retries):
        context = CallContext(run_id=run_id, mode="verified", ticker=ticker, step=metric)
        fact = extract_fact(client, context, metric, definition.query, filing, chunks, feedback)
        if fact.value_as_written is None:
            return FactResult(run_id=run_id, mode="verified", ticker=ticker, metric=metric,
                              fact=fact, verification=None, attempts=attempt, status="not_found", final_value=None)
        last_verification = verify(fact, store, filing, known_values, definition)
        client.db.execute("INSERT OR REPLACE INTO verification_attempts VALUES (?, ?, ?, ?, ?, ?)",
                          (run_id, ticker, metric, attempt, fact.model_dump_json(), last_verification.model_dump_json()))
        client.db.commit()
        if last_verification.passed:
            return FactResult(run_id=run_id, mode="verified", ticker=ticker, metric=metric,
                              fact=fact, verification=last_verification, attempts=attempt,
                              status="answered", final_value=last_verification.normalized_value)
        logger.warning("ticker=%s step=%s mode=verified attempt=%s failed_check=%s reason=%s",
                       ticker, metric, attempt, last_verification.failed_check, last_verification.reason)
        feedback = retry_feedback(last_verification, fact, store, filing, definition)
        if attempt < 1 + config.verification.max_retries:
            chunks += index.retrieve(definition.query, config.retrieval.retry_extra_k, offset=len(chunks))
    return FactResult(run_id=run_id, mode="verified", ticker=ticker, metric=metric, fact=fact,
                      verification=last_verification, attempts=attempt, status="unverified", final_value=None)


def run_extraction(run_id: str, mode: Literal["baseline", "verified"], companies: str,
                   model: str | None = None) -> list[FactResult]:
    config = load_config()
    if companies not in {"dev", "full"}:
        raise ValueError("companies must be dev or full")
    tickers = getattr(config.companies, companies)
    if model:
        active = [entry for entry in config.llm.providers if not entry.model.startswith("FILL_IN")]
        if len(active) != 1:
            raise ValueError("--model requires exactly one configured provider")
        active[0].model = model
    with LLMClient(config.llm, project_root() / "data" / "runs.db") as client:
        if not client.providers:
            raise AllProvidersFailed("No provider configured")
        prepare_database(client.db)
        snapshot = config.model_dump()
        for entry in snapshot["llm"]["providers"]:
            if entry.get("thinking_level") is None:
                entry.pop("thinking_level",None)
        snapshot["selected_companies"] = tickers
        source = Path(__file__).parent
        snapshot["extraction_code_sha256"] = hashlib.sha256(b"".join(
            (source / name).read_bytes() for name in ("retrieve.py", "prompts.py", "extract.py", "numbers.py")
        )).hexdigest()
        snapshot["verifier_code_sha256"] = hashlib.sha256(b"".join(
            (source / name).read_bytes() for name in ("verify.py", "table.py", "pipeline.py")
        )).hexdigest()
        serialized = json.dumps(snapshot, sort_keys=True)
        digest = hashlib.sha256(serialized.encode()).hexdigest()
        existing = client.db.execute("SELECT config_hash FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if existing and existing["config_hash"] != digest:
            raise ValueError("Run settings changed; use a new run_id to preserve the comparison")
        client.db.execute("INSERT OR IGNORE INTO runs VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                          (run_id, client.providers[0].name, client.providers[0].model, digest, serialized))
        client.db.commit()
        for ticker in tickers:
            missing = [metric for metric in config.metrics if not client.db.execute(
                "SELECT 1 FROM fact_results WHERE run_id=? AND ticker=? AND metric=? AND mode=?",
                (run_id, ticker, metric, mode)).fetchone()]
            if not missing:
                continue
            started = time.perf_counter()
            try:
                filing, chunks = load_filing(client.db, run_id, ticker)
                index = FilingIndex(chunks)
                known_values: dict[str, float] = {}
                if mode == "verified":
                    for row in client.db.execute("SELECT result_json FROM fact_results WHERE run_id=? AND ticker=? AND mode='verified'",
                                                 (run_id, ticker)).fetchall():
                        saved = FactResult.model_validate_json(row["result_json"])
                        if saved.status == "answered" and saved.verification and saved.verification.passed and saved.final_value is not None:
                            known_values[saved.metric] = saved.final_value
                for metric in missing:
                    try:
                        if mode == "baseline":
                            result = baseline_fact(client, config, run_id, ticker, metric, filing, index)
                        else:
                            result = verified_fact(client, config, run_id, ticker, metric, filing, index, known_values)
                    except AllProvidersFailed:
                        raise
                    except Exception:
                        logger.exception("ticker=%s step=%s mode=%s", ticker, metric, mode)
                        result = FactResult(run_id=run_id, mode=mode, ticker=ticker, metric=metric,
                                            fact=empty_fact(metric), verification=None, attempts=1,
                                            status="error", final_value=None)
                    save_result(client.db, result)
                    if result.status == "answered" and result.final_value is not None:
                        known_values[metric] = result.final_value
                    logger.info("ticker=%s step=%s mode=%s status=%s value=%s",
                                ticker, metric, mode, result.status, result.final_value)
                    if result.status == "not_found":
                        logger.info("ticker=%s step=%s mode=%s retrieved_chunks=%s", ticker, metric, mode,
                                    [chunk.chunk_id for chunk in index.retrieve(config.metrics[metric].query, config.retrieval.top_k)])
            except Exception:
                logger.exception("ticker=%s step=company mode=%s", ticker, mode)
                for metric in missing:
                    if not client.db.execute("SELECT 1 FROM fact_results WHERE run_id=? AND ticker=? AND metric=? AND mode=?",
                                             (run_id, ticker, metric, mode)).fetchone():
                        save_result(client.db, FactResult(run_id=run_id, mode=mode, ticker=ticker, metric=metric,
                                    fact=empty_fact(metric), verification=None, attempts=1, status="error", final_value=None))
            elapsed = max(0, int((time.perf_counter() - started) * 1000))
            client.db.execute("""INSERT INTO company_timings VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id,ticker,mode) DO UPDATE SET latency_ms=latency_ms+excluded.latency_ms""",
                              (run_id, ticker, mode, elapsed))
            client.db.commit()
        rows = client.db.execute("SELECT result_json FROM fact_results WHERE run_id=? AND mode=? ORDER BY ticker,metric",
                                 (run_id, mode)).fetchall()
        return [FactResult.model_validate_json(row["result_json"]) for row in rows]

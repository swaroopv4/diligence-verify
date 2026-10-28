"""Measure the unchanged final pipeline with isolated fresh caches.

Nothing is promoted to the dashboard database until both cold-mode accuracy
checks pass. A mismatch is an explicit user-requested stop, never a tuning loop.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from dv.config import LLMSettings, load_config, project_root
from dv.llm import CallContext, CompatibleProvider, LLMClient, ProviderResponse
from dv.models import DataModel, EvaluationRow
from dv.report import format_cost, format_seconds

Output = TypeVar("Output", bound=BaseModel)
ROOT = project_root()
MODEL = "gemini-3.5-flash-lite"


class PacedProvider(CompatibleProvider):
    """Pace live requests below the observed free-tier minute cap."""

    def __init__(self, settings: LLMSettings, interval: float) -> None:
        active = [entry for entry in settings.providers if not entry.model.startswith("FILL_IN")]
        if len(active) != 1 or active[0].model != MODEL:
            raise ValueError("The cold benchmark requires exactly the requested pinned model")
        super().__init__(active[0], settings.timeout_seconds)
        self.interval = interval
        self.last_started = 0.0

    def complete(self, prompt: str, *, temperature: int, max_tokens: int) -> ProviderResponse:
        delay = self.interval - (time.monotonic() - self.last_started)
        if delay > 0:
            time.sleep(delay)
        self.last_started = time.monotonic()
        return super().complete(prompt, temperature=temperature, max_tokens=max_tokens)


class MeasuredClient(LLMClient):
    def __init__(self, settings: LLMSettings, path: Path, *, interval: float = 5.0, allow_network: bool = True) -> None:
        self.allow_network = allow_network
        provider = PacedProvider(settings, interval) if allow_network else CacheOnlyProvider(settings)
        super().__init__(settings, path, [provider])
        self.attempts: defaultdict[tuple[str, str, str, str], int] = defaultdict(int)
        self.db.execute("""CREATE TABLE IF NOT EXISTS benchmark_request_identity (
            run_id TEXT,mode TEXT,ticker TEXT,metric TEXT,extraction_attempt INTEGER,
            prompt_sha256 TEXT,cache_key TEXT,
            PRIMARY KEY(run_id,mode,ticker,metric,extraction_attempt))""")
        self.db.commit()

    def complete(self, prompt: str, schema: type[Output], context: CallContext,
                 *, pin_model: bool = False) -> Output:
        key = (context.run_id, context.mode, context.ticker, context.step)
        self.attempts[key] += 1
        attempt = self.attempts[key]
        cache_key = self.cache_key(self.providers[0], prompt, schema)
        if not self.allow_network and not self.db.execute("SELECT 1 FROM llm_cache WHERE cache_key=?", (cache_key,)).fetchone():
            raise RuntimeError("Cached replay has no matching response; live requests are prohibited")
        self.db.execute("INSERT INTO benchmark_request_identity VALUES (?,?,?,?,?,?,?)",
            (*key, attempt, hashlib.sha256(prompt.encode()).hexdigest(), self.cache_key(self.providers[0], prompt, schema)))
        self.db.commit()
        measured = context.model_copy(update={"step": f"{context.step}.attempt_{attempt}"})
        return super().complete(prompt, schema, measured, pin_model=pin_model)


class CacheOnlyProvider:
    """Identical cache identity; no client or network endpoint is opened."""

    def __init__(self, settings: LLMSettings) -> None:
        active = next(entry for entry in settings.providers if not entry.model.startswith("FILL_IN"))
        self.name, self.model, self.base_url = active.name, active.model, active.base_url
        self.thinking_level = active.thinking_level

    def complete(self, prompt: str, *, temperature: int, max_tokens: int) -> ProviderResponse:
        raise AssertionError("A cached replay must never call a model")

    def close(self) -> None:
        pass


class Difference(DataModel):
    ticker: str
    metric: str
    previous_classification: str
    cold_classification: str
    previous_value: float | None
    cold_value: float | None
    ground_truth: float | None
    quote: str | None


def reference_rows(mode: str) -> tuple[str, list[EvaluationRow]]:
    from app.streamlit_app import select_studies
    from dv.report import read_database

    with read_database() as db:
        study = next(study for study in select_studies(db) if study.model == MODEL)
        run = study.verified_run if mode == "verified" else study.baseline_run
        rows = [EvaluationRow.model_validate_json(row[0]) for row in db.execute(
            "SELECT result_json FROM evaluations WHERE run_id=? AND mode=? ORDER BY ticker,metric", (run, mode))]
    return run, rows


def evaluate_isolated(folder: Path, run_id: str) -> list[EvaluationRow]:
    import dv.evaluate as evaluator

    raw = folder / "data" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for ticker in load_config().companies.full:
        source = ROOT / "data" / "raw" / f"{ticker}_companyfacts.json"
        if not source.exists():
            raise FileNotFoundError(f"Independent saved evaluation data missing: {ticker}")
        shutil.copyfile(source, raw / source.name)
    original = evaluator.project_root
    try:
        evaluator.project_root = lambda: folder
        return evaluator.evaluate_stored_run(run_id)
    finally:
        evaluator.project_root = original


def cold_mode(mode: str) -> tuple[Path, str, list[EvaluationRow], list[Difference]]:
    import dv.pipeline as pipeline

    reference_run, previous = reference_rows(mode)
    run_id = f"cold-final-{mode}-v1"
    folder = ROOT / ".deploy-check" / "benchmarks" / run_id
    path = folder / "data" / "runs.db"
    if path.exists():
        raise FileExistsError(f"Refusing to call a pre-existing cache cold: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Pre-assert an empty cache without touching the original research database.
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE benchmark_runs (
            run_id TEXT PRIMARY KEY,mode TEXT,kind TEXT,initial_cache_entries INTEGER,
            reference_run TEXT,model TEXT,request_interval_seconds REAL)""")
        db.execute("INSERT INTO benchmark_runs VALUES (?,?,?,?,?,?,?)",
                   (run_id, mode, "cold", 0, reference_run, MODEL, 5.0))
    original = pipeline.LLMClient

    def client_factory(settings: LLMSettings, unused_path: Path) -> MeasuredClient:
        return MeasuredClient(settings, path)

    try:
        pipeline.LLMClient = client_factory
        pipeline.run_extraction(run_id, mode, "full", model=MODEL)
    finally:
        pipeline.LLMClient = original
    evaluated = evaluate_isolated(folder, run_id)
    current = {(row.ticker, row.metric): row for row in previous}
    differences = [Difference(ticker=row.ticker, metric=row.metric,
        previous_classification=current[(row.ticker, row.metric)].classification,
        cold_classification=row.classification, previous_value=current[(row.ticker, row.metric)].final_value,
        cold_value=row.final_value, ground_truth=row.ground_truth, quote=row.source_quote)
        for row in evaluated if row.classification != current[(row.ticker, row.metric)].classification]
    write_comparison(path, run_id, mode, reference_run, previous, evaluated, differences)
    return path, run_id, evaluated, differences


def write_comparison(path: Path, run_id: str, mode: str, reference_run: str,
                     previous: list[EvaluationRow], evaluated: list[EvaluationRow], differences: list[Difference]) -> None:
    from dv.report import markdown_table, percent

    rows: list[list[object]] = []
    for name, values in [(reference_run, previous), (run_id, evaluated)]:
        counts = Counter(row.classification for row in values)
        answered = counts["correct"] + counts["wrong"]
        rows.append([name, mode, counts["correct"], counts["wrong"], counts["unverified"], counts["not_found"],
                     counts["no_ground_truth"], counts["error"], percent(counts["correct"] / answered if answered else None)])
    table = markdown_table(["Run", "Mode", "Correct", "Wrong", "Unverified", "Not found", "No ground truth", "Error", "Precision"], rows)
    with sqlite3.connect(path) as db:
        usage = db.execute("SELECT sum(input_tokens),sum(output_tokens),sum(cost_reference_usd),sum(cache_hit),count(*) FROM llm_calls WHERE run_id=?", (run_id,)).fetchone()
        timings = db.execute("SELECT count(*),sum(latency_ms)/1000.0,avg(latency_ms)/1000.0 FROM company_timings WHERE run_id=?", (run_id,)).fetchone()
        stored = json.loads(db.execute("SELECT settings_json FROM runs WHERE run_id=?", (run_id,)).fetchone()[0])
    report = ["# Cold accuracy comparison", "", table, "",
        f"Isolated database: `{path.relative_to(ROOT).as_posix()}`. Initial cache entries: 0. Model: `{MODEL}`; temperature: {stored['llm']['temperature']}.",
        f"New input tokens: {usage[0]:,}; output: {usage[1]:,}; reference cost: {format_cost(usage[2])}; cache hits: {usage[3]}/{usage[4]}.",
        f"Companies measured: {timings[0]}; total wall time: {format_seconds(timings[1])}; average: {format_seconds(timings[2])}/company; reference cost/company: {format_cost(usage[2]/timings[0])}.",
        "Time includes free-tier request pacing and any provider recovery waits.", ""]
    if differences:
        report += ["**STOP: cold-run accuracy differs from the current results.** Dashboard files, original results and original cache have not been changed. No automatic rerun or tuning is permitted by this gate.", "",
            markdown_table(["Ticker", "Metric", "Previous", "Cold", "Previous value", "Cold value", "XBRL", "Cold quote"],
                [[row.ticker, row.metric, row.previous_classification, row.cold_classification, row.previous_value,
                  row.cold_value, row.ground_truth, row.quote] for row in differences]), "",
            "The frozen pipeline/settings/sources were reused; fresh hosted model responses differ from cached responses. Temperature 0 alone does not establish reproducible hosted inference. Each changed classification must be reviewed before selecting a new headline."]
    else:
        report += ["Cold accuracy gate passed: all per-fact classifications match the previous run."]
    text = "\n".join(report) + "\n"
    (ROOT / "reports" / f"cold-final-{mode}-comparison.md").write_text(text, encoding="utf-8")
    print(text, flush=True)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    # Validate the final verified pipeline first; a mismatch stops before any UI work.
    path, run, evaluated, differences = cold_mode("verified")
    if differences:
        raise SystemExit(3)
    # Baseline gets a separate fresh cache; no cross-mode attempt-one cache reuse.
    path, run, evaluated, differences = cold_mode("baseline")
    if differences:
        raise SystemExit(3)
    print("Both cold accuracy gates passed. Continue with cached replay and promotion only after recording this gate.", flush=True)


if __name__ == "__main__":
    main()

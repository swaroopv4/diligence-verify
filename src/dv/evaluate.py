"""Evaluation-only access to the independent answer key (Phase 1 inspection)."""
import logging
import json
import sqlite3
from decimal import Decimal

from dv.config import AppConfig, load_config, project_root
from dv.groundtruth import CompanyFacts, candidate_diagnostics, fetch_companyfacts, match_metric
from dv.models import EvaluationRow, FactResult, FilingMetadata, GroundTruthResult
from dv.sec_client import SECClient

logger = logging.getLogger(__name__)


def inspect_groundtruth(ticker: str) -> list[GroundTruthResult]:
    config = load_config()
    try:
        with SECClient(config.sec) as client:
            filing = client.latest_filing(ticker)
            raw = project_root() / "data" / "raw"
            raw.mkdir(parents=True, exist_ok=True)
            (raw / f"{filing.ticker}_filing.json").write_text(filing.model_dump_json(indent=2), encoding="utf-8")
            facts = fetch_companyfacts(client, filing, raw / f"{filing.ticker}_companyfacts.json")
            results = [match_metric(facts, filing, name, metric) for name, metric in config.metrics.items()]
            if sum(row.value is not None for row in results) < 7:
                for row in results:
                    if row.value is None:
                        for line in candidate_diagnostics(facts, row.metric, config.metrics[row.metric]):
                            logger.warning("ticker=%s step=groundtruth_diagnostics mode=evaluation %s", ticker, line)
            return results
    except Exception:
        logger.exception("ticker=%s step=groundtruth mode=evaluation", ticker)
        raise


def classify_fact(result: FactResult, truth: GroundTruthResult, provider: str, model: str,
                  relative_tolerance: float, eps_tolerance: float) -> EvaluationRow:
    if truth.value is None:
        classification = "no_ground_truth"
    elif result.status in {"unverified", "not_found", "error"}:
        classification = result.status
    elif result.final_value is None:
        classification = "error"
    else:
        expected = Decimal(str(truth.value))
        difference = abs(Decimal(str(result.final_value)) - expected)
        limit = Decimal(str(eps_tolerance)) if result.metric == "eps_diluted" else abs(expected) * Decimal(str(relative_tolerance))
        classification = "correct" if difference <= limit else "wrong"
    return EvaluationRow(run_id=result.run_id, mode=result.mode, ticker=result.ticker,
                         metric=result.metric, provider=provider, model=model,
                         final_value=result.final_value, ground_truth=truth.value,
                         ground_truth_tag=truth.tag, classification=classification,
                         extraction_status=result.status, source_quote=result.fact.source_quote)


def evaluate_stored_run(run_id: str) -> list[EvaluationRow]:
    load_config()  # Load only project credentials; matching/tolerances use frozen settings.
    evaluated: list[EvaluationRow] = []
    with sqlite3.connect(project_root() / "data" / "runs.db") as db:
        db.row_factory = sqlite3.Row
        run = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None:
            raise ValueError(f"Unknown run {run_id}")
        saved = json.loads(run["settings_json"])
        config = AppConfig.model_validate({key: saved[key] for key in AppConfig.model_fields})
        db.execute("""CREATE TABLE IF NOT EXISTS evaluations (
            run_id TEXT NOT NULL, mode TEXT NOT NULL, ticker TEXT NOT NULL,
            metric TEXT NOT NULL, classification TEXT NOT NULL,
            result_json TEXT NOT NULL, PRIMARY KEY (run_id,mode,ticker,metric)
        )""")
        results = [FactResult.model_validate_json(row["result_json"]) for row in db.execute(
            "SELECT result_json FROM fact_results WHERE run_id=? ORDER BY ticker,mode,metric", (run_id,))]
        if not results:
            raise ValueError(f"Run {run_id} has no stored results")
        with SECClient(config.sec) as client:
            for ticker in sorted({result.ticker for result in results}):
                subset = [result for result in results if result.ticker == ticker]
                error_text = None
                truths: dict[str, GroundTruthResult] = {}
                try:
                    source = db.execute("SELECT filing_json FROM run_filings WHERE run_id=? AND ticker=?", (run_id,ticker)).fetchone()
                    if source is None:
                        raise ValueError("No filing metadata; ingestion failed")
                    filing = FilingMetadata.model_validate_json(source["filing_json"])
                    path = project_root() / "data" / "raw" / f"{ticker}_companyfacts.json"
                    facts = CompanyFacts.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else fetch_companyfacts(client, filing, path)
                    truths = {name: match_metric(facts, filing, name, metric) for name,metric in config.metrics.items()}
                except Exception as error:
                    logger.exception("ticker=%s step=groundtruth_evaluation mode=evaluation run_id=%s",ticker,run_id)
                    error_text = f"{type(error).__name__}: {error}"
                for result in subset:
                    truth = truths.get(result.metric)
                    if truth is None:
                        row = EvaluationRow(run_id=run_id,mode=result.mode,ticker=ticker,metric=result.metric,
                                            provider=run["provider"],model=run["model"],final_value=result.final_value,
                                            ground_truth=None,ground_truth_tag=None,classification="no_ground_truth",
                                            extraction_status=result.status,source_quote=result.fact.source_quote,
                                            evaluation_error=error_text)
                    else:
                        row = classify_fact(result,truth,run["provider"],run["model"],
                                            config.verification.relative_tolerance,config.verification.eps_absolute_tolerance)
                    db.execute("INSERT OR REPLACE INTO evaluations VALUES (?, ?, ?, ?, ?, ?)",
                               (run_id,row.mode,ticker,row.metric,row.classification,row.model_dump_json()))
                    evaluated.append(row)
                db.commit()
    return evaluated

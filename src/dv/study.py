"""Shared read-only study data for the dashboard, README and report."""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from typing import Any
from dv.models import DataModel, EvaluationRow, FactResult
from dv.report import format_cost, format_seconds

REVIEW_LABEL = "Unverified · flagged for review"

CHECK_NAMES = {
    "V1": "Source belongs to this filing", "V2": "Quote matches the source exactly",
    "V3": "Displayed number is copied exactly", "V4": "Number can be parsed",
    "V5": "Scale and per-share units are supported", "V6": "Selected column matches the fiscal period",
    "V7": "Financial sanity checks", "V8": "Row label and financial scope match",
}
FAILED_NAMES = {
    "V1": "source not in this filing", "V2": "quote is not exact", "V3": "number was not copied exactly",
    "V4": "unparseable number", "V5": "unsupported scale", "V6": "fiscal-period column not verified",
    "V7": "financial sanity check failed", "V8": "wrong row or financial scope",
}

class Study(DataModel):
    model: str
    baseline_run: str
    verified_run: str
    first_baseline_run: str
    first_verified_run: str
    cache_run: str | None
    companies: list[str]
    metrics: list[str]
    cold: bool = False

class CaughtError(DataModel):
    model: str
    ticker: str
    metric: str
    baseline_value: float | None
    ground_truth: float | None
    outcome: str
    checks: str
    quote: str
    first_check: str = ""
    corrected: bool = False
    attempts: int = 1

class Usage(DataModel):
    input_tokens: int
    output_tokens: int
    seconds: float
    cost: float
    actual_cost: float
    calls: int
    hits: int

    @property
    def hit_rate(self) -> float | None:
        return self.hits / self.calls if self.calls else None

def extraction_signature(settings: dict[str, Any]) -> str:
    """Verifier changes may reuse a baseline; extraction changes may not."""
    value = {
        "companies": sorted(settings["selected_companies"]),
        "metrics": {name: {key: definition[key] for key in ("kind", "unit", "query", "xbrl_tags")}
                    for name, definition in settings["metrics"].items()},
        "retrieval": settings["retrieval"], "llm": settings["llm"],
        "code": settings.get("extraction_code_sha256"),
    }
    return json.dumps(value, sort_keys=True)

def verifier_signature(settings: dict[str, Any]) -> str:
    return json.dumps({"verification": settings["verification"], "metrics": settings["metrics"],
                       "code": settings.get("verifier_code_sha256")}, sort_keys=True)

def call_usage(db: sqlite3.Connection, run_id: str, mode: str) -> Usage:
    row = db.execute("""SELECT COALESCE(sum(input_tokens),0) AS inputs, COALESCE(sum(output_tokens),0) AS outputs,
        COALESCE(sum(cost_reference_usd),0) AS cost, COALESCE(sum(cost_actual_usd),0) AS actual,
        count(*) AS calls, COALESCE(sum(cache_hit),0) AS hits FROM llm_calls WHERE run_id=? AND mode=?""", (run_id, mode)).fetchone()
    seconds = db.execute("SELECT COALESCE(sum(latency_ms),0)/1000.0 FROM company_timings WHERE run_id=? AND mode=?", (run_id, mode)).fetchone()[0]
    return Usage(input_tokens=row["inputs"], output_tokens=row["outputs"], seconds=seconds,
                 cost=row["cost"], actual_cost=row["actual"], calls=row["calls"], hits=row["hits"])

def legacy_studies(db: sqlite3.Connection) -> list[Study]:
    """Pair first comparable baseline/latest complete verification by provenance.

    Partial trials are excluded. Costs use first complete mode runs; the cache
    replay must match those original verifier settings, not a later repair run.
    """
    runs = [dict(row) for row in db.execute("SELECT * FROM runs ORDER BY created_at,run_id")]
    settings = {row["run_id"]: json.loads(row["settings_json"]) for row in runs}
    complete: dict[str, set[str]] = {}
    complete_facts: dict[str, set[str]] = {}
    manifests: dict[str, list[tuple[str, str, str]]] = {}
    for run in runs:
        run_id, config = run["run_id"], settings[run["run_id"]]
        companies = set(config.get("selected_companies", []))
        if not companies or companies != set(config["companies"]["full"]):
            continue
        wanted = {(ticker, metric) for ticker in companies for metric in config["metrics"]}
        for mode in ("baseline", "verified"):
            facts = set(map(tuple, db.execute("SELECT ticker,metric FROM fact_results WHERE run_id=? AND mode=?", (run_id, mode))))
            evaluations = set(map(tuple, db.execute("SELECT ticker,metric FROM evaluations WHERE run_id=? AND mode=?", (run_id, mode))))
            if facts == wanted:
                complete_facts.setdefault(run_id, set()).add(mode)
            if facts == evaluations == wanted:
                complete.setdefault(run_id, set()).add(mode)
        manifests[run_id] = list(map(tuple, db.execute("SELECT ticker,filing_json,chunk_sha256 FROM run_filings WHERE run_id=? ORDER BY ticker", (run_id,))))
    studies: list[Study] = []
    for model in dict.fromkeys(run["model"] for run in runs):
        baselines = [run for run in runs if run["model"] == model and "baseline" in complete.get(run["run_id"], set())]
        for baseline in baselines:
            base = baseline["run_id"]
            signature = extraction_signature(settings[base])
            verified = [run["run_id"] for run in runs if run["model"] == model
                        and "verified" in complete.get(run["run_id"], set())
                        and extraction_signature(settings[run["run_id"]]) == signature
                        and manifests[run["run_id"]] == manifests[base]]
            if not verified:
                continue
            first, cache = verified[0], None
            candidates = [run["run_id"] for run in runs if run["model"] == model and run["run_id"] != first
                          and "verified" in complete_facts.get(run["run_id"], set())
                          and extraction_signature(settings[run["run_id"]]) == signature
                          and manifests[run["run_id"]] == manifests[base]]
            for candidate in candidates:
                usage = call_usage(db, candidate, "verified")
                if usage.calls and usage.hits == usage.calls and verifier_signature(settings[candidate]) == verifier_signature(settings[first]):
                    originals = [json.loads(row[0]) for row in db.execute("SELECT result_json FROM fact_results WHERE run_id=? AND mode='verified' ORDER BY ticker,metric", (first,))]
                    replay = [json.loads(row[0]) for row in db.execute("SELECT result_json FROM fact_results WHERE run_id=? AND mode='verified' ORDER BY ticker,metric", (candidate,))]
                    for result in originals + replay:
                        result.pop("run_id")
                    if originals == replay:
                        cache = candidate
                        break
            studies.append(Study(model=model, baseline_run=base, verified_run=verified[-1],
                                 first_baseline_run=base, first_verified_run=first, cache_run=cache,
                                 companies=settings[base]["selected_companies"], metrics=list(settings[base]["metrics"])))
            break
    return studies

def format_number(value: float | None, metric: str = "") -> str:
    if value is None:
        return "—"
    sign = "−" if value < 0 else ""
    if metric == "eps_diluted":
        return f"{sign}${abs(value):.2f}"
    for divisor, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if abs(value) >= divisor:
            return f"{sign}${abs(value) / divisor:.2f}{suffix}"
    return f"{sign}${abs(value):,.2f}"

def metric_name(metric: str) -> str:
    return "Diluted EPS" if metric == "eps_diluted" else metric.replace("_", " ").title()

def caught_errors(db: sqlite3.Connection, study: Study) -> list[CaughtError]:
    rows = db.execute("""SELECT b.ticker,b.metric,b.result_json AS baseline_eval,
        v.result_json AS verified_eval,f.result_json AS baseline_fact
        FROM evaluations b JOIN evaluations v ON v.ticker=b.ticker AND v.metric=b.metric
        JOIN fact_results f ON f.run_id=b.run_id AND f.ticker=b.ticker AND f.metric=b.metric AND f.mode=b.mode
        WHERE b.run_id=? AND b.mode='baseline' AND b.classification='wrong'
        AND v.run_id=? AND v.mode='verified' AND v.classification IN ('correct','unverified')
        ORDER BY b.ticker,b.metric""", (study.baseline_run, study.verified_run)).fetchall()
    result: list[CaughtError] = []
    for row in rows:
        baseline = EvaluationRow.model_validate_json(row["baseline_eval"])
        verified = EvaluationRow.model_validate_json(row["verified_eval"])
        fact = FactResult.model_validate_json(row["baseline_fact"])
        checks: list[str] = []
        for attempt in db.execute("SELECT verification_json FROM verification_attempts WHERE run_id=? AND ticker=? AND metric=? ORDER BY attempt",
                                  (study.verified_run, row["ticker"], row["metric"])):
            code = json.loads(attempt[0])["failed_check"]
            if code and code not in checks:
                checks.append(code)
        first = db.execute("SELECT verification_json FROM verification_attempts WHERE run_id=? AND ticker=? AND metric=? AND attempt=1",(study.verified_run,row["ticker"],row["metric"])).fetchone()
        first_code = json.loads(first[0])["failed_check"] if first else None
        saved = db.execute("SELECT attempts FROM fact_results WHERE run_id=? AND mode='verified' AND ticker=? AND metric=?",(study.verified_run,row["ticker"],row["metric"])).fetchone() if "attempts" in {entry[1] for entry in db.execute("PRAGMA table_info(fact_results)")} else None
        result.append(CaughtError(model=study.model, ticker=row["ticker"], metric=row["metric"],
            baseline_value=baseline.final_value, ground_truth=baseline.ground_truth,
            outcome=("Corrected to " + format_number(verified.final_value, row["metric"]) if verified.classification == "correct" else "Flagged for review"),
            checks="; ".join(f"{code} · {CHECK_NAMES.get(code, 'Unknown check')}" for code in checks) or "No stored failed-check audit",
            quote=fact.fact.source_quote or "No quote recorded", corrected=verified.classification=="correct",
            attempts=saved[0] if saved else 1,
            first_check=f"{first_code} · {FAILED_NAMES.get(first_code, 'check failed')}" if first_code else "No first-attempt failure"))
    return sorted(result,key=lambda item:(not item.corrected,item.ticker,item.metric))


def select_studies(db: sqlite3.Connection) -> list[Study]:
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='canonical_studies'").fetchone():
        return legacy_studies(db)
    studies: list[Study] = []
    for row in db.execute("SELECT * FROM canonical_studies ORDER BY model"):
        settings=json.loads(db.execute("SELECT settings_json FROM runs WHERE run_id=?",(row['verified_run'],)).fetchone()[0])
        expected={(ticker,metric) for ticker in settings['selected_companies'] for metric in settings['metrics']}
        for run,mode in [(row['baseline_run'],'baseline'),(row['verified_run'],'verified'),(row['cache_run'],'verified')]:
            actual=set(map(tuple,db.execute("SELECT ticker,metric FROM evaluations WHERE run_id=? AND mode=?",(run,mode))))
            if actual!=expected:
                raise ValueError(f"Canonical evaluation is incomplete: {run}")
        studies.append(Study(model=row['model'],baseline_run=row['baseline_run'],verified_run=row['verified_run'],
            first_baseline_run=row['baseline_run'],first_verified_run=row['verified_run'],cache_run=row['cache_run'],
            companies=settings['selected_companies'],metrics=list(settings['metrics']),cold=True))
    return studies


def result_rows(db: sqlite3.Connection, studies: list[Study]) -> list[dict[str, object]]:
    from dv.report import summarize,percent
    rows=[]
    for study in studies:
        total=len(study.companies)*len(study.metrics)
        for mode,run in [('baseline',study.baseline_run),('verified',study.verified_run)]:
            value=summarize(db,run,mode)
            if value.error:
                raise ValueError(f"Canonical run contains processing errors: {run}")
            counts=[value.correct,value.wrong,value.unverified,value.not_found,value.no_ground_truth]
            if sum(counts)!=total:
                raise ValueError(f"Canonical result counts do not sum to {total}: {run}")
            rows.append(dict(zip(['Mode','Model','Correct','Wrong','Unverified','Not found','No ground truth','Precision on answered'],
                [mode.title(),study.model,*counts,percent(value.precision_on_answered)])))
    return rows


def headline(db: sqlite3.Connection, studies: list[Study]) -> str:
    rows=result_rows(db,studies)
    wrong=sum(row['Wrong'] for row in rows if row['Mode']=='Baseline')
    remaining=sum(row['Wrong'] for row in rows if row['Mode']=='Verified')
    errors=[error for study in studies for error in caught_errors(db,study)]
    corrected=sum(error.corrected for error in errors)
    flagged=len(errors)-corrected
    if wrong and remaining==0 and len(errors)==wrong:
        retry_corrected=sum(error.corrected and error.attempts>1 for error in errors)
        correction=f"{corrected} corrected on retry" if retry_corrected==corrected else f"{corrected} corrected"
        return f"Code verification removed all {wrong} wrong answers: {correction}, {flagged} flagged for human review."
    return f"Code verification caught {len(errors)} of {wrong} baseline errors; {remaining} wrong verified answers remain."


def review_summary(db: sqlite3.Connection, studies: list[Study]) -> tuple[int, str]:
    total = sum(row['Unverified'] for row in result_rows(db, studies) if row['Mode'] == 'Verified')
    caught = sum(not error.corrected for study in studies for error in caught_errors(db, study))
    return total, f"includes {caught} caught baseline errors"


def cost_rows(db: sqlite3.Connection, study: Study) -> list[dict[str, object]]:
    from dv.report import summarize
    rows=[]
    for mode,run in [('baseline',study.baseline_run),('verified',study.verified_run)]:
        summary=summarize(db,run,mode)
        rows.append({'Mode':mode.title(),'Reference cost / company':summary.cost_reference_usd/len(study.companies),
                     'Avg time / company (s)':summary.avg_seconds_per_company})
    return rows


def average_steps(db: sqlite3.Connection, study: Study) -> list[dict[str, object]]:
    rows=db.execute("""SELECT CASE WHEN step LIKE '%.attempt_1%' THEN 'Extraction attempt 1' ELSE 'Verification retries' END,
        count(*),sum(cost_reference_usd) FROM llm_calls WHERE run_id=? AND mode='verified' GROUP BY 1""",(study.verified_run,)).fetchall()
    return [{'Step':name,'Requests':count,'Avg reference cost / company':cost/len(study.companies)} for name,count,cost in rows]


def generate_final_report(db: sqlite3.Connection, destination: Path) -> Path:
    from dv.report import markdown_table,percent
    studies=select_studies(db);rows=result_rows(db,studies)
    review_total, review_caption = review_summary(db, studies)
    sections=['# Diligence Verify','',headline(db,studies),'',
        f"**{REVIEW_LABEL}: {review_total}**",review_caption,'',
        markdown_table(list(rows[0]),[list(row.values()) for row in rows]),'']
    for study in studies:
        total=len(study.companies)*len(study.metrics)
        sections += [f"Each mode covers {total} facts: {len(study.companies)} companies × {len(study.metrics)} metrics. Missing ground truth is excluded from precision.", '', '## Caught errors','']
        errors=caught_errors(db,study)
        sections += [markdown_table(['Company','Metric','Baseline value','XBRL value','Verified outcome','Caught by','Source quote'],
            [[e.ticker,metric_name(e.metric),format_number(e.baseline_value,e.metric),format_number(e.ground_truth,e.metric),e.outcome,e.first_check,e.quote] for e in errors[:5]]) if errors else 'No baseline errors were corrected or flagged.', '', '## Cost per company','']
        costs=cost_rows(db,study)
        sections += [markdown_table(['Mode','Reference cost / company','Avg time / company'],
            [[r['Mode'],format_cost(r['Reference cost / company']),format_seconds(r['Avg time / company (s)'])] for r in costs]),
            '', '## Average verified cost by step','',markdown_table(['Step','Requests','Avg reference cost / company'],
            [[r['Step'],r['Requests'],format_cost(r['Avg reference cost / company'])] for r in average_steps(db,study)]),'',
            '## Verified replay','']
        usage=[]
        for label,run in [('Cold verified',study.verified_run),('Cached replay',study.cache_run)]:
            u=call_usage(db,run,'verified')
            usage.append([label,u.input_tokens+u.output_tokens,format_seconds(u.seconds),format_cost(u.cost),percent(u.hit_rate)])
        sections += [markdown_table(['Run','New tokens','Time','Reference cost','Cache hit rate'],usage),'',
            'Reference costs use the token prices stored with each run. Measured time includes free-tier pacing and recovery waits.', '',
            '## Per-metric results','']
        from dv.report import summarize
        per_metric=[]
        for mode,run in [('baseline',study.baseline_run),('verified',study.verified_run)]:
            for metric in study.metrics:
                value=summarize(db,run,mode,metric)
                per_metric.append([mode.title(),metric_name(metric),value.correct,value.wrong,value.unverified,value.not_found,value.no_ground_truth,percent(value.precision_on_answered)])
        sections += [markdown_table(['Mode','Metric','Correct','Wrong','Unverified','Not found','No ground truth','Precision'],per_metric),'','## Flagged for review','']
        flagged=[]
        for record in db.execute("SELECT result_json FROM fact_results WHERE run_id=? AND mode='verified' AND status='unverified' ORDER BY ticker,metric",(study.verified_run,)):
            fact=FactResult.model_validate_json(record[0]);failure=fact.verification
            flagged.append([fact.ticker,metric_name(fact.metric),failure.failed_check,failure.reason,fact.fact.source_quote])
        sections += [markdown_table(['Company','Metric','Check','Reason','Source quote'],flagged) if flagged else 'No facts are flagged for review.','',
            '## Verification','',*['- '+code+': '+name+'.' for code,name in CHECK_NAMES.items()],'', '## Limitations','',
            f"One model, {len(study.companies)} companies, and 10-K filings only. Precision measures accepted answers with matching XBRL ground truth; abstentions and missing facts affect coverage. Deterministic checks do not guarantee correctness on other filings.",
            'Intel section labels remain unknown: its Item labels occur in a cross-reference index rather than body boundaries. Whole-document retrieval preserves source evidence but has less reliable section ranking.', '',
            f"Data: `{study.baseline_run}`, `{study.verified_run}`, `{study.cache_run}`.",'']
    destination.parent.mkdir(parents=True,exist_ok=True);destination.write_text('\n'.join(sections),encoding='utf-8')
    return destination


def generate_readme(db: sqlite3.Connection, destination: Path) -> Path:
    from dv.report import markdown_table
    studies=select_studies(db);study=studies[0];rows=result_rows(db,studies);costs=cost_rows(db,study)
    review_total, review_caption = review_summary(db, studies)
    examples=caught_errors(db,study)[:3]
    lines=['# Diligence Verify','',
        f"Diligence Verify extracts {len(study.metrics)} financial numbers from {len(study.companies)} public companies’ SEC 10-K filings, verifies source quotes, numbers, scales, fiscal columns and financial row labels with deterministic code, and checks the results against SEC XBRL. The read-only Streamlit dashboard includes traceable filing evidence, caught errors and measured cost per company. No API keys are required.", '',
        markdown_table(list(rows[0]),[list(row.values()) for row in rows]),'',headline(db,studies),'',
        f"**{REVIEW_LABEL}: {review_total}**",review_caption,'',
        f"Each mode covers {len(study.companies)*len(study.metrics)} facts; missing ground truth is excluded from precision.",'', '## Examples','']
    lines += [f"- {e.ticker} {metric_name(e.metric).lower()}: {format_number(e.baseline_value,e.metric)} vs XBRL {format_number(e.ground_truth,e.metric)}; {e.outcome[:1].lower() + e.outcome[1:]}." for e in examples]
    lines += ['', '## Verification','',*['- '+code+': '+name+'.' for code,name in CHECK_NAMES.items()], '', '## Cost per company','']
    lines += [f"- {r['Mode']}: {format_cost(r['Reference cost / company'])} at reference token prices; {format_seconds(r['Avg time / company (s)'])} average." for r in costs]
    lines += ['', '## Limitations','',f"One model, {len(study.companies)} companies, 10-K filings only. Ground-truth coverage is incomplete; precision does not measure missing answers. Intel section labels remain unknown because its Item references are in an index rather than body headings. Results describe this sample and do not guarantee financial correctness.", '',
        '## Run locally','', 'Use Python 3.11, then:', '', '```bash', 'git clone https://github.com/swaroopV4/diligence-verify.git', 'cd diligence-verify', 'python -m venv .venv', '# Activate .venv (Windows: .venv\\Scripts\\Activate.ps1; Linux/macOS: source .venv/bin/activate)',
        'python -m pip install -r requirements.txt','streamlit run app/streamlit_app.py','```','',
        '[Full results](reports/results.md) · [GitHub](https://github.com/swaroopV4/diligence-verify)']
    content='\n'.join(lines)+'\n'
    if len(content.splitlines())>=60:raise ValueError('README must remain under 60 lines')
    destination.write_text(content,encoding='utf-8');return destination

"""Read-only executive view of stored results, costs, and immutable evidence."""
from __future__ import annotations

import hashlib
import html
import json
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

# Run directly from a fresh src-layout checkout without installing the research
# package (whose optional extraction dependencies are not needed by the demo).
SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from dv.config import project_root
from dv.models import Chunk, ConsistencyFlag, DataModel, EvaluationRow, FactResult, ModeSummary
from dv.report import percent, read_database, summarize
from dv.table import TRANSLATION, locate_cells, normalize_quote

ROOT = project_root()
logger = logging.getLogger(__name__)
CHECK_NAMES = {
    "V1": "Source belongs to this filing",
    "V2": "Quote matches the source exactly",
    "V3": "Displayed number is copied exactly",
    "V4": "Number can be parsed",
    "V5": "Scale and per-share units are supported",
    "V6": "Selected column matches the fiscal period",
    "V7": "Financial sanity checks",
    "V8": "Row label and financial scope match",
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


class CaughtError(DataModel):
    model: str
    ticker: str
    metric: str
    baseline_value: float | None
    ground_truth: float | None
    outcome: str
    checks: str
    quote: str


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


def highlighted_quote(text: str, quote: str | None) -> tuple[str, bool]:
    """Preserve source characters while matching normalized whitespace/Unicode."""
    if not quote:
        return html.escape(text), False
    normalized: list[str] = []
    spans: list[tuple[int, int]] = []
    for index, char in enumerate(text):
        translated = char.translate(TRANSLATION)
        if translated.isspace():
            if normalized and normalized[-1] == " ":
                spans[-1] = (spans[-1][0], index + 1)
            elif normalized:
                normalized.append(" ")
                spans.append((index, index + 1))
        else:
            normalized.append(translated)
            spans.append((index, index + 1))
    if normalized and normalized[-1] == " ":
        normalized.pop()
        spans.pop()
    target = normalize_quote(quote)
    start = "".join(normalized).find(target)
    if start < 0 or not target:
        return html.escape(text), False
    left, right = spans[start][0], spans[start + len(target) - 1][1]
    return html.escape(text[:left]) + "<mark>" + html.escape(text[left:right]) + "</mark>" + html.escape(text[right:]), True


def highlighted_evidence(chunk: Chunk, fact: FactResult) -> tuple[str, str]:
    """Highlight a unique matched table row and cell; never guess a location."""
    if chunk.is_table:
        cells = locate_cells(fact.fact, chunk)
        if len(cells) == 1:
            cell = cells[0]
            rendered: list[str] = []
            for index, line in enumerate(chunk.text.splitlines()):
                if index == cell.row_index:
                    parts = [html.escape(part) for part in line.split("|")]
                    parts[cell.cell_index] = '<mark class="selected-cell">' + parts[cell.cell_index] + "</mark>"
                    rendered.append('<span class="selected-row">' + "|".join(parts) + "</span>")
                else:
                    rendered.append(html.escape(line))
            header = cell.header.label if cell.header else "unresolved"
            return "\n".join(rendered), f"Blue: matched row. Gold: selected cell. Column: {header}."
    rendered, found = highlighted_quote(chunk.text, fact.fact.source_quote)
    return rendered, ("Gold: exact source quote." if found else "The reported quote has no exact match; source text is shown without a guessed highlight.")


@st.cache_data(show_spinner=False)
def load_chunks(relative_path: str, expected_hash: str) -> dict[str, Chunk]:
    # Historical run metadata was produced on Windows; Cloud runs on Linux.
    path = (ROOT / relative_path.replace("\\", "/")).resolve()
    if not path.is_relative_to((ROOT / "data" / "processed").resolve()):
        raise ValueError("Source snapshot is outside the processed-data directory")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected_hash:
        raise ValueError("Source snapshot hash does not match the stored run")
    return {chunk.chunk_id: chunk for line in content.decode("utf-8").splitlines()
            if line and (chunk := Chunk.model_validate_json(line))}


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


def select_studies(db: sqlite3.Connection) -> list[Study]:
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


def status_label(result: FactResult, evaluation: EvaluationRow) -> str:
    if result.status == "unverified":
        code = result.verification.failed_check if result.verification else ""
        return f"Review · {code}"
    if result.status == "not_found":
        return "Not found"
    if result.status == "error" or evaluation.classification == "error":
        return "Error"
    return "Checks passed" if result.mode == "verified" else "Extracted"


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
        result.append(CaughtError(model=study.model, ticker=row["ticker"], metric=row["metric"],
            baseline_value=baseline.final_value, ground_truth=baseline.ground_truth,
            outcome=("Corrected to " + format_number(verified.final_value, row["metric"]) if verified.classification == "correct" else "Flagged for review"),
            checks="; ".join(f"{code} · {CHECK_NAMES.get(code, 'Unknown check')}" for code in checks) or "No stored failed-check audit",
            quote=fact.fact.source_quote or "No quote recorded"))
    return result


def source_evidence(db: sqlite3.Connection, run_id: str, ticker: str, fact: FactResult, evaluation: EvaluationRow) -> None:
    st.subheader("Source evidence")
    st.caption(f"{metric_name(fact.metric)} · Extracted {format_number(fact.final_value, fact.metric)} · XBRL {format_number(evaluation.ground_truth, fact.metric)}")
    if fact.verification and not fact.verification.passed:
        code = fact.verification.failed_check
        st.info(f"{code} · {CHECK_NAMES.get(code, '')}: {fact.verification.reason}")
    if evaluation.classification == "wrong":
        st.error("The accepted value differs from the independent XBRL reference.")
    source = db.execute("SELECT * FROM run_filings WHERE run_id=? AND ticker=?", (run_id, ticker)).fetchone()
    if not source:
        st.info("No filing snapshot was stored for this selection.")
        return
    filing = json.loads(source["filing_json"])
    accession = filing["accession"].replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{filing['cik']}/{accession}/{filing['primary_document']}"
    st.markdown(f"[Open SEC filing]({url}) · Fiscal end: {filing['period_of_report']}")
    st.caption(f"Chunk ID: {fact.fact.source_chunk_id or 'No source found'} · XBRL tag: {evaluation.ground_truth_tag or 'No matching tag'}")
    if fact.fact.source_quote:
        st.caption("Reported source quote")
        st.code(fact.fact.source_quote, language=None, wrap_lines=True)
    chunk = load_chunks(source["chunk_path"], source["chunk_sha256"]).get(fact.fact.source_chunk_id or "")
    if chunk:
        marked, explanation = highlighted_evidence(chunk, fact)
        st.markdown('<div class="source-box">' + marked + "</div>", unsafe_allow_html=True)
        st.caption(explanation)
    else:
        st.info("The reported source chunk is unavailable or no source was found.")


def cost_and_cache(db: sqlite3.Connection, study: Study, ticker: str, mode: str) -> None:
    st.subheader("Cost and cache")
    first_id = study.first_baseline_run if mode == "baseline" else study.first_verified_run
    chart, comparison = st.columns([1, 1])
    with chart:
        st.markdown(f"**First-run cost by step · {ticker} · {mode}**")
        costs = pd.read_sql_query("""SELECT step AS Step, SUM(cost_reference_usd) AS 'Reference USD'
            FROM llm_calls WHERE run_id=? AND ticker=? AND mode=? AND cache_hit=0 GROUP BY step ORDER BY step""",
            db, params=(first_id, ticker, mode))
        if costs.empty:
            st.caption("No uncached call cost was recorded for this selection in the first run.")
        else:
            costs["Step"] = costs["Step"].map(lambda value: metric_name(value.replace(".repair", "")) + (" · repair" if ".repair" in value else ""))
            st.bar_chart(costs.set_index("Step"), height=245, color="#4677b8")
        st.caption(f"Source: {first_id}. Only uncached calls contribute to reference cost.")
    with comparison:
        st.markdown("**First run vs cached rerun · verified mode · full cohort**")
        first = call_usage(db, study.first_verified_run, "verified")
        pairs = [("First run", first)]
        if study.cache_run:
            pairs.append(("Cached rerun", call_usage(db, study.cache_run, "verified")))
        st.dataframe(pd.DataFrame([{"Run": label, "Tokens": f"{usage.input_tokens + usage.output_tokens:,}", "Time": f"{usage.seconds:.2f}s",
            "Reference cost": f"${usage.cost:.6f}", "Cache hit rate": percent(usage.hit_rate)} for label, usage in pairs]), hide_index=True, width="stretch")
        if not study.cache_run:
            st.caption("No complete compatible cached rerun has been stored.")
        else:
            st.caption(f"First: {study.first_verified_run}. Cached: {study.cache_run}.")
        st.caption("Recorded tokens, wall time and hypothetical reference-price costs. Cache hits consume no new tokens.")
        if first.hits:
            st.caption("The first study already reused some cached calls; a fully cold run was not recorded.")
        if study.verified_run != study.first_verified_run:
            st.caption("This cost/cache comparison uses the original check set and its matching replay. The accuracy table uses the updated verifier.")


def main() -> None:
    st.set_page_config(page_title="Diligence Verify", page_icon="✓", layout="wide")
    st.markdown("""<style>
      .block-container {padding-top:1.6rem; max-width:1600px}
      h1 {letter-spacing:-.045em; padding-bottom:.2rem!important}
      h2 {letter-spacing:-.025em}
      [data-testid="stMetric"] {background:#f4f7fb;border:1px solid #dce4ef;border-radius:10px;padding:14px 16px}
      [data-testid="stMetricValue"] {font-size:1.8rem}
      .source-box {white-space:pre-wrap;overflow:auto;max-height:430px;background:#f7f9fc;
        color:#17283c;border:1px solid #dce3ed;border-radius:8px;padding:16px;
        font-family:ui-monospace,Consolas,monospace;font-size:12px;line-height:1.8}
      .source-box mark {background:#ffe395;color:#17283c;border-radius:3px}
      .selected-row {background:#dceafa;display:inline-block;min-width:100%}
      .selected-cell {font-weight:800;outline:2px solid #c08c20;padding:2px}
    </style>""", unsafe_allow_html=True)
    st.title("Diligence Verify")
    try:
        with read_database() as db:
            studies = select_studies(db)
            if not studies:
                st.info("No complete, comparable evaluated study is available yet.")
                st.stop()
            companies = set().union(*(set(study.companies) for study in studies))
            metrics = set().union(*(set(study.metrics) for study in studies))
            st.write(f"LLM extraction of {len(metrics)} financial numbers from {len(companies)} companies' 10-K filings, verified by code and checked against SEC XBRL data.")
            summaries = [summarize(db, study.baseline_run if mode == "baseline" else study.verified_run, mode)
                         for study in studies for mode in ("baseline", "verified")]
            baseline = [summary for summary in summaries if summary.mode == "baseline"]
            verified = [summary for summary in summaries if summary.mode == "verified"]

            def precision(group: list[ModeSummary]) -> str:
                correct = sum(item.correct for item in group)
                answered = sum(item.correct + item.wrong for item in group)
                return percent(correct / answered if answered else None)

            wrong_card, precision_card, review_card, cost_card = st.columns(4)
            wrong_card.metric("Wrong answers · baseline → verified", f"{sum(item.wrong for item in baseline)} → {sum(item.wrong for item in verified)}")
            precision_card.metric("Precision · baseline → verified", f"{precision(baseline)} → {precision(verified)}")
            review_card.metric("Unverified · flagged for review", sum(item.unverified for item in verified))
            first_cost = sum(call_usage(db, study.first_baseline_run, "baseline").cost + call_usage(db, study.first_verified_run, "verified").cost for study in studies)
            cost_card.metric("Reference cost / company", f"${first_cost / len(companies):.4f}", help="Recorded uncached-call cost in the first full baseline + verified study, divided by companies. Never uses the cached replay.")
            st.caption("Baseline → latest verified results. Cost / company covers both modes in the first full study; it is a reference-price estimate of recorded uncached calls.")
            st.dataframe(pd.DataFrame([{"Mode": summary.mode.title(), "Model": summary.model, "Correct": summary.correct,
                "Wrong": summary.wrong, "Unverified": summary.unverified, "Not found": summary.not_found,
                "Precision": percent(summary.precision_on_answered)} for summary in summaries]), hide_index=True, width="stretch")

            all_caught = [error for study in studies for error in caught_errors(db, study)]
            st.subheader("Caught errors")
            if all_caught:
                st.dataframe(pd.DataFrame([{"Company": error.ticker, "Metric": metric_name(error.metric),
                    "Baseline value": format_number(error.baseline_value, error.metric), "XBRL value": format_number(error.ground_truth, error.metric),
                    "Verified outcome": error.outcome, "Failed check": error.checks, "Source quote": error.quote}
                    for error in all_caught[:5]]), hide_index=True, width="stretch",
                    column_config={"Source quote": st.column_config.TextColumn(width="large"), "Failed check": st.column_config.TextColumn(width="large")})
                corrected = sum(error.outcome.startswith("Corrected") for error in all_caught)
                st.caption(f"{len(all_caught)} baseline errors caught: {corrected} corrected, {len(all_caught) - corrected} flagged for review. Quotes show the baseline evidence; failed checks come from the verified retry audit.")
            else:
                st.write("No stored cases where a baseline error was corrected or flagged by verification.")

            st.subheader("Company drill-down")
            model_col, company_col, mode_col = st.columns([2, 1, 1])
            models = [study.model for study in studies]
            model = model_col.selectbox("Model", models, key="model")
            study = next(item for item in studies if item.model == model)
            caught = [error for error in all_caught if error.model == model]
            default_company = caught[0].ticker if caught else sorted(study.companies)[0]
            cohort = sorted(study.companies)
            ticker = company_col.selectbox("Company", cohort, index=cohort.index(default_company), key="ticker")
            mode = mode_col.selectbox("Mode", ["verified", "baseline"], key="mode")
            run_id = study.baseline_run if mode == "baseline" else study.verified_run
            stored = db.execute("""SELECT f.result_json AS fact_json,e.result_json AS evaluation_json FROM fact_results f
                JOIN evaluations e USING (run_id,mode,ticker,metric) WHERE f.run_id=? AND f.ticker=? AND f.mode=? ORDER BY f.metric""", (run_id, ticker, mode)).fetchall()
            facts = [FactResult.model_validate_json(row["fact_json"]) for row in stored]
            evaluations = [EvaluationRow.model_validate_json(row["evaluation_json"]) for row in stored]
            if not facts:
                st.info("No stored facts for this selection.")
                st.stop()
            table = pd.DataFrame([{"Metric": metric_name(fact.metric), "Value": format_number(fact.final_value, fact.metric),
                "XBRL value": format_number(evaluation.ground_truth, fact.metric),
                "Match": "✓" if evaluation.classification == "correct" else "✗" if evaluation.classification == "wrong" else "—",
                "Status": status_label(fact, evaluation)} for fact, evaluation in zip(facts, evaluations, strict=True)])
            event = st.dataframe(table, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                                 key=f"facts_{run_id}_{ticker}_{mode}", height="auto")
            st.caption("Match: ✓ within XBRL tolerance · ✗ outside tolerance · — no comparable accepted answer. Select a row for evidence.")
            st.caption("Checks: " + " · ".join(f"{code}: {name}" for code, name in CHECK_NAMES.items()))
            chosen = event.selection.rows
            default_metric = next((error.metric for error in caught if error.ticker == ticker), None)
            index = chosen[0] if chosen and chosen[0] < len(facts) else next((i for i, fact in enumerate(facts) if fact.metric == default_metric), 0)
            source_evidence(db, run_id, ticker, facts[index], evaluations[index])

            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='consistency_flags'").fetchone():
                flags = [ConsistencyFlag.model_validate_json(row[0]) for row in db.execute("SELECT flag_json FROM consistency_flags WHERE run_id=? AND ticker=?", (run_id, ticker))]
                if flags:
                    with st.expander("Consistency review leads"):
                        st.caption("Review leads may reflect rounding or scope. They do not change accuracy labels.")
                        for flag in flags:
                            st.write(metric_name(flag.metric))
                            st.code(flag.prose_quote, language=None)

            cost_and_cache(db, study, ticker, mode)
            with st.expander("Study coverage and limits", expanded=False):
                if len(studies) < 2:
                    st.write("Second-model benchmark pending. Partial secondary-model trials are excluded from the completed comparison.")
                st.write(f"{len(companies)} public companies · {len(metrics)} financial metrics · one form type (10-K) · free hosted model tier. "
                         "Precision counts only accepted answers with XBRL ground truth. No-ground-truth cases are excluded. "
                         "Deterministic source, column and row-scope checks reduce these observed errors but do not guarantee financial correctness.")
                st.dataframe(pd.DataFrame([{"Model": summary.model, "Mode": summary.mode.title(), "Facts with ground truth": summary.total_with_ground_truth,
                    "Not found": summary.not_found, "Processing errors": summary.error, "No ground truth": summary.no_ground_truth}
                    for summary in summaries]), hide_index=True, width="stretch")
                for item in studies:
                    st.caption(f"{item.model}: baseline {item.baseline_run}; verified {item.verified_run}. "
                               "Baseline reuse requires identical extraction settings, code hash and immutable filing snapshots.")
                st.caption("Reference costs use stored per-call token prices; actual free-tier charges differ. "
                           "The first completed study already contained cache reuse, so no fully uncached end-to-end cost or speed claim is made. "
                           "The same-settings cache comparison uses the original check set; updated accuracy uses the later verifier run.")
    except (FileNotFoundError, ValueError, sqlite3.Error) as error:
        logger.exception("ticker=%s step=dashboard mode=%s", st.session_state.get("ticker", "study"), st.session_state.get("mode", "summary"))
        st.error(str(error))


if __name__ == "__main__":
    main()

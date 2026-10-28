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
from dv.study import CHECK_NAMES, Study, CaughtError, Usage, select_studies, call_usage, caught_errors, format_number, metric_name, headline, result_rows, average_steps, cost_rows

ROOT = project_root()
logger = logging.getLogger(__name__)









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














def status_label(result: FactResult, evaluation: EvaluationRow) -> str:
    if result.status == "unverified":
        code = result.verification.failed_check if result.verification else ""
        return f"Review · {code}"
    if result.status == "not_found":
        return "Not found"
    if result.status == "error" or evaluation.classification == "error":
        return "Error"
    return "Checks passed" if result.mode == "verified" else "Extracted"




def source_evidence(db: sqlite3.Connection, run_id: str, ticker: str, fact: FactResult, evaluation: EvaluationRow) -> None:
    st.subheader("Source evidence")
    evidence_summary = f"{metric_name(fact.metric)} · Extracted {format_number(fact.final_value, fact.metric)} · XBRL {format_number(evaluation.ground_truth, fact.metric)}"
    st.caption(evidence_summary.replace("$", r"\$"))
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
    st.subheader("Measured cost")
    steps, replay = st.columns(2)
    with steps:
        st.markdown(f"**Average verified cost by step · {len(study.companies)} companies**")
        records=average_steps(db,study)
        st.dataframe(pd.DataFrame([{"Step":r["Step"],"Requests":r["Requests"],
            "Avg reference cost / company":f"${r['Avg reference cost / company']:.6f}"} for r in records]),hide_index=True,width="stretch")
    with replay:
        st.markdown("**Verified run and cached replay**")
        pairs=[("Cold verified",study.verified_run),("Cached replay",study.cache_run)]
        usages=[(label,call_usage(db,run,"verified")) for label,run in pairs if run]
        st.dataframe(pd.DataFrame([{"Run":label,"New tokens":f"{u.input_tokens+u.output_tokens:,}","Time":f"{u.seconds:.2f}s",
            "Reference cost":f"${u.cost:.6f}","Cache hit rate":percent(u.hit_rate)} for label,u in usages]),hide_index=True,width="stretch")
    st.caption("Reference-price estimates use stored token usage. Measured time includes free-tier request pacing and recovery waits.")


def main() -> None:
    st.set_page_config(page_title="Diligence Verify", page_icon="✓", layout="wide")
    st.markdown("""<style>
      .block-container {padding-top:1.6rem; max-width:1600px}
      h1 {letter-spacing:-.045em; padding-bottom:.2rem!important}
      h2 {letter-spacing:-.025em}
      [data-testid="stMetric"] {background:#f4f7fb;border:1px solid #dce4ef;border-radius:10px;padding:14px 16px;min-height:110px}
      [data-testid="stMetricValue"] {font-size:1.55rem}
      .source-box {white-space:pre-wrap;overflow:auto;max-height:430px;background:#f7f9fc;
        color:#17283c;border:1px solid #dce3ed;border-radius:8px;padding:16px;
        font-family:ui-monospace,Consolas,monospace;font-size:12px;line-height:1.8}
      .source-box mark {background:#ffe395;color:#17283c;border-radius:3px}
      [data-testid="stMetricLabel"] p {white-space:normal;overflow:visible;text-overflow:clip}
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

            st.markdown("**"+headline(db,studies)+"**")
            wrong_card,precision_card,review_card,base_cost,verified_cost=st.columns(5)
            wrong_card.metric("Wrong answers · baseline → verified",f"{sum(item.wrong for item in baseline)} → {sum(item.wrong for item in verified)}")
            precision_card.metric("Precision · baseline → verified",f"{precision(baseline)} → {precision(verified)}")
            review_card.metric("Flagged for human review",sum(item.unverified for item in verified))
            for card,record in zip([base_cost,verified_cost],cost_rows(db,studies[0]),strict=True):
                card.metric(record['Mode']+" · cost / company",f"${record['Reference cost / company']:.6f}")
                card.caption(f"Average time: {record['Avg time / company (s)']:.2f}s / company")
            st.dataframe(pd.DataFrame(result_rows(db,studies)),hide_index=True,width="stretch")
            st.caption(f"Each row totals {len(companies)*len(metrics)} facts: {len(companies)} companies × {len(metrics)} financial metrics. No-ground-truth cases are included in the total and excluded from precision.")

            all_caught = [error for study in studies for error in caught_errors(db, study)]
            st.subheader("Caught errors")
            if all_caught:
                st.dataframe(pd.DataFrame([{"Company": error.ticker, "Metric": metric_name(error.metric),
                    "Baseline value": format_number(error.baseline_value, error.metric), "XBRL value": format_number(error.ground_truth, error.metric),
                    "Verified outcome": error.outcome, "Caught by": error.first_check, "Source quote": error.quote}
                    for error in all_caught[:5]]), hide_index=True, width="stretch",
                    column_config={"Source quote": st.column_config.TextColumn(width="large"), "Caught by": st.column_config.TextColumn(width="large")})
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
                                 key=f"facts_{run_id}_{ticker}_{mode}", height="auto",
                                 column_config={"Match":st.column_config.TextColumn(width="small"),"Status":st.column_config.TextColumn(width="medium"),"Metric":st.column_config.TextColumn(width="medium")})
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
                st.write(f"One model · {len(companies)} companies · {len(metrics)} financial metrics · 10-K filings only. "
                         "Precision counts accepted answers with matching XBRL ground truth. Missing answers affect coverage. "
                         "Deterministic checks do not guarantee financial correctness on other filings.")
                st.write("Intel section labels remain unknown: its Item labels are in a cross-reference index rather than body headings. "
                         "Whole-document retrieval preserves the evidence but lacks reliable section ranking.")
    except (FileNotFoundError, ValueError, sqlite3.Error) as error:
        logger.exception("ticker=%s step=dashboard mode=%s", st.session_state.get("ticker", "study"), st.session_state.get("mode", "summary"))
        st.error(str(error))


if __name__ == "__main__":
    main()

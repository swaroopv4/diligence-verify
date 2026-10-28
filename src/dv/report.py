"""Database-derived result tables and reproducible Markdown; no model/network calls."""
from __future__ import annotations
import json
import sqlite3
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from dv.config import project_root
from dv.models import EvaluationRow, ModeSummary


@contextmanager
def read_database(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = path or project_root() / "data" / "runs.db"
    if not path.exists():
        raise FileNotFoundError(f"No stored runs database: {path}")
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro",uri=True)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


def summarize(db: sqlite3.Connection, run_id: str, mode: str, metric: str | None = None) -> ModeSummary:
    run = db.execute("SELECT model FROM runs WHERE run_id=?",(run_id,)).fetchone()
    if run is None:
        raise ValueError(f"Unknown run {run_id}")
    params: list[object] = [run_id,mode]
    clause = ""
    if metric:
        clause = " AND metric=?"
        params.append(metric)
    records = db.execute("SELECT result_json FROM evaluations WHERE run_id=? AND mode=?"+clause,params).fetchall()
    rows = [EvaluationRow.model_validate_json(row["result_json"]) for row in records]
    counts = Counter(row.classification for row in rows)
    total = sum(row.ground_truth is not None for row in rows)
    answered = counts["correct"]+counts["wrong"]
    sql = """SELECT count(*) AS calls,COALESCE(sum(cache_hit),0) AS hits,
        COALESCE(sum(input_tokens),0) AS inputs,COALESCE(sum(output_tokens),0) AS outputs,
        COALESCE(sum(cost_actual_usd),0) AS actual,COALESCE(sum(cost_reference_usd),0) AS reference
        FROM llm_calls WHERE run_id=? AND mode=?"""
    usage_params: list[object] = [run_id,mode]
    if metric:
        prefix=metric+".attempt_"
        sql += " AND (step=? OR step=? OR substr(step,1,?)=?)"
        usage_params.extend([metric,metric+".repair",len(prefix),prefix])
    usage = db.execute(sql,usage_params).fetchone()
    timing = db.execute("SELECT AVG(latency_ms)/1000.0 AS average FROM company_timings WHERE run_id=? AND mode=?",(run_id,mode)).fetchone()
    return ModeSummary(run_id=run_id,mode=mode,model=run["model"],correct=counts["correct"],wrong=counts["wrong"],
        unverified=counts["unverified"],not_found=counts["not_found"],error=counts["error"],no_ground_truth=counts["no_ground_truth"],
        total_with_ground_truth=total,precision_on_answered=counts["correct"]/answered if answered else None,
        correct_rate=counts["correct"]/total if total else None,wrong_rate=counts["wrong"]/total if total else None,
        unverified_rate=counts["unverified"]/total if total else None,
        avg_seconds_per_company=timing["average"] if not metric else None,
        input_tokens=usage["inputs"],output_tokens=usage["outputs"],cost_actual_usd=usage["actual"],
        cost_reference_usd=usage["reference"],calls=usage["calls"],cache_hits=usage["hits"],
        cache_hit_rate=usage["hits"]/usage["calls"] if usage["calls"] else None)


def study_runs(db: sqlite3.Connection) -> list[str]:
    selected: dict[str,str] = {}
    for run in db.execute("SELECT * FROM runs ORDER BY created_at DESC,run_id DESC").fetchall():
        config = json.loads(run["settings_json"])
        n = len(config.get("selected_companies",[]))
        if n < len(config["companies"]["full"]) or run["model"] in selected:
            continue
        expected = n*len(config["metrics"])
        counts = dict(db.execute("SELECT mode,count(*) FROM evaluations WHERE run_id=? GROUP BY mode",(run["run_id"],)).fetchall())
        if counts.get("baseline")==expected and counts.get("verified")==expected:
            selected[run["model"]]=run["run_id"]
            if len(selected)==2:
                break
    return sorted(selected.values())


def percent(value: float | None) -> str:
    return f"{value:.1%}" if value is not None else "N/A"


def cache_replays(db: sqlite3.Connection, run_ids: list[str], companies: set[str]) -> list[str]:
    models={db.execute("SELECT model FROM runs WHERE run_id=?",(run_id,)).fetchone()[0] for run_id in run_ids}
    selected: dict[str,str]={}
    for run in db.execute("SELECT * FROM runs ORDER BY created_at DESC,run_id DESC").fetchall():
        if run["run_id"] in run_ids or run["model"] not in models or run["model"] in selected:
            continue
        config=json.loads(run["settings_json"])
        if set(config.get("selected_companies",[]))!=companies:
            continue
        counts=dict(db.execute("SELECT mode,count(*) FROM fact_results WHERE run_id=? GROUP BY mode",(run["run_id"],)).fetchall())
        if counts.get("verified")==len(companies)*len(config["metrics"]) and not counts.get("baseline"):
            selected[run["model"]]=run["run_id"]
    return sorted(selected.values())


def markdown_table(headers: list[str], rows: list[list[object]]) -> str:
    def cell(value: object) -> str:
        return str(value).replace("|",r"\|").replace("\n","<br>")
    lines=["| "+" | ".join(headers)+" |","| "+" | ".join("---" for _ in headers)+" |"]
    lines.extend("| "+" | ".join(cell(value) for value in row)+" |" for row in rows)
    return "\n".join(lines)


def generate_report(run_ids: list[str] | None = None, cache_run_ids: list[str] | None = None,
                    *, db_path: Path | None = None, destination: Path | None = None) -> Path:
    with read_database(db_path) as db:
        if run_ids is None and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='canonical_studies'").fetchone():
            from dv.study import generate_final_report
            return generate_final_report(db,destination or project_root()/"reports"/"results.md")
        run_ids=run_ids or study_runs(db)
        if not run_ids:
            raise ValueError("The report requires a completed, evaluated model comparison")
        studies=[db.execute("SELECT * FROM runs WHERE run_id=?",(run_id,)).fetchone() for run_id in run_ids]
        if any(run is None for run in studies):
            raise ValueError("Report contains an unknown run")
        configs=[json.loads(run["settings_json"]) for run in studies]
        companies=set(configs[0]["selected_companies"])
        if any(set(config["selected_companies"])!=companies for config in configs):
            raise ValueError("Compared models must use the same company cohort")
        if len(run_ids)>1 and len({run["model"] for run in studies})<2:
            raise ValueError("Report requires two different models")
        for key in ("metrics","retrieval","verification","extraction_code_sha256"):
            if any(config.get(key)!=configs[0].get(key) for config in configs):
                raise ValueError(f"Compared runs differ in {key}")
        manifests=[{row["ticker"]:(json.loads(row["filing_json"])["accession"],row["chunk_sha256"])
                    for row in db.execute("SELECT * FROM run_filings WHERE run_id=?",(run_id,))} for run_id in run_ids]
        if any(manifest!=manifests[0] for manifest in manifests):
            raise ValueError("Compared runs differ in source evidence snapshots")
        for run_id,config in zip(run_ids,configs,strict=True):
            expected=len(companies)*len(config["metrics"])
            actual=dict(db.execute("SELECT mode,count(*) FROM evaluations WHERE run_id=? GROUP BY mode",(run_id,)).fetchall())
            if actual.get("baseline")!=expected or actual.get("verified")!=expected:
                raise ValueError(f"Incomplete evaluation for {run_id}")
        summaries=[summarize(db,run_id,mode) for run_id in run_ids for mode in ("baseline","verified")]
        main=[[s.mode,s.model,s.correct,s.wrong,s.unverified,percent(s.precision_on_answered),
               f"{s.avg_seconds_per_company:.3f}s" if s.avg_seconds_per_company is not None else "N/A",
               f"$ {s.cost_reference_usd:.6f}"] for s in summaries]
        sections=["# Diligence Verify results",
            "Generated entirely from stored runs, evaluations, verification attempts and call logs.",
            f"Study: {len(companies)} companies, {len(configs[0]['metrics'])} metrics, "
            +", ".join(sorted({config["filing"]["form"] for config in configs}))+".",
            markdown_table(["Mode","Model","Correct","Wrong","Unverified","Precision on answered","Avg time per company","Cost at reference price"],main),
            "## Coverage and rates",markdown_table(
                ["Mode","Model","With ground truth","Correct rate","Wrong rate","Unverified rate","Not found","Error","No ground truth"],
                [[s.mode,s.model,s.total_with_ground_truth,percent(s.correct_rate),percent(s.wrong_rate),
                  percent(s.unverified_rate),s.not_found,s.error,s.no_ground_truth] for s in summaries])]
        if len(studies)==1:
            sections.insert(1,"**Second-model benchmark pending.** This preliminary report uses one completed model comparison. "
                "Partial secondary-model trials are preserved in SQLite and PROGRESS.md and excluded from accuracy tables.")
        before_wrong=sum(s.wrong for s in summaries if s.mode=="baseline")
        after_wrong=sum(s.wrong for s in summaries if s.mode=="verified")
        outcome=f"Observed XBRL mismatches: {before_wrong} in baseline, {after_wrong} in verified mode. "
        if after_wrong>=before_wrong:
            outcome+="The verified pipeline did not reduce the mismatch count in this sample."
        else:
            outcome+="The verified pipeline reduced the mismatch count; coverage and residual errors are shown below."
        sections.insert(4 if len(studies)>1 else 5,outcome)
        metrics=[]
        for run_id,config in zip(run_ids,configs,strict=True):
            for mode in ("baseline","verified"):
                for metric in config["metrics"]:
                    s=summarize(db,run_id,mode,metric)
                    metrics.append([s.model,s.mode,metric,s.correct,s.wrong,s.unverified,s.not_found,s.error,s.no_ground_truth,percent(s.precision_on_answered)])
        sections.extend(["## Per-metric breakdown",markdown_table(
            ["Model","Mode","Metric","Correct","Wrong","Unverified","Not found","Error","No ground truth","Precision"],metrics),
            "## Observed errors caught by verification"])
        examples=[]
        wrong=[]
        for run_id in run_ids:
            for record in db.execute("SELECT result_json FROM evaluations WHERE run_id=? AND mode='baseline' AND classification='wrong'",(run_id,)).fetchall():
                b=EvaluationRow.model_validate_json(record["result_json"])
                wrong.append([b.model,b.ticker,b.metric,b.final_value,b.ground_truth,b.source_quote or ""])
                paired=db.execute("SELECT result_json FROM evaluations WHERE run_id=? AND mode='verified' AND ticker=? AND metric=?",(run_id,b.ticker,b.metric)).fetchone()
                v=EvaluationRow.model_validate_json(paired["result_json"]) if paired else None
                failed=db.execute("""SELECT verification_json FROM verification_attempts WHERE run_id=? AND ticker=? AND metric=?
                    AND json_extract(verification_json,'$.passed')=0 ORDER BY attempt LIMIT 1""",(run_id,b.ticker,b.metric)).fetchone()
                if v and v.classification in {"correct","unverified","not_found"} and failed:
                    f=json.loads(failed["verification_json"])
                    examples.append(f"### {b.ticker} — {b.metric} — {b.model}\n\nBaseline: {b.final_value}; XBRL: {b.ground_truth}. "
                        f"Verified: {v.classification}, value: {v.final_value}.\n\nFailed {f['failed_check']}: {f['reason']}.\n\n"
                        f"> {(b.source_quote or '').replace(chr(10),chr(10)+'> ')}\n\nVerified quote:\n\n"
                        f"> {(v.source_quote or 'No accepted quote').replace(chr(10),chr(10)+'> ')}")
        sections.append(f"Qualifying paired examples observed: {len(examples)}; shown: {min(5,len(examples))}.")
        sections.extend(examples[:5] or ["No qualifying baseline-wrong/verified-caught pairs were observed."])
        if len(examples)<5:
            sections.append("Fewer than the requested five examples occurred; no examples or errors were invented.")
        sections.extend(["## All wrong baseline rows for review",markdown_table(
            ["Model","Ticker","Metric","Extracted","XBRL","Quote"],wrong) if wrong else "No wrong baseline rows.",
            "## Cost, timing and cache",markdown_table(
            ["Run","Mode","Input tokens","Output tokens","Actual cost","Reference cost","Calls","Cache hits","Hit rate"],
            [[s.run_id,s.mode,s.input_tokens,s.output_tokens,f"$ {s.cost_actual_usd:.6f}",f"$ {s.cost_reference_usd:.6f}",
              s.calls,s.cache_hits,percent(s.cache_hit_rate)] for s in summaries]),
            "Reference prices are frozen per run. Timings include retry waits; interpret them alongside cache-hit rates. "
            "Tables cover the listed benchmark run IDs; preflights and abandoned trials remain in the audit database. "
            "Both modes share the identical first-attempt extraction/cache. Actual cost is recorded as zero for configured free tiers; "
            "reference cost is a hypothetical paid-token estimate. Failed calls without usage report zero known tokens."])
        cache_rows=[]
        replay_ids=cache_run_ids if cache_run_ids is not None else cache_replays(db,run_ids,companies)
        for cache_id in replay_ids:
            warm=db.execute("SELECT * FROM runs WHERE run_id=?",(cache_id,)).fetchone()
            if warm is None:
                raise ValueError(f"Unknown cache replay {cache_id}")
            config=json.loads(warm["settings_json"])
            if set(config["selected_companies"])!=companies:
                raise ValueError("Cache replay cohort differs from the comparison")
            expected=len(companies)*len(config["metrics"])
            count=db.execute("SELECT count(*) FROM fact_results WHERE run_id=? AND mode='verified'",(cache_id,)).fetchone()[0]
            if count!=expected:
                raise ValueError("Cache replay is incomplete")
            original=next((s for s in summaries if s.model==warm["model"] and s.mode=="verified"),None)
            if original is None:
                raise ValueError("Cache replay model is absent from the main comparison")
            replay=summarize(db,cache_id,"verified")
            cache_rows.append([cache_id,warm["model"],replay.input_tokens+replay.output_tokens,
                f"$ {replay.cost_reference_usd:.6f}",percent(replay.cache_hit_rate),
                f"$ {original.cost_reference_usd-replay.cost_reference_usd:.6f}",
                f"{replay.avg_seconds_per_company:.3f}s" if replay.avg_seconds_per_company is not None else "N/A"])
        sections.extend(["### Verified replay with the same settings",markdown_table(
            ["Replay","Model","New tokens","Reference cost","Hit rate","Reference cost saved vs first verified run","Avg time/company"],cache_rows)
            if cache_rows else "A completed cache replay has not been supplied."])
        flags=[]
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='consistency_flags'").fetchone():
            for run_id in run_ids:
                for row in db.execute("SELECT ticker,metric,flag_json FROM consistency_flags WHERE run_id=?",(run_id,)):
                    f=json.loads(row["flag_json"])
                    flags.append([run_id,row["ticker"],row["metric"],f["table_value"],f["prose_value"],f["prose_quote"]])
        sections.extend(["## Consistency review leads",
            "These heuristic flags may reflect rounding, segments or component amounts; they do not alter accuracy.",
            markdown_table(["Run","Ticker","Metric","Verified table","Nearby prose","Prose quote"],flags) if flags else "No recorded flags.",
            "## Limitations",
            f"- Free hosted models, {len(companies)} companies and the configured form type(s); results describe this sample.",
            "- Model architectures and generation settings differ across model families; compare the recorded configurations. Open-model parameter counts describe total rather than necessarily active parameters.",
            "- XBRL tag coverage can be incomplete. Missing ground truth is excluded and shown separately; accession matching is never relaxed.",
            "- Configured parent-attributable income/equity tags can differ from consolidated totals including noncontrolling interests. Segment/component values are also distinct from company totals.",
            "- Quote, number, scale, year and sanity checks cannot prove that a quoted row/column denotes the requested financial concept.",
            "- Conservative checks can abstain on correct financial values when scale or quotation validation fails.",
            "- Some filings require whole-document section fallback or incorporate statements by reference; source coverage affects retrieval.",
            "- Provider errors and free quotas affect coverage and time. Zero known usage on an error does not prove the server did no work."])
        if all(s.wrong==0 for s in summaries if s.mode=="baseline"):
            sections.append("Completed baseline wrong rates were zero. No reduction in wrong answers was demonstrated; report the harder-cohort follow-up honestly.")
        sections.extend(["## Reproducibility","Main run IDs: "+", ".join(run_ids)+".",
            "Re-run dv report with these run IDs and optional cache run IDs. All result numbers are recomputed from SQLite."])
        content="\n\n".join(sections)+"\n"
    destination=destination or project_root()/"reports"/"results.md"
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(content,encoding="utf-8")
    return destination

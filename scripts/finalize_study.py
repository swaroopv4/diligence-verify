"""Promote audited measurements and replay only stored verified responses."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from dv.config import LLMSettings, project_root
from scripts.cold_benchmark import MeasuredClient, evaluate_isolated

ROOT = project_root()


def import_database(source: Path, destination: Path) -> None:
    """Copy audit rows transactionally, preserving the existing research history."""
    with sqlite3.connect(source) as incoming, sqlite3.connect(destination) as target:
        for name, sql in incoming.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            target.execute(sql.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1))
            columns = [row[1] for row in incoming.execute(f'PRAGMA table_info("{name}")')]
            if name == "llm_cache":
                continue  # Hosted dashboard needs audit/result rows, not private working caches.
            if name == "llm_calls":
                columns.remove("id")
            names = ",".join(f'"{column}"' for column in columns)
            records = incoming.execute(f'SELECT {names} FROM "{name}"').fetchall()
            if name == "llm_calls":
                run_ids = {record[columns.index("run_id")] for record in records}
                for run in run_ids:
                    target.execute("DELETE FROM llm_calls WHERE run_id=?", (run,))
            target.executemany(f'INSERT OR REPLACE INTO "{name}" ({names}) VALUES ({",".join("?" for _ in columns)})', records)


def cached_replay() -> str:
    import dv.pipeline as pipeline

    folder = ROOT / ".deploy-check/benchmarks/cold-final-verified-v1"
    path = folder / "data/runs.db"
    run = "cached-final-verified-v1"
    with sqlite3.connect(path) as db:
        if db.execute("SELECT 1 FROM runs WHERE run_id=?", (run,)).fetchone():
            raise ValueError("Replay ID already exists; preserve its original timing")
        entries = db.execute("SELECT count(*) FROM llm_cache").fetchone()[0]
        db.execute("INSERT INTO benchmark_runs VALUES (?,?,?,?,?,?,?)", (run,"verified","cached",entries,"cold-final-verified-v1","gemini-3.5-flash-lite",0))

    def client(settings: LLMSettings, unused: Path) -> MeasuredClient:
        return MeasuredClient(settings,path,allow_network=False)

    original = pipeline.LLMClient
    try:
        pipeline.LLMClient = client
        pipeline.run_extraction(run,"verified","full",model="gemini-3.5-flash-lite")
    finally:
        pipeline.LLMClient = original
    evaluate_isolated(folder,run)
    with sqlite3.connect(path) as db:
        usage = db.execute("SELECT count(*),sum(cache_hit),sum(input_tokens)+sum(output_tokens) FROM llm_calls WHERE run_id=?",(run,)).fetchone()
        assert usage[0] == usage[1] and usage[2] == 0
        originals = [json.loads(row[0]) for row in db.execute("SELECT result_json FROM fact_results WHERE run_id='cold-final-verified-v1' ORDER BY ticker,metric")]
        replays = [json.loads(row[0]) for row in db.execute("SELECT result_json FROM fact_results WHERE run_id=? ORDER BY ticker,metric",(run,))]
        for result in originals + replays:
            result.pop("run_id")
        assert originals == replays, "Cached replay differs from the policy-corrected cold results"
    return run


def promote() -> None:
    destination = ROOT / "data/runs.db"
    for mode in ("verified","baseline"):
        import_database(ROOT/f".deploy-check/benchmarks/cold-final-{mode}-v1/data/runs.db", destination)
    with sqlite3.connect(destination) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS canonical_studies (
            model TEXT PRIMARY KEY,baseline_run TEXT,verified_run TEXT,cache_run TEXT,status_policy TEXT)""")
        db.execute("INSERT OR REPLACE INTO canonical_studies VALUES (?,?,?,?,?)",(
            "gemini-3.5-flash-lite","cold-final-baseline-v1","cold-final-verified-v1","cached-final-verified-v1","retain_failure_on_null_retry_v1"))


if __name__ == "__main__":
    print("Cached replay:",cached_replay())
    promote()
    print("Promoted the two cold runs and identical cached replay into data/runs.db")

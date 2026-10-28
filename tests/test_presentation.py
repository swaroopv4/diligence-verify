"""Reader-facing summaries agree and retain the original database measurements."""
import json
import re
import sqlite3
from pathlib import Path

from dv.config import project_root
from dv.report import format_cost, format_seconds, markdown_table, read_database
from dv.study import (
    REVIEW_LABEL, cost_rows, generate_final_report,
    generate_readme, headline, result_rows, review_summary, select_studies,
)


def test_readme_and_report_share_database_summary(tmp_path: Path) -> None:
    root = project_root()
    database_before = (root / "data/runs.db").read_bytes()
    with read_database() as db:
        studies = select_studies(db)
        count, caption = review_summary(db, studies)
        assert (count, caption) == (3, "includes 2 caught baseline errors")
        rows = result_rows(db, studies)
        table = markdown_table(list(rows[0]), [list(row.values()) for row in rows])
        title = headline(db, studies)
        costs = cost_rows(db, studies[0])
        for generate in (generate_readme, generate_final_report):
            target = tmp_path / f"{generate.__name__}.md"
            generate(db, target)
            text = target.read_text(encoding="utf-8")
            assert text == (root / ("README.md" if generate == generate_readme else "reports/results.md")).read_text(encoding="utf-8")
            assert table in text and title in text
            assert f"{REVIEW_LABEL}: {count}" in text and caption in text
            for row in costs:
                assert format_cost(row['Reference cost / company']) in text
                assert format_seconds(row['Avg time / company (s)']) in text
            assert not re.search(r"\d+\.\d+s\b", text)
            assert not re.search(r"\$\d+\.\d{3,}", text)
        # These are display conversions, not rounded cost/timing calculations.
        assert costs[0]['Reference cost / company'] != 0.11
        assert costs[0]['Avg time / company (s)'] != 45

    assert (root / "data/runs.db").read_bytes() == database_before


def test_review_counts_follow_database_changes() -> None:
    with read_database() as source, sqlite3.connect(":memory:") as db:
        source.backup(db)
        db.row_factory = sqlite3.Row
        studies = select_studies(db)
        study = studies[0]
        assert review_summary(db, studies) == (3, "includes 2 caught baseline errors")
        # Removing one baseline error changes only the caught-error subset.
        record = db.execute("""SELECT b.rowid, b.result_json FROM evaluations b
            JOIN evaluations v ON v.ticker=b.ticker AND v.metric=b.metric
            WHERE b.run_id=? AND b.mode='baseline' AND b.classification='wrong'
            AND v.run_id=? AND v.mode='verified' AND v.classification='unverified' LIMIT 1""",
            (study.baseline_run, study.verified_run)).fetchone()
        payload = json.loads(record['result_json'])
        payload['classification'] = 'correct'
        db.execute("UPDATE evaluations SET classification='correct', result_json=? WHERE rowid=?",
                   (json.dumps(payload), record['rowid']))
        assert review_summary(db, studies) == (3, "includes 1 caught baseline errors")
        # An additional abstention changes the total independently of baseline errors.
        record = db.execute("SELECT rowid, result_json FROM evaluations WHERE run_id=? AND mode='verified' AND classification='correct' LIMIT 1",
                            (study.verified_run,)).fetchone()
        payload = json.loads(record['result_json'])
        payload['classification'] = 'unverified'
        db.execute("UPDATE evaluations SET classification='unverified', result_json=? WHERE rowid=?",
                   (json.dumps(payload), record['rowid']))
        assert review_summary(db, studies) == (4, "includes 1 caught baseline errors")

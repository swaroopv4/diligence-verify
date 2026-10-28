"""Reports are reproducibly recomputed from database values, including coverage."""
import json
import pytest
from pathlib import Path
from dv.config import load_config
from dv.llm import LLMClient
from dv.models import EvaluationRow
from dv.pipeline import prepare_database
from dv.report import generate_report,read_database,summarize


def test_report_uses_database_and_recomputes(tmp_path: Path) -> None:
    path=tmp_path/"runs.db"
    config=load_config()
    settings=config.model_dump()
    settings["selected_companies"]=["TEST"]
    settings["metrics"]={"revenue":settings["metrics"]["revenue"]}
    with LLMClient(config.llm,path,[]) as client:
        db=client.db
        prepare_database(db)
        db.execute("CREATE TABLE evaluations (run_id TEXT,mode TEXT,ticker TEXT,metric TEXT,classification TEXT,result_json TEXT)")
        for run,model in [("a","small"),("b","large")]:
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)",(run,"fake",model,"hash",json.dumps(settings)))
            for mode in ["baseline","verified"]:
                row=EvaluationRow(run_id=run,mode=mode,ticker="TEST",metric="revenue",provider="fake",model=model,
                                  final_value=100,ground_truth=100,ground_truth_tag="Test",classification="correct",
                                  extraction_status="answered",source_quote="Revenue | 100")
                db.execute("INSERT INTO evaluations VALUES (?,?,?,?,?,?)",(run,mode,"TEST","revenue","correct",row.model_dump_json()))
                db.execute("INSERT INTO company_timings VALUES (?,?,?,?)",(run,"TEST",mode,1000))
        db.commit()
    output=tmp_path/"results.md"
    generate_report(["a","b"],db_path=path,destination=output)
    before=output.read_text(encoding="utf-8")
    assert "| baseline | small | 1 | 0 | 0 | 100.0% |" in before
    assert "No wrong baseline rows." in before
    generate_report(["a","b"],db_path=path,destination=output)
    assert output.read_text(encoding="utf-8")==before
    generate_report(["a"],db_path=path,destination=output)
    assert "Second-model benchmark pending" in output.read_text(encoding="utf-8")
    with read_database(path) as db:
        summary=summarize(db,"a","baseline")
        assert summary.total_with_ground_truth==1
        assert summary.wrong_rate==0
        assert summary.avg_seconds_per_company==1
    import sqlite3
    with sqlite3.connect(path) as db:
        row=EvaluationRow(run_id="a",mode="baseline",ticker="TEST",metric="revenue",provider="fake",model="small",
                          final_value=200,ground_truth=100,ground_truth_tag="Test",classification="wrong",
                          extraction_status="answered",source_quote="Revenue | 200")
        db.execute("UPDATE evaluations SET classification='wrong',result_json=? WHERE run_id='a' AND mode='baseline'",(row.model_dump_json(),))
        db.commit()
    generate_report(["a","b"],db_path=path,destination=output)
    after=output.read_text(encoding="utf-8")
    assert "| baseline | small | 0 | 1 | 0 | 0.0% |" in after
    assert "Revenue \\| 200" in after
    assert after!=before
    settings["retrieval"]["top_k"]+=1
    with sqlite3.connect(path) as db:
        db.execute("UPDATE runs SET settings_json=? WHERE run_id='b'",(json.dumps(settings),))
        db.commit()
    with pytest.raises(ValueError,match="retrieval"):
        generate_report(["a","b"],db_path=path,destination=output)

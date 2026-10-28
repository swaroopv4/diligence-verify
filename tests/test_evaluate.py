"""Accuracy denominators, status labels and exact tolerance boundaries."""
import pytest
from dv.evaluate import classify_fact
from dv.models import ExtractedFact,FactResult,GroundTruthResult


@pytest.mark.parametrize(("metric","value","expected","status","label"),[
    ("revenue",100,100,"answered","correct"),
    ("revenue",100.5,100,"answered","correct"),
    ("revenue",100.50001,100,"answered","wrong"),
    ("net_income",-100.5,-100,"answered","correct"),
    ("net_income",-101,-100,"answered","wrong"),
    ("net_income",0,0,"answered","correct"),
    ("net_income",0.001,0,"answered","wrong"),
    ("eps_diluted",1.01,1,"answered","correct"),
    ("eps_diluted",1.01001,1,"answered","wrong"),
    ("revenue",None,100,"unverified","unverified"),
    ("revenue",None,100,"not_found","not_found"),
    ("revenue",None,100,"error","error"),
    ("revenue",None,100,"answered","error"),
    ("revenue",100,None,"answered","no_ground_truth"),
])
def test_classification(metric: str,value: float | None,expected: float | None,status: str,label: str) -> None:
    fact=ExtractedFact(metric=metric,value_as_written=None,scale_as_written=None,period_end=None,source_chunk_id=None,source_quote=None)
    result=FactResult(run_id="r",mode="baseline",ticker="TEST",metric=metric,fact=fact,verification=None,
                      attempts=1,status=status,final_value=value)
    truth=GroundTruthResult(ticker="TEST",metric=metric,value=expected,tag="Test" if expected is not None else None,
                            unit="USD",accession="acc",period_end="2025-12-31",status="matched" if expected is not None else "no_ground_truth")
    row=classify_fact(result,truth,"fake","model",0.005,0.01)
    assert row.classification==label
    assert row.extraction_status==status

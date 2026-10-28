"""Command line entry point. Phase gates control which commands are implemented."""
import logging
import sys
from typing import Literal
from uuid import uuid4

import typer

app = typer.Typer(no_args_is_help=True, help="Diligence Verify: financial extraction with code verification.")


@app.callback()
def configure_console() -> None:
    """Keep real SEC quotations printable in redirected Windows console output."""
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,"reconfigure"):
            stream.reconfigure(encoding="utf-8",errors="backslashreplace")


def pending(phase: int) -> None:
    typer.echo(f"Not implemented: requires Phase {phase} and all preceding gates.", err=True)
    raise typer.Exit(2)


@app.command()
def groundtruth(ticker: str = typer.Option(..., help="Public company ticker")) -> None:
    """Fetch the SEC XBRL answer key (evaluation only)."""
    from dv.evaluate import inspect_groundtruth

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        rows = inspect_groundtruth(ticker.upper())
    except Exception as error:
        typer.echo(f"SEC ground truth failed: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo("metric\tvalue\tunit\ttag\tstatus")
    for row in rows:
        typer.echo(f"{row.metric}\t{row.value}\t{row.unit}\t{row.tag}\t{row.status}")
    count = sum(row.value is not None for row in rows)
    typer.echo(f"Matched {count}/{len(rows)} metrics")
    if count < 7:
        raise typer.Exit(1)


@app.command()
def ingest(ticker: str = typer.Option(...)) -> None:
    """Download and chunk the latest 10-K."""
    from dv.ingest import ingest_filing

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        chunks = ingest_filing(ticker)
    except Exception as error:
        typer.echo(f"Ingestion failed: {error}", err=True)
        raise typer.Exit(1) from error
    sections = sorted({chunk.section for chunk in chunks})
    tables = [chunk for chunk in chunks if chunk.is_table and chunk.detected_scale]
    maximum = max((len(chunk.text) for chunk in chunks), default=0)
    typer.echo(f"{ticker.upper()}: chunks={len(chunks)} sections={sections} scaled_tables={len(tables)} max_chars={maximum}")
    samples = sorted(tables, key=lambda chunk: chunk.section != "item_8")[:3]
    for chunk in samples:
        typer.echo(f"\n{chunk.chunk_id} scale={chunk.detected_scale}\n{chunk.text}")
    if not {"item_7", "item_8"} <= set(sections) or not tables or maximum > 8000:
        typer.echo("Phase 2 live gate failed", err=True)
        raise typer.Exit(1)


@app.command("llm-smoke")
def llm_smoke() -> None:
    """Test each configured free or local provider."""
    from typing import Literal
    from pydantic import BaseModel
    from dv.config import load_config, project_root
    from dv.llm import CallContext, LLMClient, configured_providers

    class SmokeResult(BaseModel):
        ok: Literal[True]

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = load_config().llm
    providers = configured_providers(settings)
    if not providers:
        typer.echo("DISABLED: no configured free/local provider. Set a model in config.yaml and start its endpoint.", err=True)
        raise typer.Exit(1)
    passed = 0
    for provider in providers:
        with LLMClient(settings, project_root() / "data" / "runs.db", [provider]) as client:
            context = CallContext(run_id="llm-smoke", mode="smoke", ticker="-", step="smoke")
            try:
                client.complete('Return only JSON: {"ok": true}', SmokeResult, context)
                row = client.db.execute("SELECT * FROM llm_calls ORDER BY id DESC LIMIT 1").fetchone()
                typer.echo(f"PASS {provider.name} model={provider.model} input_tokens={row['input_tokens']} output_tokens={row['output_tokens']} latency_ms={row['latency_ms']} cache_hit={bool(row['cache_hit'])}")
                passed += 1
            except Exception as error:
                typer.echo(f"DISABLED {provider.name} model={provider.model}: {error}", err=True)
    if not passed:
        raise typer.Exit(1)


@app.command()
def run(mode: Literal["baseline", "verified"] = typer.Option(...), companies: Literal["dev", "full"] = "dev",
        run_id: str | None = None, model: str | None = None) -> None:
    """Extract financial metrics and persist resumable results."""
    from dv.pipeline import run_extraction

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    run_id = run_id or uuid4().hex
    typer.echo(f"run_id={run_id}")
    try:
        results = run_extraction(run_id, mode, companies, model)
    except Exception as error:
        typer.echo(f"Run failed: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo("ticker\tmetric\tvalue_as_written\tfinal_value\tstatus\tattempts")
    for row in results:
        typer.echo(f"{row.ticker}\t{row.metric}\t{row.fact.value_as_written}\t{row.final_value}\t{row.status}\t{row.attempts}")
    typer.echo(f"Stored {len(results)} valid FactResult rows")
    if any(row.status == "error" for row in results):
        raise typer.Exit(1)


@app.command("eval")
def evaluate_run(run_id: str = typer.Option(...)) -> None:
    """Evaluate stored results against independently matched XBRL facts."""
    from collections import Counter
    from dv.evaluate import evaluate_stored_run

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    rows = evaluate_stored_run(run_id)
    for mode in ("baseline", "verified"):
        counts = Counter(row.classification for row in rows if row.mode == mode)
        typer.echo(f"{mode}: {dict(counts)}")
    for row in rows:
        if row.classification == "wrong" or row.evaluation_error:
            typer.echo(f"REVIEW {row.mode} {row.ticker} {row.metric}: value={row.final_value} ground_truth={row.ground_truth} tag={row.ground_truth_tag}\nquote={row.source_quote}\nerror={row.evaluation_error}")


@app.command()
def consistency(run_id: str = typer.Option(...)) -> None:
    """List deterministic prose/table red flags; never change accuracy results."""
    from dv.consistency import scan_run

    flags = scan_run(run_id)
    typer.echo(f"Consistency red flags: {len(flags)}")
    for flag in flags:
        typer.echo(f"{flag.ticker} {flag.metric}: table={flag.table_value} prose={flag.prose_value}\n{flag.table_quote}\n{flag.prose_quote}")


@app.command()
def report(run_id: list[str] = typer.Option([], "--run-id"),
           cache_run_id: list[str] = typer.Option([], "--cache-run-id")) -> None:
    """Generate the results report entirely from stored run data."""
    from dv.report import generate_report

    typer.echo(str(generate_report(run_id or None, cache_run_id or None)))


if __name__ == "__main__":
    app()

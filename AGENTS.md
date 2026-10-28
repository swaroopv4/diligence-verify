# AGENTS.md: Diligence Verify

Instructions for the coding agent (Codex or Cursor). Read this whole file before writing any code.

## Background: who this is for and why

### The audience

This project is a showcase for **Lunon** (lunon.ai), an early-stage AI-native consulting firm founded in 2026 by three Carnegie Mellon students. It raised about $2M in pre-seed funding led by General Catalyst and has a small team based in New York and Pittsburgh.

### What Lunon does

- **Diligence for private equity:** commercial due diligence before a firm buys a company, and vendor due diligence when it sells. This means reading private documents (filings, pitch decks, financial statements, call transcripts) and producing reports that investment committees rely on.
- **Strategy work:** market assessments, market entry, growth strategy.
- **Forward deployed engineering:** engineers embedded inside mid-market and private-equity-owned companies (roughly 100 to 2,000 employees) to build AI systems on the client's own data and software (ERP, CRM, accounting), then hand them over.
- **Business model:** fixed-price services engagements, scoped before work starts. They do not sell software and do not build their own models.

### Their technology

- They route each task step to whichever outside model fits best (Claude, GPT, Nemotron, DeepSeek), so they are not tied to one model vendor.
- Their open-source research system, **Lunon Deep Research** (github.com/LunonAI/lunon-deep-research, Python, MIT license), runs a four-stage pipeline: plan, research with five parallel agents, write, edit. It uses a typed `PipelineState` passed between stages and a memory bank of evidence.
- Their core selling point is trust: **"every citation is verified against its source and every number checked by code, not by another model."**
- Their public pipeline works on **web sources**. Their paid diligence work runs on **private documents**.

### The gap this project fills

1. **Verification on private documents.** Their public pipeline checks web citations. This project shows the same code-based checking applied to financial documents, which is what diligence actually depends on. One wrong number in diligence can change a deal decision.
2. **Proof with numbers.** Anyone can claim "verified." This project measures how often plain LLM extraction gets financial numbers wrong, using SEC XBRL data as an independent answer key, and shows how much code verification reduces that.
3. **Cost visibility.** Lunon sells fixed-price engagements, so its profit depends on how cheaply and quickly each engagement runs. Its pipeline does not report cost or time per step. This project tracks tokens, cost, time and cache savings for every call.
4. **Less dependence on paid model vendors.** Everything here runs on free or local models, which shows the approach works without OpenAI or Anthropic. Those vendors are now also Lunon's competitors through their own consulting arms.

### What this means for design choices

- **Correctness and auditability come before features.** Every number must trace back to an exact quote and pass code checks. Saying "unverified" is better than a confident wrong answer.
- **The comparison must be fair**, or a technical reader at Lunon will dismiss it. Same model, same retrieved text, same prompt for both modes.
- **Results must be honest.** Report limitations plainly. Do not tune anything to make the baseline look worse.
- **Keep it compatible with their stack:** Python, typed data models, model choice set in config, nothing locked to one vendor.
- **The output should be easy for a busy engineer to judge in 2 minutes:** one results table, a few clear examples of caught errors, and a cost summary.

## 0. Mission

Build a Python app that:

1. Downloads SEC 10-K filings for a set of public companies.
2. Uses an LLM to extract key financial numbers from the filing text, each with an exact source quote.
3. Verifies every extracted number with deterministic code (no LLM in the verifier).
4. Measures accuracy against SEC XBRL data, which acts as the answer key.
5. Compares two modes: `baseline` (plain LLM extraction) and `verified` (extraction plus code verification plus retry).
6. Tracks tokens, cost, time and cache hits for every LLM call.
7. Shows results in a simple Streamlit demo.

Everything must run on free model tiers or local models.

The final headline output is a results table like this:

| Mode | Model | Correct | Wrong | Unverified | Precision on answered | Avg time per company | Cost at reference price |
|---|---|---|---|---|---|---|---|

## 1. Rules for the coding agent

1. **Work phase by phase.** Do not start a phase until the previous phase gate passes.
2. **After each phase**, append to `PROGRESS.md`: phase number, what was built, gate commands run, gate output summary, known issues.
3. **Fix loop.** If a gate fails: read the error, fix the cause, rerun the gate. Maximum 3 attempts per failure. If it still fails, write a `BLOCKED` section in `PROGRESS.md` with the error, what you tried, and 2 possible options. Then stop and wait for the user.
4. **No answer key leakage.** XBRL ground truth (`groundtruth.py`) is used ONLY in `evaluate.py`. Never import it in extraction, retrieval, verification or the pipeline. Never use edgartools XBRL objects or its parsed financial statement objects for extraction. Extraction reads filing text and HTML only.
5. **No secrets in code.** Read keys from `.env`. Commit `.env.example` only.
6. **No silent failures.** Every exception is logged with ticker, step and mode. A failed company never crashes the whole run. It is recorded as failed and the run continues.
7. **Tests never call the network or an LLM.** Use fixtures in `tests/fixtures/` and a fake LLM provider.
8. **Type hints everywhere. Pydantic v2 models for all structured data.**
9. **Do not add features that are not in this spec.**
10. **Temperature 0 for every LLM call.**

## 2. Stack

- Python 3.11 or newer
- `edgartools` (download filings and filing HTML/text only)
- `httpx` (SEC API calls)
- `pydantic` v2
- `openai` Python SDK (used as a client for all OpenAI-compatible endpoints: Gemini, Groq, OpenRouter, Ollama)
- `tenacity` (retries with backoff)
- `rank-bm25` (retrieval)
- `beautifulsoup4` and `lxml` (HTML cleanup and table conversion)
- `sqlite3` from the standard library (cache and run logs)
- `pyyaml`, `python-dotenv`, `pandas`, `typer` (CLI)
- `pytest`
- `streamlit`

## 3. Repo layout

```
diligence-verify/
  AGENTS.md
  PROGRESS.md
  README.md
  config.yaml
  .env.example
  pyproject.toml
  src/dv/
    __init__.py
    config.py          # load config.yaml and .env
    models.py          # all Pydantic models
    sec_client.py      # SEC HTTP client with user agent and rate limiting
    groundtruth.py     # XBRL answer key (evaluation only)
    ingest.py          # download 10-K, clean HTML, split into sections
    chunk.py           # table-aware chunking, scale detection
    retrieve.py        # BM25 retrieval per metric
    llm.py             # providers, fallback chain, cache, cost tracking
    prompts.py         # extraction and retry prompts
    extract.py         # baseline extraction
    numbers.py         # number parsing and normalization
    verify.py          # deterministic verifier checks V1 to V7
    pipeline.py        # baseline and verified modes
    consistency.py     # cross-section red flags (Phase 6)
    evaluate.py        # compare against ground truth
    report.py          # markdown report and tables
    cli.py             # typer CLI
  app/
    streamlit_app.py
  tests/
    fixtures/
    test_*.py
  data/
    raw/               # downloaded filings
    processed/         # chunks as JSONL
    runs.db            # sqlite: cache, LLM call log, results
  reports/
    results.md
```

## 4. Config

`config.yaml`:

```yaml
sec:
  user_agent_env: SEC_USER_AGENT     # format: "Full Name email@example.com"
  max_requests_per_second: 8         # SEC limit is 10, stay under it

companies:
  dev: [AAPL, MSFT, CRM]
  full: [AAPL, MSFT, GOOGL, AMZN, META, NVDA, ADBE, CRM, ORCL, INTC, CSCO, IBM, NFLX, INTU, NOW]

filing:
  form: 10-K
  which: latest

llm:
  temperature: 0
  max_output_tokens: 2000
  timeout_seconds: 120
  providers:                         # order = fallback chain
    - name: gemini
      base_url: https://generativelanguage.googleapis.com/v1beta/openai/
      api_key_env: GEMINI_API_KEY
      model: FILL_IN_CURRENT_FREE_MODEL
    - name: groq
      base_url: https://api.groq.com/openai/v1
      api_key_env: GROQ_API_KEY
      model: FILL_IN_CURRENT_FREE_MODEL
    - name: openrouter
      base_url: https://openrouter.ai/api/v1
      api_key_env: OPENROUTER_API_KEY
      model: FILL_IN_CURRENT_FREE_MODEL
    - name: ollama
      base_url: http://localhost:11434/v1
      api_key_env: null
      model: FILL_IN_LOCAL_MODEL
  reference_prices_per_million:      # used only to estimate paid cost
    input: 3.00
    output: 15.00

retrieval:
  top_k: 5
  retry_extra_k: 5

verification:
  max_retries: 2
  relative_tolerance: 0.005          # 0.5 percent
  eps_absolute_tolerance: 0.01

metrics:
  revenue:
    kind: duration
    unit: USD
    query: "total net revenue sales net sales total revenues"
    xbrl_tags: [RevenueFromContractWithCustomerExcludingAssessedTax, Revenues, SalesRevenueNet, RevenueFromContractWithCustomerIncludingAssessedTax]
  net_income:
    kind: duration
    unit: USD
    query: "net income net earnings"
    xbrl_tags: [NetIncomeLoss]
  operating_income:
    kind: duration
    unit: USD
    query: "operating income income from operations"
    xbrl_tags: [OperatingIncomeLoss]
  operating_cash_flow:
    kind: duration
    unit: USD
    query: "net cash provided by operating activities"
    xbrl_tags: [NetCashProvidedByUsedInOperatingActivities]
  eps_diluted:
    kind: duration
    unit: USD/shares
    query: "diluted earnings per share diluted net income per share"
    xbrl_tags: [EarningsPerShareDiluted]
  total_assets:
    kind: instant
    unit: USD
    query: "total assets balance sheet"
    xbrl_tags: [Assets]
  total_liabilities:
    kind: instant
    unit: USD
    query: "total liabilities"
    xbrl_tags: [Liabilities]
  cash:
    kind: instant
    unit: USD
    query: "cash and cash equivalents"
    xbrl_tags: [CashAndCashEquivalentsAtCarryingValue]
  stockholders_equity:
    kind: instant
    unit: USD
    query: "total stockholders equity shareholders equity"
    xbrl_tags: [StockholdersEquity, StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest]
```

`.env.example`:

```
SEC_USER_AGENT="Your Name your@email.com"
GEMINI_API_KEY=
GROQ_API_KEY=
OPENROUTER_API_KEY=
```

The user fills in current free model names. If a model name is `FILL_IN...`, skip that provider and log a warning.

## 5. Core data models (`models.py`)

```python
class Chunk(BaseModel):
    chunk_id: str            # f"{ticker}_{accession}_{section}_{n:04d}"
    ticker: str
    accession: str
    section: str             # e.g. "item_7", "item_8"
    text: str
    is_table: bool
    detected_scale: Literal["units", "thousands", "millions", "billions"] | None
    scale_excludes_per_share: bool   # True if header says "except per share"

class ExtractedFact(BaseModel):
    metric: str
    value_as_written: str | None     # exact characters from the text, e.g. "(1,234.5)"
    scale_as_written: str | None     # e.g. "in millions", or None
    period_end: str | None           # ISO date of fiscal period end
    source_chunk_id: str | None
    source_quote: str | None         # exact substring of the chunk, max 300 chars

class VerificationResult(BaseModel):
    passed: bool
    failed_check: str | None         # "V1" to "V7"
    reason: str | None
    normalized_value: float | None   # final value in base units (USD or USD/share)

class FactResult(BaseModel):
    run_id: str
    mode: Literal["baseline", "verified"]
    ticker: str
    metric: str
    fact: ExtractedFact
    verification: VerificationResult | None    # None in baseline mode
    attempts: int
    status: Literal["answered", "unverified", "not_found", "error"]
    final_value: float | None

class LLMCall(BaseModel):
    run_id: str
    mode: str
    ticker: str
    step: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cache_hit: bool
    cost_actual_usd: float           # 0 on free tiers
    cost_reference_usd: float        # tokens times reference price
```

## 6. Runtime loops (how the app itself handles failure)

### 6.1 LLM call loop (`llm.py`)

```
for provider in fallback_chain:
    check cache (key = sha256(provider, model, prompt, temperature)) -> return if hit
    try up to 3 times with exponential backoff (2s, 4s, 8s) on 429, 5xx, timeout
    on success: validate JSON against Pydantic schema
        if invalid: one repair attempt (send the validation error back, ask for corrected JSON only)
        if still invalid: treat as provider failure
    on success: write cache, log LLMCall row, return
    on failure: log, move to next provider
if all providers fail: raise AllProvidersFailed
```

**Pinned mode:** when `pin_model=True` (always during evaluation), do not move to another provider. On exhaustion, wait 60 seconds and retry, up to 5 times, then mark that company as `error` and continue. This keeps one model per evaluation run so results stay comparable.

### 6.2 Per-fact verification loop (`pipeline.py`, verified mode)

```
chunks = retrieve(metric, top_k)
for attempt in 1..(1 + max_retries):
    fact = extract(metric, chunks)
    if fact.value_as_written is None: status = not_found, break
    result = verify(fact, chunk_store)
    if result.passed: status = answered, final_value = result.normalized_value, break
    else:
        feedback = f"Previous answer failed {result.failed_check}: {result.reason}"
        chunks = chunks + retrieve(metric, next retry_extra_k)
        extract again with feedback
if never passed: status = unverified, final_value = None
```

Baseline mode: one extraction call, schema validation only, no verifier, no retry. `final_value` is computed by parsing `value_as_written` with the scale the model reported. Same chunks, same model, same base prompt as verified mode attempt 1.

### 6.3 Run resume

Every `FactResult` is written to `runs.db` immediately. On restart with the same `run_id`, skip (ticker, metric, mode) combinations already stored.

## 7. Verifier checks (`verify.py`)

Run in order. Stop at the first failure.

| Check | Rule |
|---|---|
| V1 | `source_chunk_id` exists in the chunk store for this filing |
| V2 | `source_quote` is an exact substring of the chunk text after whitespace normalization (collapse spaces, normalize unicode quotes and dashes) |
| V3 | `value_as_written` appears inside `source_quote` |
| V4 | `numbers.parse(value_as_written)` returns a number |
| V5 | Scale: reported scale must match `chunk.detected_scale`. For `eps_diluted`, scale must be units and `scale_excludes_per_share` handling applied. If the chunk has no detected scale and the number has no word scale ("billion"), fail with reason "scale unknown" |
| V6 | Period: the fiscal year of `period_end` appears in the chunk text or its table header |
| V7 | Sanity: revenue > 0, abs(eps) < 1000, cash <= total assets when both are known for the same filing |

`normalized_value = parsed_number * scale_multiplier` except EPS, which is never scaled.

### `numbers.py` parsing rules

- Remove `$`, commas, spaces.
- `(1,234)` means negative.
- A leading minus sign means negative.
- Word scales: "thousand", "million", "billion" (and "k", "m", "bn" when next to a number).
- A cell that is only a dash, em dash (`\u2014`) or en dash (`\u2013`) means "no value": return None.
- Footnote markers like `(1)` directly after a number are stripped, but only when the number before them is valid. Do not confuse them with negative numbers.
- Percentages are rejected for these metrics.

Write at least 25 unit tests for `numbers.py`, covering every rule above.

## 8. Ground truth (`groundtruth.py`, evaluation only)

- Source: `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json` with the `SEC_USER_AGENT` header.
- For each metric, try `xbrl_tags` in order and use the first tag that has a matching fact.
- Matching rules:
  - unit must match (`USD` or `USD/shares`)
  - `accn` must equal the 10-K accession number being evaluated
  - `end` must equal the filing's fiscal period end date (`period_of_report`)
  - duration metrics: `start` exists and the period length is between 350 and 380 days
  - instant metrics: no `start`
- If several facts match, take the first one and log a warning. If none match, the metric is `no_ground_truth` and is excluded from accuracy.

## 9. Evaluation (`evaluate.py`)

For each (ticker, metric, mode) with ground truth:

- `correct`: final_value within tolerance (relative 0.5 percent, or absolute 0.01 for EPS)
- `wrong`: final_value present but outside tolerance
- `unverified`: verified mode gave up
- `not_found` and `error`: counted separately

Report per mode and per model:

- Correct rate = correct / total with ground truth
- **Wrong rate** = wrong / total with ground truth (the key number)
- Unverified rate
- **Precision on answered** = correct / (correct + wrong)
- Avg time per company, total tokens, cost at reference price, cache hit rate

Run on two models (one small, one larger) so the result does not depend on one model.

## 10. Phases and gates

### Phase 0: Setup

Build: repo layout, `pyproject.toml`, config loading, `.env.example`, empty modules, `PROGRESS.md`, `README.md` with setup steps.

Gate:
- `pip install -e .` succeeds
- `pytest` runs (zero tests is fine)
- `python -m dv.cli --help` lists commands

Fallback: if `edgartools` fails to install, pin an older version and note it in `PROGRESS.md`.

### Phase 1: SEC client and ground truth

Build: `sec_client.py` (user agent header, rate limit, retries), ticker to CIK lookup, `groundtruth.py`, CLI command `dv groundtruth --ticker AAPL`.

Gate:
- `pytest tests/test_groundtruth.py` passes using a saved companyfacts JSON fixture (save one real response to `tests/fixtures/` once)
- tests cover: tag fallback order, duration vs instant matching, accession filtering, no-match case
- live smoke: `dv groundtruth --ticker AAPL` prints all 9 metrics with at least 7 non-null values

Fallback: if fewer than 7 values match, print every candidate fact for the missing metrics (tag, start, end, accn, form) and fix the matching logic. Do not loosen the accession rule.

### Phase 2: Ingestion and chunking

Build: download latest 10-K HTML with edgartools, clean HTML, split into Items (1, 1A, 7, 7A, 8 at minimum). Table-aware chunking:
- tables converted to pipe-separated text with rows on separate lines
- a table is one chunk if under 6,000 characters, otherwise split by rows with the header rows repeated in every piece
- text chunks about 1,500 characters with 200 character overlap
- scale detection: search the table header and the 3 lines above the table for "in thousands", "in millions", "in billions", and "except per share"

Save chunks to `data/processed/{ticker}_{accession}.jsonl`. CLI: `dv ingest --ticker AAPL`.

Gate:
- unit tests for table conversion, chunk ids, scale detection (use small HTML fixtures)
- live smoke for the 3 dev companies: Item 7 and Item 8 found, at least 1 table chunk with `detected_scale` set, no chunk over 8,000 characters
- print 3 sample table chunks to the console for a manual check

Fallback: if Items are not found by heading, fall back to edgartools section helpers if available. If still missing, chunk the whole document and tag sections as "unknown". Log which companies used the fallback.

### Phase 3: LLM layer

Build: `llm.py` with the provider abstraction, fallback chain, pinned mode, cache, JSON repair, `LLMCall` logging to `runs.db`, and a `FakeProvider` for tests.

Gate:
- tests with `FakeProvider`: fallback order on 429, cache hit on repeat call, JSON repair path, pinned mode does not switch providers, `LLMCall` row written with correct cost math
- live smoke: `dv llm-smoke` sends one tiny JSON request to each configured provider and prints provider, model, tokens, latency

Fallback: if a provider fails the live smoke, mark it disabled in the console output and continue. At least one provider must pass.

### Phase 4: Retrieval and baseline extraction

Build: BM25 index per filing, metric queries from config with a boost for Item 8 table chunks. Extraction prompt in `prompts.py`:
- give the chunks with their ids
- ask for JSON matching `ExtractedFact` for one metric
- `value_as_written` and `source_quote` must be copied exactly, never computed or rounded
- return nulls if the value is not in the given text
- state the fiscal period end date the filing covers

CLI: `dv run --mode baseline --companies dev`.

Gate:
- unit tests for retrieval ranking on a fixture filing
- live: baseline run on 3 dev companies writes 27 `FactResult` rows, every row valid, `LLMCall` rows logged
- print a table of ticker, metric, value_as_written, final_value

Fallback: if more than 30 percent of facts are `not_found`, print the top retrieved chunk ids for those metrics and improve queries or the Item 8 boost. Do not change the prompt to guess values.

### Phase 5: Verifier and verified mode

Build: `numbers.py`, `verify.py`, verified loop in `pipeline.py` exactly as in section 6.2.

Gate:
- at least 25 tests for `numbers.py`
- at least one passing and one failing test for each check V1 to V7
- live: `dv run --mode verified --companies dev` writes 27 rows, the attempts column shows retries happened where checks failed, every `answered` row has a passing verification
- print each failed check with its reason for review

Fallback: if more than 50 percent of facts end `unverified`, print the failed check counts. If one check causes most failures, inspect 3 examples and decide if the check or the chunk data is wrong. Fix the root cause. Never weaken a check just to raise the pass rate without writing why in `PROGRESS.md`.

### Phase 6: Consistency red flags (do only if time allows)

Build: for each answered fact, scan Item 7 text chunks for the same metric mentioned in prose (keyword plus a nearby number). Parse with `numbers.py`. If it differs beyond tolerance after scaling, record a red flag with both quotes. No LLM in this step. Red flags never change accuracy numbers.

Gate: unit test with a fixture where prose and table disagree. Live run lists red flags (zero is a valid result).

### Phase 7: Evaluation and report

Build: `evaluate.py`, `report.py`. CLI: `dv eval --run-id ...` and `dv report`.

Steps:
1. Evaluate on the 3 dev companies. Check every `wrong` row by hand in the console output (value, ground truth, quote).
2. If the ground truth itself looks wrong for a row, fix matching in `groundtruth.py`, not the pipeline.
3. Run full 15 companies, both modes, model A (pinned).
4. Repeat with model B (pinned).
5. Run verified mode a second time with the same run settings to show cache savings.

`reports/results.md` must contain:
- results table (section 0 format) for both models
- per-metric breakdown
- 5 examples where baseline was wrong and verified mode caught it, with quotes and the failed check
- cost and time summary, and cache savings from the second run
- limitations: free models, 15 companies, one form type, XBRL tag coverage

Gate: report file exists, all numbers in it are recomputed from `runs.db` by `report.py` (no hand-typed numbers), and `pytest` passes.

Fallback: if baseline wrong rate is 0 on both models, report that honestly, then add the larger company list or 10-Q filings to test harder cases. Do not change models only to make baseline look worse.

### Phase 8: Streamlit demo

Build: `app/streamlit_app.py`:
- pick ticker and mode
- facts table: metric, value, status badge (verified, unverified, failed check), source quote, ground truth, match
- click a row to see the full source chunk with the quote highlighted
- cost per step bar chart from `LLMCall` rows
- red flags list if Phase 6 was done
- summary results table at the top

Reads only from `runs.db` and processed chunks. No live LLM calls in the app.

Gate: `streamlit run app/streamlit_app.py` loads without errors for all dev companies. Take 2 screenshots and save them to `reports/`.

### Phase 9: Lunon repo integration (optional)

1. Clone `github.com/LunonAI/lunon-deep-research` into `third_party/` (do not vendor it into `src/`).
2. Read its code and write a short summary in `PROGRESS.md`: where LLM calls happen, how `PipelineState` and the memory bank store evidence.
3. **Before editing anything, list the exact files you plan to change and stop for user approval.**
4. Write an adapter that converts `answered` facts into their evidence format, behind a config flag, without changing their core logic.
5. Separate branch for the upstream pull request: add per-call token, cost and latency logging around their LLM calls, plus a summary printed at the end of a run. No behavior change. Add tests following their test style.

Gate: their existing tests still pass, and one task runs end to end with free models configured through their env variables.

## 11. Definition of done

- `pytest` passes
- `reports/results.md` generated from data
- Streamlit demo runs
- `README.md` explains setup, how to run each phase, and the headline result in 3 sentences
- `PROGRESS.md` has every phase with gate results

# Diligence Verify progress

The supplied AGENTS.md is the implementation specification. Later phases must not
start until the preceding gate passes. No accuracy results have been collected.

## Phase 0 — setup (passed)

Built isolated project layout, editable package, validated Pydantic v2 configuration,
core data models, environment template, CLI command inventory and setup instructions.
Gate commands (project virtual environment, 2026-10-27):

- `python -m pip install -e .`: exit 0; edgartools 5.62.1 installed without fallback.
- `python -m pytest`: exit 0; 3 configuration tests passed in 0.41s.
- `python -m dv.cli --help`: exit 0; lists groundtruth, ingest, llm-smoke,
  run, eval and report.

Known issues: later-phase commands are explicit stubs until their gates are reached.
The SEC contact identity supplied by the user is stored in the ignored project
`.env`. No Ollama executable, local model manifests or running localhost endpoint
was found during environment discovery; this may block Phase 3.

## Phase 1 — SEC client and ground truth (passed)

Built user-agent validation, 8 requests/second throttle, transient HTTP retries,
ticker/CIK lookup, latest 10-K metadata lookup (including historical submissions),
strict accession/period/unit/duration matching and missing-match diagnostics.
Only `evaluate.py` imports the answer-key module in application code; the CLI
delegates its groundtruth command to that evaluation-only entry point.

Gate commands:

- `python -m pytest tests/test_groundtruth.py tests/test_sec_client.py tests/test_config.py`:
  exit 0; 26 tests passed in 0.49s, including 17 ground-truth tests.
- `python -m dv.cli groundtruth --ticker AAPL`: exit 0; all 9/9 metrics matched
  accession `0000320193-25-000079`, fiscal period end 2025-09-27. Full console
  output: `reports/phase1-live-attempt1.txt`.

Saved the complete actual SEC response once as `tests/fixtures/AAPL_companyfacts.json`
and the matching filing metadata as `tests/fixtures/AAPL_filing.json`. Tests never
download data: a global socket guard rejects accidental network access.
Companyfacts SHA256: `6B4380F07CF6045408BE419CF7D78A5D90D08C28CB86FEF6C78C7105622FD784`.
Source: https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json.
Known issues: none for this phase. Full evaluation/reporting remains Phase 7.

## Phase 2 — ingestion and chunking (passed)

Built raw-HTML-only downloads through EdgarTools, removal of hidden inline-XBRL
content, Item boundaries, pipe-separated tables, repeated table headers on row
splits, 1,500-character prose chunks with overlap, local scale detection and JSONL
persistence. EdgarTools' HTML section helper is the first fallback, followed by
explicit `unknown` sections; no dev company needed a fallback.

Gate commands:

- `python -m pytest tests/test_chunk.py`: exit 0; 13 tests passed in 0.47s.
- `python -m dv.cli ingest --ticker AAPL`: exit 0; 236 chunks, 35 scaled tables,
  maximum 4,604 characters.
- `python -m dv.cli ingest --ticker MSFT`: exit 0; 430 chunks, 65 scaled tables,
  maximum 3,275 characters.
- `python -m dv.cli ingest --ticker CRM`: exit 0; 436 chunks, 68 scaled tables,
  maximum 4,485 characters.

All three contain Items 1, 1A, 7, 7A and 8. Three sample financial table chunks per
company were printed for review; saved console outputs are
`reports/phase2-{AAPL,MSFT,CRM}-final.txt`. Manual inspection found MSFT sometimes
renders closing negative-number parentheses in separate HTML cells; table cleanup
now joins that punctuation to its numeric cell, with a regression test. Header,
year and scale text remain in every applicable table chunk.
Known issues: oversized individual table rows fail explicitly rather than silently
truncating columns. No such row occurred in the dev companies.

## Phase 3 — LLM layer (passed)

Built compatible SDK providers, placeholder/key skipping, 3-attempt transient
backoff, fallback chain, pinned provider recovery (five 60-second waits), one JSON
repair, schema-validated persistent cache and per-attempt SQLite audit rows.
Every provider call uses temperature 0; SDK-internal retries are disabled so the
audit logger observes every actual attempt. Cache hits record zero newly consumed
tokens/reference cost. Failed transport attempts record an explicit error type;
token usage is zero when the server did not provide usage.

Gate commands:

- `python -m pytest tests/test_llm.py --tb=short`: 11 passed in 1.86s. Initial
  failures came from an inaccessible host pytest temp directory, then its missing
  replacement parent. Fixed by assigning fresh project-local scratch directories
  with a containment check. No network or model is called by tests.
- Live attempt 1, `python -m dv.cli llm-smoke`: correctly failed because every
  configured model was still a placeholder and no Ollama installation was found.
- The user then authorized the existing Groq API key. Copied only `GROQ_API_KEY`
  into the ignored project `.env` without displaying it. Queried Groq's live model
  listing: `openai/gpt-oss-20b` and `openai/gpt-oss-120b` are available; configured
  the former as the initial model and reserved the latter for the larger-model run.
- Live attempt 2, same command: exit 0; Groq gpt-oss-20b passed, 123 input tokens,
  91 output tokens, 967 ms. Other placeholders explicitly reported disabled.
  Output: `reports/phase3-live-attempt2.txt`.

Implementation references checked: official OpenAI Python/chat-completion docs and
https://console.groq.com/docs/models. Known issues: free-tier rate limits can add
recovery waits during larger runs; no paid-tier quota or pricing is assumed.

## Phase 4 — retrieval and baseline extraction (passed)

Built a per-filing BM25Plus index with a 1.5x Item 8 table boost, exact-quote
extraction prompts, pinned extraction, baseline number/scale normalization,
immediate fact commits, source/settings/code fingerprints and run resume.
Baseline normalization requires the shared number parser now; deterministic
verification and its exhaustive parser/verifier test gates remain Phase 5.

Gate work so far:

- Initial retrieval tests exposed negative BM25Okapi scores, for which multiplying
  by a table boost demoted relevant tables. Switched to BM25Plus (positive IDF).
  Both fixture-ranking checks now pass, including identical-text table boosting.
- Stopped exploratory live run `dev-20b-v1` after two facts to avoid mixing retrieval
  implementations. Its records are retained for audit and excluded from final
  comparisons. Restarted with run ID `dev-20b-v2`.
- `python -m pytest --tb=short`: exit 0; 58 tests passed in 2.42s. Tests include
  first-answer parity across modes, immediate SQLite commits, import-boundary
  enforcement and resume without re-extraction.
- Live gate passed: `python -m dv.cli run --mode baseline --companies dev --run-id dev-20b-v2`.
  Output: `reports/phase4-live-attempt2.txt`. Free-tier 8,000 TPM responses cause
  the specified pinned recovery waits; no model fallback occurs.
- Exit 0: 27 valid rows (9 per dev company), all answered with one extraction
  attempt; zero not-found and zero error rows. Full ticker/metric/display/base-unit
  table printed at the end of the saved output. LLM audit rows recorded throughout.

Known issues: the live gate took about 17 minutes because of free-tier recovery
waits. An answered baseline row is a model output, not a verified/correct claim.
Results/report/demo gates are still outstanding.

## Phase 5 — verifier and verified mode (passed after Gemini resume)

Built ordered deterministic checks V1–V7, exact-quote normalization, scale and EPS
handling, fiscal-date/year checks, sanity relationships, retry feedback with the
next five chunks and abstention after three failed checks. Every verification
attempt is persisted so a later successful answer does not erase caught errors.
V6 also rejects a reported fiscal date different from the filing's actual fiscal
end; merely finding a comparative year in a table is insufficient.

Gate commands and fixes so far:

- `python -m pytest tests/test_numbers.py tests/test_verify.py --tb=short`: initially
  72 passed, including 48 parser/normalization cases; subsequently removed six
  redundant repetitions of the full passing verifier path. Each check has a
  positive path through the full verifier and explicit negative cases.
- Added three fake-provider pipeline tests for added-chunk feedback/retry,
  abstention after three failures and stopping on a null fact.
- Full suite after fixes: 130 passed in 2.94s; no test network/model calls.
- Live attempt 1 (`dev-20b-v2`) stopped after V5 exposed a per-share header issue.
  Extended scale-exclusion detection beyond a 50-character cap, added a regression
  fixture and refreshed chunk metadata. The first-attempt prompt/text stayed unchanged.
- Live attempt 2 (`dev-20b-v3`) exposed a second legitimate EPS header form:
  `net income in millions and shares in thousands`. The scale is explicitly
  scoped to those components, so EPS is excluded; detector now recognizes that
  scoped wording when the header identifies earnings per share. Three actual dev
  EPS source chunks were inspected. V5 itself remains strict about units.
- Attempt 2 also caught a true provenance error (MSFT net income's displayed
  currency/value was not an exact substring of its quote, V3); retry corrected it.
  Other enlarged requests hit Groq HTTP 413 (8,000 TPM, requested 8,145) and a
  provider JSON-mode HTTP 400. Stopped for a concrete request-size fix: retries
  retain all evidence/schema constraints while removing redundant wording and
  JSON Schema display titles; repair no longer repeats an already-given schema.
  First-attempt prompts remain byte-for-byte unchanged and are covered by tests.
- Added content-addressed chunk snapshots for new runs, so future metadata
  corrections cannot overwrite a run's evidence. Preserved matching historical
  snapshots. Abandoned v1/v2 AAPL snapshots had already changed metadata before
  this fix and are excluded from final comparisons; original filing HTML remains.
- Third live gate: fresh `dev-20b-v4`, baseline first (same cached first answers),
  then verified. Outputs: `reports/phase5-final-baseline.txt` and
  `reports/phase5-live-attempt3.txt`.

Known issues: Groq's free request/token capacity can be smaller than the required
expanded retrieval context. If the third attempt remains blocked, obey the supplied
three-attempt limit and stop before Phase 6/7/8.

### BLOCKED — Phase 5 live gate, third attempt

Date: 2026-10-27 (America/Los_Angeles).

`python -m dv.cli run --mode verified --companies dev --run-id dev-20b-v4`
cannot complete the required 27-row live gate. On MSFT net income, the baseline
and second extraction both failed V3: the model's displayed value did not occur
exactly in its quoted source. The required third extraction adds the next five
chunks, which Groq rejects before generation:

```text
HTTP 413: Request too large for model openai/gpt-oss-20b
tokens per minute (TPM): Limit 8000, Requested 9924
code: rate_limit_exceeded
```

This is an individual request-size rejection, so waiting for the rolling token
allowance to refill cannot make that same request fit. Stopped the owned Python
process rather than continuing known-impossible capacity retries. Incomplete facts
remain pending, not fabricated or falsely marked verified.

What was tried across the three live gate attempts:

1. Preserved full V1–V7 checks; diagnosed and fixed the long per-share exclusion
   header, with a fixture based on real visible filing text.
2. Inspected all three dev EPS chunks, fixed explicitly scoped numerator/share
   scales, and preserved the previous comparison evidence. Observed successful
   correction of a currency/quote mismatch on an earlier attempt.
3. Kept identical first-attempt prompts; compacted only retry wording/schema
   display labels, removed redundant repair schema text and reran under a new
   immutable source snapshot. The required 15-chunk context still exceeds Groq's
   free capacity. No retrieved evidence was removed and no check was weakened.

Verified local state at stop: run `dev-20b-v4` has all 27 baseline facts and 10
answered verified facts (AAPL 9, MSFT 1). Every answered verified fact has a passing
verification. MSFT net income's two failed attempts are retained in
`verification_attempts`. These counts are extraction/verification status, not
accuracy measurements against XBRL.

Final offline gate: `python -m pytest --tb=short` — 130 passed in 2.79s. Output:
`reports/phase5-tests-final.txt`. Third live trace:
`reports/phase5-live-attempt3.txt`. The source snapshots and SQLite database remain
available under `data/`; provider keys remain only in the ignored `.env`.

Two options to unblock:

1. Configure a free API provider/model whose per-request capacity accommodates the
   expanded context (at least this 9,924-token request, with room for repair).
   Rerun both modes pinned to that same model; do not mix providers within a comparison.
2. Set up a local Ollama model with sufficient context, then rerun both modes
   pinned to it. This avoids the hosted free-tier request cap.

Stopped as required by supplied AGENTS.md §1.3. Awaiting the user's choice.
Phases 6, 7, 8 and optional 9 have not started. There is no generated accuracy
report or Streamlit demo yet; the project's definition of done has not been met.

### Phase 5 resumed — user selected Gemini

The user explicitly chose the existing Gemini key to resolve the Groq capacity
block. Copied only `GEMINI_API_KEY` into the ignored project environment, without
displaying it. The live model inventory includes `gemini-3.5-flash-lite` and
`gemini-3.8-flash`; Google's current pricing documentation lists free-tier input
and output for both. Selected Flash-Lite as the lightweight model and Flash as
the higher-capacity comparison tier (parameter counts are not published).

`python -m dv.cli llm-smoke`: exit 0; Gemini 3.5 Flash-Lite passed, 23 input tokens,
9 output tokens, 1,564 ms. Other provider placeholders explicitly skipped.
New comparison ID: `dev-gemini-lite-v1`; both modes use the same pinned model,
retrieved evidence and first-attempt prompt. Existing Groq runs are preserved.
References checked: https://ai.google.dev/gemini-api/docs/models,
https://ai.google.dev/gemini-api/docs/pricing and
https://ai.google.dev/gemini-api/docs/openai.

### Phase 5 final gate — passed

The first Gemini run reached 27 rows in both modes but exposed a schema-validation
gap: a retry returned metric `total revenue` rather than `revenue`, which was
rejected outside the JSON-repair path. Fixed this by specializing the expected
metric as a Pydantic Literal in the response schema for both modes. It now receives
the same one-repair handling as other schema errors; no verifier rule changed.
Added a regression test and reran both modes under a fresh model/schema snapshot.

- `python -m pytest --tb=short`: exit 0; 131 passed in 3.00s.
- `python -m dv.cli run --mode baseline --companies dev --run-id dev-gemini-lite-v2`:
  exit 0; 27 answered rows, no not-found/error rows.
- `python -m dv.cli run --mode verified --companies dev --run-id dev-gemini-lite-v2`:
  exit 0; 27 valid rows, 23 answered and 4 unverified, no errors. All 23 answered
  rows have passing verification. Retried facts include all three EPS cases,
  MSFT cash and MSFT stockholders' equity; the latter answered on attempt 2.
- Every failed check/reason printed in `reports/phase5-gemini-verified-v2.txt`.
  Test output: `reports/phase5-gemini-tests.txt`.

Unverified rate is below the 50% diagnostic threshold. The checks conservatively
reject missing/incorrect EPS scales and nonexact source quotations, even when a
displayed number may be financially correct. Accuracy is not inferred from these
status counts; independent evaluation is still required in Phase 7. Earlier
BLOCKED sections above are retained as historical audit entries and are resolved
for the Gemini comparison.

## Phase 6 — consistency red flags (passed)

Built deterministic, same-year Item 7 prose scans near metric labels with explicit
word scales (or dollar-denominated EPS), and stored both the verified-table and
prose quotes. No LLM is used. Flags are review leads only and never mutate facts
or accuracy labels. Sentence boundaries/nearest-amount selection avoid associating
an adjacent metric's amount or a comparative prior-year amount with the label.

- `python -m pytest tests/test_consistency.py --tb=short`: exit 0; fixture with
  disagreeing prose/table passes, also checks matching values, other years and
  avoiding an EPS-to-cash-flow cross-sentence false association.
- `python -m dv.cli consistency --run-id dev-gemini-lite-v2`: exit 0; 5 heuristic
  review flags printed and stored. Output: `reports/phase6-live.txt`.
- Manual output inspection prompted tightening from a broad nearby-number window
  to sentence-local nearest amounts; initial derived flags were recomputed.

Known limitation: nearby amounts can still concern a segment/component or rounded
prose. These are explicitly described as possible scope/rounding discrepancies,
not proven financial errors.

## Phase 7 — evaluation and report (passed in user-approved single-model scope)

Built independent stored-run evaluation, using frozen metric/tolerance settings,
strict SEC accession/year/unit matching, Decimal tolerance comparisons and
separate correct/wrong/unverified/not-found/error/no-ground-truth labels. XBRL
imports remain confined to `evaluate.py` in application code. Missing ground truth
and evaluation download failures are explicit and excluded from accuracy.

`python -m dv.cli eval --run-id dev-gemini-lite-v2`: exit 0. The dev answer key
matched all metrics: baseline 27 correct; verified 23 correct, 4 unverified.
There were zero wrong rows to review. Output: `reports/phase7-dev-evaluation.txt`.
The database/evaluation check corrected an earlier manually counted Phase 5
summary of 22/5 to the actual 23/4; the stored results were unchanged.

Preparing all remaining full-cohort filings before the two independent pinned
model runs, so both models read the same processed evidence snapshots.

### Phase 7 implementation and full-cohort runs

All 15 filings downloaded successfully. INTC, CSCO, INTU and NOW used the specified
whole-document/unknown-section fallback; this is retained and will be disclosed.
No source text was altered to manufacture harder baseline errors.

Built database-derived headline/coverage/per-metric tables, paired caught-error
examples, wrong-row review, cost/time/cache summaries and limitations. Reports
refuse differing cohorts, metric/retrieval/verification settings, extraction-code
hashes or source snapshots. They display fewer examples honestly if fewer than
five baseline-wrong/verified-caught pairs occurred.

- `python -m pytest tests/test_evaluate.py tests/test_report.py --tb=short`:
  15 passed; includes exact tolerance boundaries, negative/zero targets, missing
  ground truth and reproducible report regeneration after changing stored data.
- Full run A: `full-gemini-lite-v1`, pinned `gemini-3.5-flash-lite`.
- Gemini 3.8 Flash failed preflight with repeated HTTP 503 high-demand errors.
  Gemini 3.6 Flash passed preflight and began full run B, `full-gemini-flash-v1`,
  pinned `gemini-3.6-flash`. This availability substitution occurred before model
  B's benchmark, not to change measured baseline quality; no model switching is
  allowed inside either run.
- Output traces: `reports/phase7-ingestion.txt`, `reports/phase7-full-lite.txt`,
  `reports/phase7-full-flash.txt`. Free request-per-minute waits and temporary
  provider unavailability remain visible in call logs and company timings.

### Phase 7 availability follow-up and first full evaluation

Gemini 3.6 produced a partial Apple baseline but repeated service-unavailable and
quota failures prevented steady progress. Retained that incomplete trial and
stopped it before evaluating its accuracy. Gemini 2.5 Flash passed the compatible
JSON preflight and was selected for the second full comparison:
`full-gemini-flash25-v1`, pinned `gemini-2.5-flash` in both modes. Availability,
not baseline accuracy, drove this change. Both final model tiers expose no public
parameter counts and differ in generation; report this limitation plainly.

First completed full run, `full-gemini-lite-v1`:

- Baseline: 135 rows, 114 answered and 21 not-found.
- Verified: 135 rows, 105 answered, 21 not-found, 9 unverified; no processing errors.
- Independent evaluation: baseline 109 correct, 5 wrong, 17 not-found and 4
  no-ground-truth; verified 100 correct, 5 wrong, 17 not-found, 9 unverified and
  4 no-ground-truth. Output: `reports/phase7-full-lite-evaluation.txt`.
- Manually inspected every wrong baseline value, XBRL value, quote and full source
  context. All five are scope/definition mismatches: Intel net income includes
  noncontrolling income whereas the configured NetIncomeLoss is parent-attributable;
  Intel operating income selected the Intel Products segment; Intel and Oracle
  equity selected totals including noncontrolling interests; Netflix cash selected
  the Cash component rather than total cash plus money-market/time-deposit equivalents.
  These source tables confirm the configured XBRL targets, so matching was unchanged.
  The deterministic checks missed these semantic distinctions. No numerical
  accuracy gain is claimed for this model.
- A Windows redirected-output encoding error during manual source review was
  corrected by enabling UTF-8 for CLI streams; review then completed successfully.
- Verified cache replay `full-gemini-lite-cache-v1`: 135 identical fact/verification
  outcomes, 166/166 cache hits, zero new tokens and zero reference cost. Replay
  output: `reports/phase7-lite-cache.txt`. This uses a new run ID rather than the
  resume mechanism, ensuring the cache is actually exercised.
- Full offline suite at this point: 147 passed in 4.00s.

### Phase 7 free-quota resolution — Gemma pair

The live Gemini 2.5 Flash response confirmed a hard **20 requests/day** free quota,
exhausted after its preflight and 19 baseline facts. Stopped that partial trial and
preserved its audit data; no model change occurs within a comparison run.

Google's hosted Gemma 4 models are free, and provide a clearer small/larger pair:
`gemma-4-26b-a4b-it` (26B total, 4B active mixture of experts) and `gemma-4-31b-it`
(31B dense). The first Gemma default-thinking preflight emitted thought tags in
content, which correctly failed JSON validation. Added Google's documented,
configurable `thinking_level: minimal` plus `include_thoughts: false` using the
OpenAI-compatible extra-body field. Temperature remains 0. Cache identities include
the thinking setting, and run metadata records it. Default/unset behavior and
historical cache identities remain unchanged.

Both Gemma models then passed tiny JSON preflight under the minimal setting.
Primary full-cohort comparisons are now `full-gemma26-v1` and `full-gemma31-v1`,
with the same thinking setting, source snapshots and prompts in both modes.
The earlier completed Flash-Lite comparison remains available as supplementary
data. Availability/quota constraints drove model selection before evaluating the
new models' accuracy; the negative Flash-Lite findings remain unchanged.

References checked: https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api,
https://ai.google.dev/gemini-api/docs/openai (Thinking), and
https://ai.google.dev/gemini-api/docs/pricing (Gemma 4 free input/output).

### Phase 7 approved scope change and final gate

The user explicitly chose: **"Finish report and demo now; mark second benchmark
pending"** after the runtime estimate. This supersedes the original two-completed-
models gate for this delivery. Stopped the two owned Gemma jobs and retained every
partial fact/call/source snapshot. No unfinished model results are presented as
completed accuracy measurements. Gemini/Flash/Gemma quota and server-error trials
remain in the audit database and traces. Diagnostic attempts disabling forced JSON
did not solve server reliability and are not used in the delivered configuration.

The delivered report selects the completed `full-gemini-lite-v1` comparison and
the completed `full-gemini-lite-cache-v1` replay. It prominently marks the second
model pending. Default configuration is restored to the working Flash-Lite model.
Configurable Google thinking controls remain available for later Gemma resumption;
both main Gemma trials used minimal thinking and temperature 0.

- `python -m pytest --tb=short`: exit 0; **149 passed in 6.24s**.
- `python -m dv.cli report`: exit 0; `reports/results.md` generated from SQLite,
  including all requested tables, actual observed errors, cache savings and limits.
- There were **zero** observed baseline-wrong/verified-caught pairs in the completed
  study. The report says so instead of inventing five examples. It lists all five
  missed baseline mismatches for review and states that the verified pipeline did
  not reduce the mismatch count. The all-zero-baseline fallback does not apply.
- The report is now complete for the approved scope; the second-model benchmark
  remains pending. Phase 8 may proceed under the user's explicit instruction.

## Phase 8 — passed in the approved scope

- Read-only Streamlit demo runs at http://127.0.0.1:8511, with the pending second-model benchmark disclosed prominently.
- All 30 company/mode views (15 companies × two modes) load with nine facts each and no exceptions. Validation logs: reports/phase8-apptest.txt and reports/phase8-all-views.txt.
- Browser validation covered row selection, highlighted source evidence, filing links, verification status, XBRL mismatch display, and the reference cost chart. Screenshots: reports/demo-overview.jpg and reports/demo-evidence.jpg.
- Final test suite: **151 passed in 6.80s**, recorded in reports/final-tests.txt.
- Report regeneration is byte-identical (SHA256 639286df2305fff94e96a58d16f289b7111c78779f0bef8eecc1da14163930d1).

## Phase 9 — optional, not selected

Upstream integration was not requested. No external publication or integration was performed.

## Delivery

The report and demo are complete in the user's approved scope. The original second-model benchmark remains pending; partial trials and their audit records are preserved. The completed study retained five XBRL mismatches in each mode and demonstrated no numerical mismatch reduction.

## Phase 5b diagnosis

Step 1 completed before application or test code changes. Sources: immutable full-gemini-lite-v1 FactResults, stored evaluations, verification_attempts and run_filings chunk snapshots. No live LLM or ground-truth changes were used for diagnosis.

### Wrong rows (both modes, all requested fields)

#### verified

- **INTC / net_income**
  - value_as_written: `26`; final_value: `26000000.0`; XBRL value: `-267000000.0`; tag: `NetIncomeLoss`.
  - source_chunk_id: `INTC_0000050863-26-000011_unknown_0390`.
  - source_quote: `Net income (loss) |  | 26 |`.
  - Actual row label: `Net income (loss)`; column header: `Dec 27, 2025`.
  - Classification: Ground truth scope mismatch: selected consolidated income including NCI; NetIncomeLoss is parent-attributable (-267 million). Both are valid disclosed concepts; the configured metric uses the parent concept.

- **INTC / operating_income**
  - value_as_written: `12.7`; final_value: `12700000000.0`; XBRL value: `-2214000000.0`; tag: `OperatingIncomeLoss`.
  - source_chunk_id: `INTC_0000050863-26-000011_unknown_0162`.
  - source_quote: `Total Intel Products operating income was $12.7 billion in 2025`.
  - Actual row label: `Total Intel Products operating income (prose subject)`; column header: `2025 (prose; no table column)`.
  - Classification: Wrong row or concept: Intel Products segment, not consolidated operating loss. No scale or sign parsing error.

- **INTC / stockholders_equity**
  - value_as_written: `126,360`; final_value: `126360000000.0`; XBRL value: `114281000000.0`; tag: `StockholdersEquity`.
  - source_chunk_id: `INTC_0000050863-26-000011_unknown_0398`.
  - source_quote: `Total stockholders' equity |  | 126,360`.
  - Actual row label: `Total stockholders’ equity`; column header: `Dec 27, 2025`.
  - Classification: Ground truth scope mismatch: total includes NCI; configured first tag StockholdersEquity is parent-only. The table separately discloses Total Intel stockholders’ equity 114,281 million.

- **NFLX / cash**
  - value_as_written: `5,208,710`; final_value: `5208710000.0`; XBRL value: `9033681000.0`; tag: `CashAndCashEquivalentsAtCarryingValue`.
  - source_chunk_id: `NFLX_0001065280-26-000034_item_16_0043`.
  - source_quote: `Cash | $ | 5,214,163 |  |  | $ | — |  |  | $ | — |  |  | $ | 5,214,163 |  |  | $ | 5,208,710 |`.
  - Actual row label: `Cash`; column header: `As of December 31, 2025 / Cash and cash equivalents`.
  - Classification: Wrong row or concept: Cash component in the cash-and-equivalents classification column, not the total including money market funds and time deposits. Baseline also quoted a header adjacent to a value that is not adjacent in the source (would fail V2).

- **ORCL / stockholders_equity**
  - value_as_written: `43,056`; final_value: `43056000000.0`; XBRL value: `42508000000.0`; tag: `StockholdersEquity`.
  - source_chunk_id: `ORCL_0001193125-26-277521_item_15_0012`.
  - source_quote: `Total stockholders’ equity |  |  | 43,056`.
  - Actual row label: `Total stockholders’ equity`; column header: `2026 / May 31`.
  - Classification: Ground truth scope mismatch: total includes NCI; parent-only Total Oracle Corporation stockholders’ equity is 42,508 million.

#### baseline

- **INTC / net_income**
  - value_as_written: `26`; final_value: `26000000.0`; XBRL value: `-267000000.0`; tag: `NetIncomeLoss`.
  - source_chunk_id: `INTC_0000050863-26-000011_unknown_0390`.
  - source_quote: `Net income (loss) |  | 26 |`.
  - Actual row label: `Net income (loss)`; column header: `Dec 27, 2025`.
  - Classification: Ground truth scope mismatch: selected consolidated income including NCI; NetIncomeLoss is parent-attributable (-267 million). Both are valid disclosed concepts; the configured metric uses the parent concept.

- **INTC / operating_income**
  - value_as_written: `12.7`; final_value: `12700000000.0`; XBRL value: `-2214000000.0`; tag: `OperatingIncomeLoss`.
  - source_chunk_id: `INTC_0000050863-26-000011_unknown_0162`.
  - source_quote: `Total Intel Products operating income was $12.7 billion in 2025`.
  - Actual row label: `Total Intel Products operating income (prose subject)`; column header: `2025 (prose; no table column)`.
  - Classification: Wrong row or concept: Intel Products segment, not consolidated operating loss. No scale or sign parsing error.

- **INTC / stockholders_equity**
  - value_as_written: `126,360`; final_value: `126360000000.0`; XBRL value: `114281000000.0`; tag: `StockholdersEquity`.
  - source_chunk_id: `INTC_0000050863-26-000011_unknown_0398`.
  - source_quote: `Total stockholders' equity |  | 126,360`.
  - Actual row label: `Total stockholders’ equity`; column header: `Dec 27, 2025`.
  - Classification: Ground truth scope mismatch: total includes NCI; configured first tag StockholdersEquity is parent-only. The table separately discloses Total Intel stockholders’ equity 114,281 million.

- **NFLX / cash**
  - value_as_written: `5,208,710`; final_value: `5208710000.0`; XBRL value: `9033681000.0`; tag: `CashAndCashEquivalentsAtCarryingValue`.
  - source_chunk_id: `NFLX_0001065280-26-000034_item_16_0043`.
  - source_quote: `Cash and cash equivalents | $ | 5,208,710`.
  - Actual row label: `Cash`; column header: `As of December 31, 2025 / Cash and cash equivalents`.
  - Classification: Wrong row or concept: Cash component in the cash-and-equivalents classification column, not the total including money market funds and time deposits. Baseline also quoted a header adjacent to a value that is not adjacent in the source (would fail V2).

- **ORCL / stockholders_equity**
  - value_as_written: `43,056`; final_value: `43056000000.0`; XBRL value: `42508000000.0`; tag: `StockholdersEquity`.
  - source_chunk_id: `ORCL_0001193125-26-277521_item_15_0012`.
  - source_quote: `Total stockholders’ equity |  |  | 43,056`.
  - Actual row label: `Total stockholders’ equity`; column header: `2026 / May 31`.
  - Classification: Ground truth scope mismatch: total includes NCI; parent-only Total Oracle Corporation stockholders’ equity is 42,508 million.

The wrong fact sets are identical: **True**, five facts in each mode. NFLX's final verified quote differs because its first baseline quote failed V2 and the retry supplied an exact quote of the same wrong component. No wrong row is explained by a prior-year column, scale multiplier, or sign parser.

### Final unverified rows grouped by check

#### V2

| Ticker | Metric | Failed check | Reason |
|---|---|---|---|
| MSFT | cash | V2 | source quote is not an exact substring after whitespace/quote/dash normalization |

#### V5

| Ticker | Metric | Failed check | Reason |
|---|---|---|---|
| AAPL | eps_diluted | V5 | EPS scale must be units; per-share amounts are never scaled |
| AMZN | cash | V5 | scale unknown |
| AMZN | eps_diluted | V5 | EPS scale must be units; per-share amounts are never scaled |
| CRM | eps_diluted | V5 | EPS scale must be units; per-share amounts are never scaled |
| CSCO | eps_diluted | V5 | EPS scale must be units; per-share amounts are never scaled |
| MSFT | eps_diluted | V5 | EPS scale must be units; per-share amounts are never scaled |
| NVDA | eps_diluted | V5 | EPS scale must be units; per-share amounts are never scaled |
| ORCL | eps_diluted | V5 | EPS scale must be units; per-share amounts are never scaled |

### Root causes and ground-truth decision

- AAPL EPS: final and first extraction report scale_as_written=null, value 7.46, in a millions table whose scale_excludes_per_share=true and whose visible header says “except … per-share amounts”. scale_name(None) yields None; effective != "units" fails before examining the exception flag. The same defect explains seven final EPS rejections. A null scale may mean units only when the source explicitly supports the per-share exception (or a units scale); explicit millions EPS must still fail, and EPS must never be multiplied.
- AMZN cash: all three attempts cite the cash-flow reconciliation table, which has no scale in the saved header/context. A model-reported millions scale is not evidence. Keep rejecting unknown scale; feedback should direct it to a source with an explicit scale.
- MSFT cash: all three attempts remove pipe delimiters from the quote. Whitespace normalization deliberately does not remove meaningful table punctuation. V2 is correct; feedback should show the actual source row.
- V6 only looks for the year anywhere in a chunk, so it cannot distinguish current from prior-year cells. This is a latent correctness bug even though none of the five observed wrong rows uses a prior year. Pipe tables contain blank/currency cells and original colspan geometry is absent, so map semantic numeric columns to ordered date headers conservatively and reject ambiguous locations rather than guess.
- V8 is missing. Citation/number checks do not establish a matching financial concept. Add configured allowed/excluded labels, preserve parent-vs-NCI scope when both labels are disclosed, and reject segment/prose concepts and partial cash components.
- No change to groundtruth.py is justified. The selected tags accurately represent the canonical parent-attributable income and equity and total cash/equivalents. Changing tags to match the model would change the target rather than fix the verifier. Source-only scope checks must align evidence with that declared target; no evaluator values or XBRL objects enter extraction or verification.

Diagnosis gate: printed all ten wrong-mode rows, checked their source tables/prose and headers, printed all nine final unverified reasons and inspected failed attempt history. Passed. One initial read-only console dump hit Windows cp1252 Unicode output; rerun with UTF-8 succeeded. Proceed to Step 2.

## Phase 5b fixes — Step 2 gate passed

- Added source-only semantic cell mapping in table.py: exact quoted numeric-cell location, ordered date/year headers, repeated child headers, currency/blank cells and dash placeholders, and fail-closed ambiguous/missing columns. V6 now checks the selected table column; prose retains the prior fiscal-date/year rule. INTC operating income is inside a saved one-cell layout table containing prose and has no table-column evidence, so V6 correctly rejects it; the same prose treated as text also fails V8's segment exclusion.
- Added V8 and row_labels/exclude_labels for all nine metrics. Punctuation/case normalization retains word boundaries. Parent income/equity scope is checked against visible competing parent/NCI rows, cash components are rejected, and diluted share-count denominators are not accepted as EPS. Canonical parent-only definitions and all XBRL tag selections remain unchanged.
- Fixed V5's null-scale EPS defect only where the source establishes units: visible per-share header exception, metadata exception, or units scale. Explicit conflicting/ambiguous EPS scales and unknown monetary scales still fail. EPS normalization never multiplies.
- Feedback now names the failed check, expected fiscal column, allowed/excluded row labels and any discovered parent row. V2 feedback includes the literal source row with separators. No first-attempt prompt, retrieval query/ranking, number parser, ground-truth code or source snapshot changed.
- Real immutable source fixtures cover all fourteen diagnosis cases plus three equivalent-label/nested-header cases (CSCO Total equity, GOOGL Revenues, INTU repeated cost/fair-value headers). No XBRL answer values are in these fixtures.
- Added positive/negative regressions for V5, V6, V8 and retry corrections using a fake provider; tests remain network-blocked. Existing synthetic prose/table fixtures were made structurally explicit for the stricter table check.
- Gate commands: python -m pytest --tb=short → **180 passed in 7.72s**. Earlier first implementation also passed 175 tests; subsequent additions cover equivalent labels and nested headers. No test gate failures occurred.
- Provenance check: extraction/retrieval code hash equals the old run, all query/settings fields match, and all 15 current filing/chunk hashes equal the old immutable snapshots. Baseline will not be rerun because its effective inputs are unchanged. Retry feedback alone changed and is used only after a verified-mode failure.
- New runs also freeze verifier/table/pipeline source hashes. Retain the existing LLM cache and use a new run ID for the verified rerun. Proceed to Step 3.

## Phase 5b rerun — Step 3 and final gate

# Phase 5b: verifier corrections and measured rerun

Model: `gemini-3.5-flash-lite`. New verified run: `full-gemini-lite-phase5b-v1`. Baseline and original verified run: `full-gemini-lite-v1`. All counts below are recomputed from SQLite evaluations; four no-ground-truth cases per mode are excluded from the 131-case denominator.

| Study | Mode | Correct | Wrong | Unverified | Not found | Facts with GT | Precision | Wrong rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Original | baseline | 109 | 5 | 0 | 17 | 131 | 95.6% | 3.8% |
| Original | verified | 100 | 5 | 9 | 17 | 131 | 95.2% | 3.8% |
| Phase 5b | verified | 111 | 0 | 3 | 17 | 131 | 100.0% | 0.0% |

Baseline was reused, not regenerated: extraction code hash, retrieval settings, queries, fiscal metadata and all fifteen evidence hashes match. Only verification rules and post-failure feedback changed. All original results remain intact.

## Previously wrong facts after the fix

| Ticker | Metric | New classification | Final value | Attempts | Final failed check |
| --- | --- | --- | --- | --- | --- |
| INTC | net_income | unverified | None | 3 | V8 |
| INTC | operating_income | correct | -2214000000.0 | 2 | None |
| INTC | stockholders_equity | correct | 114281000000.0 | 2 | None |
| NFLX | cash | unverified | None | 3 | V2 |
| ORCL | stockholders_equity | correct | 42508000000.0 | 2 | None |

Three previously wrong facts were corrected; two abstained. No previously wrong fact is accepted with a wrong value in this run. This is a small, source-specific regression study, not a general correctness guarantee. No observed wrong row was a prior-year error; V6 column regressions demonstrate prevention of that latent defect separately.

## Every remaining wrong or unverified row

### AMZN / cash — unverified

- Failed check: **V5**; reason: scale unknown.
- value_as_written: `86,810`; final_value: `None`; XBRL value (evaluation only): `86810000000.0`.
- source_chunk_id: `AMZN_0001018724-26-000004_unknown_0218`.
- Final source_quote: `Cash and cash equivalents | $ | 78,779 |  |  | $ | 86,810 |`.
- Literal source row: `Cash and cash equivalents | $ | 78,779 |  |  | $ | 86,810 | `.
- Explanation: All three attempts select the same cash-flow reconciliation table. Its saved visible header/context has no scale, so the model-reported millions scale is unsupported. V5 remains strict; a different explicitly scaled source is required. No amount is released.

Attempts (stored audit):

- 1: V5 — scale unknown; displayed `86,810`, quote `Cash and cash equivalents | $ | 78,779 |  |  | $ | 86,810 |`.
- 2: V5 — scale unknown; displayed `86,810`, quote `Consolidated Statements of Cash Flows Reconciliation
 | December 31, 2024 |  | December 31, 2025
Cash and cash equivalents | $ | 78,779 |  |  | $ | 86,810 |`.
- 3: V5 — scale unknown; displayed `86,810`, quote `Cash and cash equivalents | $ | 78,779 |  |  | $ | 86,810 |`.

### INTC / net_income — unverified

- Failed check: **V8**; reason: row 'Net income (loss)' does not establish parent-only net_income scope; noncontrolling interests are disclosed. Expected parent row: Net income (loss) attributable to Intel.
- value_as_written: `26`; final_value: `None`; XBRL value (evaluation only): `-267000000.0`.
- source_chunk_id: `INTC_0000050863-26-000011_unknown_0390`.
- Final source_quote: `Net income (loss) |  | 26 |  |  | ( 19,233 ) |  |  | 1,675`.
- Literal source row: `January 22, 2026`.
- Explanation: Attempt 1 selects consolidated income including NCI and fails V8. Attempt 2 identifies the parent loss, but value_as_written is (267) while the exact source/quote is ( 267 ); V3 correctly rejects the changed characters. Attempt 3 reverts to the including-NCI row and fails V8. The exact-copy and parent-only rules are preserved; no amount is released.

Attempts (stored audit):

- 1: V8 — row 'Net income (loss)' does not establish parent-only net_income scope; noncontrolling interests are disclosed. Expected parent row: Net income (loss) attributable to Intel; displayed `26`, quote `Net income (loss) |  | 26 |`.
- 2: V3 — displayed value is absent from the source quote; displayed `(267)`, quote `Net income (loss) attributable to Intel |  | $ | ( 267 )`.
- 3: V8 — row 'Net income (loss)' does not establish parent-only net_income scope; noncontrolling interests are disclosed. Expected parent row: Net income (loss) attributable to Intel; displayed `26`, quote `Net income (loss) |  | 26 |  |  | ( 19,233 ) |  |  | 1,675`.

### NFLX / cash — unverified

- Failed check: **V2**; reason: source quote is not an exact substring after whitespace/quote/dash normalization.
- value_as_written: `9,033,681`; final_value: `None`; XBRL value (evaluation only): `9033681000.0`.
- source_chunk_id: `NFLX_0001065280-26-000034_item_16_0014`.
- Final source_quote: `Cash and cash equivalents | $ | 9,033,681`.
- Literal source row: `Cash and cash equivalents |  | $ | 9,033,681 |  |  | $ | 7,804,733 | `.
- Explanation: Attempt 1 invents adjacency between a column label and a cash component and fails V2. Attempt 2 supplies a literal component row but fails V8. Attempt 3 selects the correct balance-sheet total, but omits an empty label/currency cell separator from its quote and fails V2. The amount is not accepted without literal evidence. Runtime minute-quota errors were logged and recovered with the existing pinned-model recovery loop.

Attempts (stored audit):

- 1: V2 — source quote is not an exact substring after whitespace/quote/dash normalization; displayed `5,208,710`, quote `Cash and cash equivalents | $ | 5,208,710`.
- 2: V8 — row 'Cash' does not match expected cash row labels: cash and cash equivalents, cash cash equivalents; displayed `5,208,710`, quote `Cash | $ | 5,214,163 |  |  | $ | — |  |  | $ | — |  |  | $ | 5,214,163 |  |  | $ | 5,208,710`.
- 3: V2 — source quote is not an exact substring after whitespace/quote/dash normalization; displayed `9,033,681`, quote `Cash and cash equivalents | $ | 9,033,681`.

There are **zero remaining wrong rows**. The seventeen not-found cases with ground truth are unchanged; extraction/retrieval coverage was outside this fix. Four cases have no matching XBRL ground truth and remain excluded, not counted as correct.

## Validation, cost and limits

- `python -m pytest --tb=short`: **180 passed in 7.72s**. Tests block all network connections and use saved source fixtures/fake providers.
- `python -m dv.cli run --mode verified --companies full --run-id full-gemini-lite-phase5b-v1`: exit 0, 135 stored facts, no processing errors. Full run log: `phase5b-run.txt`.
- `python -m dv.cli eval --run-id full-gemini-lite-phase5b-v1`: exit 0. Evaluation log: `phase5b-eval.txt`.
- Integrity gate: all answered facts independently reverified; fifteen evidence manifests match the original study; one pinned model; every fact evaluated. Extraction/retrieval code hashes are identical across old/new runs.
- Ground-truth tags, source data, number parsing and first-attempt prompts were not changed. The original second-model benchmark remains pending.
- Column inference from flattened pipe tables is conservative: unsupported or ambiguous cell/header geometry fails closed. Label rules are deterministic lexical checks with local scope evidence, not a complete accounting ontology; undisclosed or separated scope distinctions may still evade them. Exact source punctuation remains required.

Recorded LLM attempts: **156**, including **135 cache hits**, **3 logged transient provider errors**, 114,525 new input tokens and 2,584 new output tokens. Actual free-tier cost: **$0.00**. Hypothetical frozen reference-price cost: **$0.382335**. Cache hits consume zero new tokens/cost; this is a warm-cache rerun, not a cold speed comparison.

Phase 5b gate passed. Stop after this result as requested.

## Phase 8 — CTO dashboard rework passed

- Reworked app/streamlit_app.py into the requested wide layout: database-derived subtitle, four executive cards, compact results, caught-error cases, company drill-down, full source evidence, cost/cache comparison, and collapsed coverage/limits. Removed the top pending-model banner.
- Accuracy pairs the first complete compatible baseline with the latest complete verified run after matching extraction settings/code and immutable source manifests. Partial model trials are excluded. Caught errors and failed-check names come from stored evaluations and verification_attempts; the default company/metric comes from those cases.
- Preserved exact-quote inspection, SEC filing links, chunk IDs, XBRL tags and mismatch warnings. Added unique matched table-row and cell highlighting with HTML escaping; ambiguous or nonmatching evidence is not guessed. Added compact money/EPS formatting and the V1–V8 legend.
- Cost cards/charts use recorded uncached-call costs from the first completed study, never the cached replay. The database has no wholly cold completed run: the first study already reused some calls. The app says so. The side-by-side cache statistics use the original verified study and a source/settings/result-identical all-cache replay; updated accuracy uses the repaired verifier run.
- Added offline regressions for compatible run pairing, refusal to pair changed source snapshots, cache replay discovery without redundant evaluations, original-versus-cache costs, caught-error audit selection, financial formatting and exact selected-cell highlighting. No live LLM calls or extraction imports were added.
- Gate: python -m pytest --tb=short → **182 passed in 13.25s**; log reports/cto-dashboard-tests.txt.
- Gate: Streamlit AppTest exercised all company/mode views, checked each facts table, four cards and first/cache comparison: **30 views passed**; log reports/cto-dashboard-all-views.txt. An initial harness treated the intentional red baseline XBRL-mismatch warning as an application error; corrected the harness to distinguish that message from runtime errors, then the full gate passed on the next attempt.
- Browser QA: confirmed four metric cards align on one desktop row, the latest results appear, the default company has caught errors, and clicking Intel operating income selects the corrected fact and highlights its original source row/cell. Tested a temporary desktop viewport to verify the requested one-row layout, then restored the default viewport.
- Screenshot gate: reports/cto-dashboard-top.jpg and reports/cto-dashboard-drilldown.jpg saved and verified as JPEGs. Streamlit runs at http://127.0.0.1:8511/.

Database-selected provenance:

- Model gemini-3.5-flash-lite: baseline full-gemini-lite-v1; latest verified full-gemini-lite-phase5b-v1; cost source full-gemini-lite-v1; cache replay full-gemini-lite-cache-v1.
- Caught examples available: 5. First verified reference cost $0.509556, 156,008 new tokens, 95.82s, 144/172 cache hits.
- Cached replay reference cost $0.000000, 0 new tokens, 4.39s, 166/166 cache hits.

Known limits: no fully cold completed cost benchmark; the cache comparison uses the original verifier; the second-model benchmark remains pending. All are disclosed in the app. Requested gate complete; stop after delivery.

## Deployment preparation — packaging gate

- Created a standalone Git repository inside diligence-verify on codex/streamlit-cloud. The surrounding chemistry application repository had no commits and unrelated projects; none of those projects are staged here. No remote publication is part of this task.
- requirements.txt pins only the three dashboard dependencies: Streamlit 1.66.1, pandas 3.1.0, Pydantic 2.14.1. YAML/dotenv imports are lazy research-only imports; the app adds its src checkout to the import path instead of installing the full extraction stack.
- Normalized stored Windows path separators at the source-reading boundary. Added .gitattributes so Git preserves evidence bytes/newlines and SQLite bytes across Linux/Windows clones. The database and financial results were not rewritten.
- The deployment manifest/allowlist includes data/runs.db and all 15 immutable snapshots used by the selected accuracy and first/cache comparisons. Database size: 1,503,232 bytes; processed snapshots total 7,727,476 bytes; largest source snapshot: 783,078 bytes. No candidate file exceeds 50 MB; the largest candidate is the public AAPL companyfacts test fixture (about 4.20 MB).
- During initial inventory, an unused historical mutable AAPL working-copy path failed its old partial-run hash. The completed dashboard does not select that partial trial. Corrected packaging to use the actual selected app manifests; all 15 deployed snapshots pass their stored hashes. Historical audit rows remain unchanged; unused working copies stay ignored.
- Expanded credential ignores (.env and variants, Streamlit secrets, private-key/credential files), keeping only .env.example. Scanned every candidate file, including SQLite, for known environment credential values and provider/private-key patterns: no matches. The new repository had no pre-existing commit history. Values were not printed.
- Rebuilt README with a one-paragraph summary, a runs.db-derived current results table, live-app placeholder, keyless local setup, Python 3.11 Community Cloud entrypoint instructions and cost/study limitations.
- Gate: python -m pytest --tb=short -> 183 passed in 10.55s (reports/deployment-tests.txt). A clean minimal dependency environment and fresh-clone/no-.env runtime validation follow this packaging commit.

## Deployment preparation — fresh-clone gate passed

- Packaging commit 053a5bd was cloned with --no-local and core.autocrlf=false into an ignored validation checkout. All 15 evidence hashes match and the SQLite bytes are identical to the committed database; no .env exists in the clone.
- Created a new isolated Python 3.11 virtual environment with only requirements.txt and its transitive dependencies. Installation succeeded. OpenAI, EdgarTools, dotenv and YAML packages are absent; no editable research package is installed.
- Cleared inherited API/token/secret/password variables, SEC_USER_AGENT and Python path overrides. With non-loopback connections blocked, Streamlit AppTest loaded all 30 company/mode views, including row data and source panes. No extraction/provider modules were imported. Log: reports/deployment-clean-clone.txt.
- The optional exhaustive harness needed two corrections before passing on its third attempt: AppTest resolves relative script paths against the harness file (fixed to the absolute clone entrypoint), and Windows asyncio uses a local socketpair (allowed loopback self-pipes while keeping external sockets blocked). Neither issue required an app change.
- Ran the actual minimal-environment `streamlit run app/streamlit_app.py` command from the clone, with no .env/API credentials, on temporary localhost port 8512. Server boot succeeded; /_stcore/health returned HTTP 200. The normal user demo remains on port 8511.
- Full commit-history audit scanned 127 distinct blobs, including the database, for known credential values and provider/private-key patterns: zero findings. An initial overly broad scanner mistook PORTKEY_MODEL's public model identifier for a secret because its variable name contains KEY; corrected credential-name classification, then the history audit passed. No real credential was found or removed, and no history rewrite was needed.
- Final size check: database 1,503,232 bytes; processed evidence 7,727,476 bytes across 15 files. No tracked file is over 50 MB. Credential files are ignored and absent from Git history.
- The README links to official Community Cloud dependency/deployment guidance and contains the current database-derived results. The live-app URL is explicitly a placeholder. No remote was added and no deployment was published.

Requested deployment-preparation gate is complete. Stop after delivering the local repository and validation evidence.

## Final cold benchmark — preflight gate

- Re-read AGENTS.md in full. The user's accuracy-match gate takes precedence: no dashboard, extraction prompt, retrieval, verifier, source snapshot or headline changes until the cold comparison passes. Any classification difference stops work for review; no repeated draws to recover the old number.
- Added scripts/cold_benchmark.py as a measurement-only runner around the existing final pipeline. Each mode uses a separate new empty runs.db/cache under ignored .deploy-check/benchmarks. The original runs.db and cache are untouched. Request pacing is five seconds between live starts, below the observed free-tier minute cap. Pacing/recovery waits remain included in measured wall time.
- Stored per-request prompt/cache-key identity and extraction-attempt labels for cost grouping. Logging context changes do not enter the prompt or cache key. Pinned model remains gemini-3.5-flash-lite; temperature 0. The runner evaluates against independently saved companyfacts only after extraction finishes.
- Offline wrapper tests verify empty-cache behavior, unchanged prompts/cache identity, attempt labels, and preserved generation settings under pacing. pytest: 185 passed in 35.49s (reports/cold-benchmark-tests.txt).
- Frozen-input gate passed: extraction/verifier source hashes and all fifteen fiscal metadata/source chunk hashes exactly match full-gemini-lite-phase5b-v1. The first live measurement is cold-final-verified-v1; baseline receives another separate empty cache only if its predecessor accuracy gate passes.
- INTC section investigation: the only literal Item 7./Item 8. strings occur in the cross-reference index table; the parser replaces that table before Item-heading recognition, and parse_html detects only unknown. Merely treating those index rows as actual document boundaries would mislabel evidence. Source section metadata remains unchanged pending the cold gate; this is not a safe one-line section fix.

## STOP — cold accuracy parity gate (user Step 5f)

# Cold accuracy comparison

| Run | Mode | Correct | Wrong | Unverified | Not found | No ground truth | Error | Precision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| full-gemini-lite-phase5b-v1 | verified | 111 | 0 | 3 | 17 | 4 | 0 | 100.0% |
| cold-final-verified-v1 | verified | 111 | 0 | 2 | 18 | 4 | 0 | 100.0% |

Isolated database: `.deploy-check/benchmarks/cold-final-verified-v1/data/runs.db`. Initial cache entries: 0. Model: `gemini-3.5-flash-lite`; temperature: 0.
New input tokens: 584,478; output: 19,293; reference cost: $2.042829; cache hits: 0/159.
Companies measured: 15; total wall time: 873.17s; average: 58.21s/company; reference cost/company: $0.136189.
Time includes free-tier request pacing and any provider recovery waits.

**STOP: cold-run accuracy differs from the current results.** Dashboard files, original results and original cache have not been changed. No automatic rerun or tuning is permitted by this gate.

| Ticker | Metric | Previous | Cold | Previous value | Cold value | XBRL | Cold quote |
| --- | --- | --- | --- | --- | --- | --- | --- |
| NFLX | cash | unverified | not_found | None | None | 9033681000.0 | None |

The frozen pipeline/settings/sources were reused; fresh hosted model responses differ from cached responses. Temperature 0 alone does not establish reproducible hosted inference. Each changed classification must be reviewed before selecting a new headline.

## Cause of the parity failure

Only NFLX / cash changed evaluation classification. Its first cold request has the same provider/model/prompt/schema cache identity as an existing reference response (prompt SHA-256 `94137db173218db48fff43923b416b81d32f1b1cf636cf7bd8711ab039ac3018`), yet the returned JSON differs:

- Previous first answer claimed quote `Cash and cash equivalents | $ | 5,208,710`, which fails V2 because that label and value are not adjacent in the source. The old run eventually produced the correct total with another inexact quote and ended **unverified** after three attempts.
- Cold first answer copied the literal `Cash` component row containing `5,208,710`, which passes the quote check but correctly fails V8 because a cash component is not total cash and equivalents.
- Cold attempt two returned `value_as_written=null`. The unchanged pipeline's null-return branch immediately labels the result **not_found**, even after a previous V8 rejection. That is why one review flag became a missing extraction; no accepted value changed, and no new wrong answer was accepted.

The missing-value branch does not preserve the prior failed-check outcome. Whether an abstention after a failed verification should instead remain flagged for review is a behavior decision that must be resolved before changing the pipeline. No such change was made here. Do not relabel this stored cold result manually to reproduce the old headline.

All fifteen filing/source manifests and extraction/verifier code hashes match the reference. The live dashboard file and canonical `data/runs.db` are byte/working-tree unchanged. The complete cold result and token/timing logs are retained in the isolated runs.db above. No cold baseline or cached replay was started, no cold data was promoted into the app, and no new UI screenshots were taken because the user's Step 5f requires stopping first.

Intel section investigation: the only Item 7 and Item 8 headings are in a cross-reference index at roughly 98 percent of the raw HTML, rather than body boundaries. A safe fix would require recognizing the main narrative/topic/page structure, not relabeling the index as a document section. The original unknown labels remain in the immutable evidence; this limitation is documented here pending authorized UI continuation.

Offline measurement-wrapper validation: **185 tests passed**. The requested polish and end-to-end UI/screenshot gate remain pending after this explicit accuracy-match stop.

## GitHub publication — explicitly authorized

- User requested creating a repository under swaroopV4 and pushing this project, and explicitly selected public visibility for CTO/portfolio sharing.
- GitHub connector account and local Git credential account both verified as swaroopv4. Connector has no repository-creation tool; use GitHub REST API for creation and Git credential manager for git transport. No credentials are printed or stored in code.
- Pre-publication scan covered all tracked and non-ignored new files, including database and benchmark logs, against known credential values and provider/private-key patterns: zero findings. Largest file is 4.20 MB. Local .env and isolated cache/checkouts remain ignored.
- Updated the README clone URL and linked the honest cold-run parity-stop report. Includes the completed benchmark measurement runner, its offline tests and comparison evidence; the dashboard and canonical results remain unchanged after the parity stop.
- Last complete test suite: 185 passed. Publication creates no app hosting deployment; the live app URL remains a clearly identified placeholder.

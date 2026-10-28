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

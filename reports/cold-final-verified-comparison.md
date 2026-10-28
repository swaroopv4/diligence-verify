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

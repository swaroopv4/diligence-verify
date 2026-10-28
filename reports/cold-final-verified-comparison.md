# Cold accuracy comparison

| Run | Mode | Correct | Wrong | Unverified | Not found | No ground truth | Error | Precision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| full-gemini-lite-phase5b-v1 | verified | 111 | 0 | 3 | 17 | 4 | 0 | 100.0% |
| cold-final-verified-v1 | verified | 111 | 0 | 3 | 17 | 4 | 0 | 100.0% |

Isolated database: `.deploy-check/benchmarks/cold-final-verified-v1/data/runs.db`. Initial cache entries: 0. Model: `gemini-3.5-flash-lite`; temperature: 0.
New input tokens: 584,478; output: 19,293; reference cost: $2.042829; cache hits: 0/159.
Companies measured: 15; total wall time: 873.17s; average: 58.21s/company; reference cost/company: $0.136189.
Time includes free-tier request pacing and any provider recovery waits.

Cold accuracy gate passed: all per-fact classifications match the previous run.

## Accepted null-after-rejection rule

A candidate rejected by verification remains unverified when a later retry returns null. The last failed check and candidate evidence are retained. Applied to stored NFLX cash (V8); original and revised results are preserved in result_policy_revisions. No new model request was used for this correction.

| Mode | Model | Correct | Wrong | Unverified | Not found | No ground truth | Precision on answered |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline | gemini-3.5-flash-lite | 109 | 5 | 0 | 17 | 4 | 95.6% |
| Verified | gemini-3.5-flash-lite | 111 | 0 | 3 | 17 | 4 | 100.0% |

Both cold runs started with empty caches. The verified replay used only the populated cold verified cache and made no live model requests.

# Cold accuracy comparison

| Run | Mode | Correct | Wrong | Unverified | Not found | No ground truth | Error | Precision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| full-gemini-lite-v1 | baseline | 109 | 5 | 0 | 17 | 4 | 0 | 95.6% |
| cold-final-baseline-v1 | baseline | 109 | 5 | 0 | 17 | 4 | 0 | 95.6% |

Isolated database: `.deploy-check/benchmarks/cold-final-baseline-v1/data/runs.db`. Initial cache entries: 0. Model: `gemini-3.5-flash-lite`; temperature: 0.
New input tokens: 448,669; output: 16,834; reference cost: $1.598517; cache hits: 0/137.
Companies measured: 15; total wall time: 681.04s; average: 45.40s/company; reference cost/company: $0.106568.
Time includes free-tier request pacing and any provider recovery waits.

Cold accuracy gate passed: all per-fact classifications match the previous run.

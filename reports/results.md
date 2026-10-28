# Diligence Verify

Code verification removed all 5 wrong answers: 3 corrected on retry, 2 flagged for human review.

**Unverified · flagged for review: 3**
includes 2 caught baseline errors

| Mode | Model | Correct | Wrong | Unverified | Not found | No ground truth | Precision on answered |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline | gemini-3.5-flash-lite | 109 | 5 | 0 | 17 | 4 | 95.6% |
| Verified | gemini-3.5-flash-lite | 111 | 0 | 3 | 17 | 4 | 100.0% |

Each mode covers 135 facts: 15 companies × 9 metrics. Missing ground truth is excluded from precision.

## Caught errors

| Company | Metric | Baseline value | XBRL value | Verified outcome | Caught by | Source quote |
| --- | --- | --- | --- | --- | --- | --- |
| INTC | Operating Income | $12.70B | −$2.21B | Corrected to −$2.21B | V6 · fiscal-period column not verified | Total Intel Products operating income was $12.7 billion in 2025 |
| INTC | Stockholders Equity | $126.36B | $114.28B | Corrected to $114.28B | V8 · wrong row or financial scope | Total stockholders' equity \|  \| 126,360 |
| ORCL | Stockholders Equity | $43.06B | $42.51B | Corrected to $42.51B | V8 · wrong row or financial scope | Total stockholders’ equity \|  \|  \| 43,056 |
| INTC | Net Income | $26.00M | −$267.00M | Flagged for review | V8 · wrong row or financial scope | Net income (loss) \|  \| 26 |
| NFLX | Cash | $5.21B | $9.03B | Flagged for review | V8 · wrong row or financial scope | Cash and cash equivalents \| $ \| 5,214,163 \|  \|  \| $ \| — \|  \|  \| $ \| — \|  \|  \| $ \| 5,214,163 \|  \|  \| $ \| 5,208,710 |

## Cost per company

| Mode | Reference cost / company | Avg time / company |
| --- | --- | --- |
| Baseline | $0.11 | 45s |
| Verified | $0.14 | 58s |

## Average verified cost by step

| Step | Requests | Avg reference cost / company |
| --- | --- | --- |
| Extraction attempt 1 | 137 | $0.11 |
| Verification retries | 22 | $0.03 |

## Verified replay

| Run | New tokens | Time | Reference cost | Cache hit rate |
| --- | --- | --- | --- | --- |
| Cold verified | 603771 | 873s | $2.04 | 0.0% |
| Cached replay | 0 | 28s | $0.00 | 100.0% |

Reference costs use the token prices stored with each run. Measured time includes free-tier pacing and recovery waits.

## Per-metric results

| Mode | Metric | Correct | Wrong | Unverified | Not found | No ground truth | Precision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline | Cash | 13 | 1 | 0 | 1 | 0 | 92.9% |
| Baseline | Diluted EPS | 14 | 0 | 0 | 1 | 0 | 100.0% |
| Baseline | Net Income | 13 | 1 | 0 | 1 | 0 | 92.9% |
| Baseline | Operating Cash Flow | 14 | 0 | 0 | 1 | 0 | 100.0% |
| Baseline | Operating Income | 11 | 1 | 0 | 2 | 1 | 91.7% |
| Baseline | Revenue | 12 | 0 | 0 | 3 | 0 | 100.0% |
| Baseline | Stockholders Equity | 12 | 2 | 0 | 1 | 0 | 85.7% |
| Baseline | Total Assets | 9 | 0 | 0 | 6 | 0 | 100.0% |
| Baseline | Total Liabilities | 11 | 0 | 0 | 1 | 3 | 100.0% |
| Verified | Cash | 12 | 0 | 2 | 1 | 0 | 100.0% |
| Verified | Diluted EPS | 14 | 0 | 0 | 1 | 0 | 100.0% |
| Verified | Net Income | 13 | 0 | 1 | 1 | 0 | 100.0% |
| Verified | Operating Cash Flow | 14 | 0 | 0 | 1 | 0 | 100.0% |
| Verified | Operating Income | 12 | 0 | 0 | 2 | 1 | 100.0% |
| Verified | Revenue | 12 | 0 | 0 | 3 | 0 | 100.0% |
| Verified | Stockholders Equity | 14 | 0 | 0 | 1 | 0 | 100.0% |
| Verified | Total Assets | 9 | 0 | 0 | 6 | 0 | 100.0% |
| Verified | Total Liabilities | 11 | 0 | 0 | 1 | 3 | 100.0% |

## Flagged for review

| Company | Metric | Check | Reason | Source quote |
| --- | --- | --- | --- | --- |
| AMZN | Cash | V5 | scale unknown | Consolidated Statements of Cash Flows Reconciliation<br> \| December 31, 2024 \|  \| December 31, 2025<br>Cash and cash equivalents \| $ \| 78,779 \|  \|  \| $ \| 86,810 |
| INTC | Net Income | V8 | row 'Net income (loss)' does not establish parent-only net_income scope; noncontrolling interests are disclosed. Expected parent row: Net income (loss) attributable to Intel | Net income (loss) \|  \| 26 \|  \|  \| ( 19,233 ) \|  \|  \| 1,675 |
| NFLX | Cash | V8 | row 'Cash' does not match expected cash row labels: cash and cash equivalents, cash cash equivalents | Cash \| $ \| 5,214,163 \|  \|  \| $ \| — \|  \|  \| $ \| — \|  \|  \| $ \| 5,214,163 \|  \|  \| $ \| 5,208,710 |

## Verification

- V1: Source belongs to this filing.
- V2: Quote matches the source exactly.
- V3: Displayed number is copied exactly.
- V4: Number can be parsed.
- V5: Scale and per-share units are supported.
- V6: Selected column matches the fiscal period.
- V7: Financial sanity checks.
- V8: Row label and financial scope match.

## Limitations

One model, 15 companies, and 10-K filings only. Precision measures accepted answers with matching XBRL ground truth; abstentions and missing facts affect coverage. Deterministic checks do not guarantee correctness on other filings.
Intel section labels remain unknown: its Item labels occur in a cross-reference index rather than body boundaries. Whole-document retrieval preserves source evidence but has less reliable section ranking.

Data: `cold-final-baseline-v1`, `cold-final-verified-v1`, `cached-final-verified-v1`.

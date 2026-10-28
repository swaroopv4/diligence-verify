# Diligence Verify results

**Second-model benchmark pending.** This preliminary report uses one completed model comparison. Partial secondary-model trials are preserved in SQLite and PROGRESS.md and excluded from accuracy tables.

Generated entirely from stored runs, evaluations, verification attempts and call logs.

Study: 15 companies, 9 metrics, 10-K.

| Mode | Model | Correct | Wrong | Unverified | Precision on answered | Avg time per company | Cost at reference price |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | gemini-3.5-flash-lite | 109 | 5 | 0 | 95.6% | 26.810s | $ 1.223229 |
| verified | gemini-3.5-flash-lite | 100 | 5 | 9 | 95.2% | 6.388s | $ 0.509556 |

Observed XBRL mismatches: 5 in baseline, 5 in verified mode. The verified pipeline did not reduce the mismatch count in this sample.

## Coverage and rates

| Mode | Model | With ground truth | Correct rate | Wrong rate | Unverified rate | Not found | Error | No ground truth |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | gemini-3.5-flash-lite | 131 | 83.2% | 3.8% | 0.0% | 17 | 0 | 4 |
| verified | gemini-3.5-flash-lite | 131 | 76.3% | 3.8% | 6.9% | 17 | 0 | 4 |

## Per-metric breakdown

| Model | Mode | Metric | Correct | Wrong | Unverified | Not found | Error | No ground truth | Precision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gemini-3.5-flash-lite | baseline | cash | 13 | 1 | 0 | 1 | 0 | 0 | 92.9% |
| gemini-3.5-flash-lite | baseline | eps_diluted | 14 | 0 | 0 | 1 | 0 | 0 | 100.0% |
| gemini-3.5-flash-lite | baseline | net_income | 13 | 1 | 0 | 1 | 0 | 0 | 92.9% |
| gemini-3.5-flash-lite | baseline | operating_cash_flow | 14 | 0 | 0 | 1 | 0 | 0 | 100.0% |
| gemini-3.5-flash-lite | baseline | operating_income | 11 | 1 | 0 | 2 | 0 | 1 | 91.7% |
| gemini-3.5-flash-lite | baseline | revenue | 12 | 0 | 0 | 3 | 0 | 0 | 100.0% |
| gemini-3.5-flash-lite | baseline | stockholders_equity | 12 | 2 | 0 | 1 | 0 | 0 | 85.7% |
| gemini-3.5-flash-lite | baseline | total_assets | 9 | 0 | 0 | 6 | 0 | 0 | 100.0% |
| gemini-3.5-flash-lite | baseline | total_liabilities | 11 | 0 | 0 | 1 | 0 | 3 | 100.0% |
| gemini-3.5-flash-lite | verified | cash | 11 | 1 | 2 | 1 | 0 | 0 | 91.7% |
| gemini-3.5-flash-lite | verified | eps_diluted | 7 | 0 | 7 | 1 | 0 | 0 | 100.0% |
| gemini-3.5-flash-lite | verified | net_income | 13 | 1 | 0 | 1 | 0 | 0 | 92.9% |
| gemini-3.5-flash-lite | verified | operating_cash_flow | 14 | 0 | 0 | 1 | 0 | 0 | 100.0% |
| gemini-3.5-flash-lite | verified | operating_income | 11 | 1 | 0 | 2 | 0 | 1 | 91.7% |
| gemini-3.5-flash-lite | verified | revenue | 12 | 0 | 0 | 3 | 0 | 0 | 100.0% |
| gemini-3.5-flash-lite | verified | stockholders_equity | 12 | 2 | 0 | 1 | 0 | 0 | 85.7% |
| gemini-3.5-flash-lite | verified | total_assets | 9 | 0 | 0 | 6 | 0 | 0 | 100.0% |
| gemini-3.5-flash-lite | verified | total_liabilities | 11 | 0 | 0 | 1 | 0 | 3 | 100.0% |

## Observed errors caught by verification

Qualifying paired examples observed: 0; shown: 0.

No qualifying baseline-wrong/verified-caught pairs were observed.

Fewer than the requested five examples occurred; no examples or errors were invented.

## All wrong baseline rows for review

| Model | Ticker | Metric | Extracted | XBRL | Quote |
| --- | --- | --- | --- | --- | --- |
| gemini-3.5-flash-lite | INTC | net_income | 26000000.0 | -267000000.0 | Net income (loss) \|  \| 26 \| |
| gemini-3.5-flash-lite | INTC | operating_income | 12700000000.0 | -2214000000.0 | Total Intel Products operating income was $12.7 billion in 2025 |
| gemini-3.5-flash-lite | INTC | stockholders_equity | 126360000000.0 | 114281000000.0 | Total stockholders' equity \|  \| 126,360 |
| gemini-3.5-flash-lite | NFLX | cash | 5208710000.0 | 9033681000.0 | Cash and cash equivalents \| $ \| 5,208,710 |
| gemini-3.5-flash-lite | ORCL | stockholders_equity | 43056000000.0 | 42508000000.0 | Total stockholders’ equity \|  \|  \| 43,056 |

## Cost, timing and cache

| Run | Mode | Input tokens | Output tokens | Actual cost | Reference cost | Calls | Cache hits | Hit rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| full-gemini-lite-v1 | baseline | 341618 | 13225 | $ 0.000000 | $ 1.223229 | 153 | 27 | 17.6% |
| full-gemini-lite-v1 | verified | 152547 | 3461 | $ 0.000000 | $ 0.509556 | 172 | 144 | 83.7% |

Reference prices are frozen per run. Timings include retry waits; interpret them alongside cache-hit rates. Tables cover the listed benchmark run IDs; preflights and abandoned trials remain in the audit database. Both modes share the identical first-attempt extraction/cache. Actual cost is recorded as zero for configured free tiers; reference cost is a hypothetical paid-token estimate. Failed calls without usage report zero known tokens.

### Verified replay with the same settings

| Replay | Model | New tokens | Reference cost | Hit rate | Reference cost saved vs first verified run | Avg time/company |
| --- | --- | --- | --- | --- | --- | --- |
| full-gemini-lite-cache-v1 | gemini-3.5-flash-lite | 0 | $ 0.000000 | 100.0% | $ 0.509556 | 0.292s |

## Consistency review leads

These heuristic flags may reflect rounding, segments or component amounts; they do not alter accuracy.

| Run | Ticker | Metric | Verified table | Nearby prose | Prose quote |
| --- | --- | --- | --- | --- | --- |
| full-gemini-lite-v1 | ADBE | revenue | 23769000000.0 | 17650000000.0 | Digital Media revenue of $17.65 billion during fiscal 2025 increased by $1.79 billion, or 11%, compared to fiscal 2024. |
| full-gemini-lite-v1 | ADBE | revenue | 23769000000.0 | 17650000000.0 | Digital Media segment revenue grew to $17.65 billion in fiscal 2025, up from $15.86 billion in fiscal 2024, representing 11% year-over-year growth. |
| full-gemini-lite-v1 | ADBE | revenue | 23769000000.0 | 1790000000.0 | Revenue from Digital Media increased $1.79 billion and revenue from Digital Experience increased $498 million during fiscal 2025 as compared to fiscal 2024. |
| full-gemini-lite-v1 | ADBE | revenue | 23769000000.0 | 2550000000.0 | Cost of revenue of $2.55 billion during fiscal 2025 increased by $193 million, or 8%, compared to fiscal 2024. |
| full-gemini-lite-v1 | ADBE | revenue | 23769000000.0 | 5410000000.0 | Subscription revenue grew to $5.41 billion in fiscal 2025, up from $4.86 billion in fiscal 2024, representing 11% year-over-year growth. |
| full-gemini-lite-v1 | ADBE | revenue | 23769000000.0 | 5410000000.0 | Subscription revenue grew to $5.41 billion in fiscal 2025, up from $4.86 billion in fiscal 2024, representing 11% |
| full-gemini-lite-v1 | ADBE | revenue | 23769000000.0 | 5860000000.0 | Digital Experience revenue of $5.86 billion during fiscal 2025 increased by $498 million, or 9%, compared to fiscal 2024. |
| full-gemini-lite-v1 | ADBE | revenue | 23769000000.0 | 5860000000.0 | Digital Experience revenue was $5.86 billion in fiscal 2025, up from $5.37 billion in fiscal 2024, representing 9% year-over-year growth. |
| full-gemini-lite-v1 | CRM | net_income | 7457000000.0 | 7500000000.0 | The net cash provided by operating activities during fiscal 2026 was primarily comprised of net income of $7.5 billion, adjusted for non-cash items, including $3.6 billion of depreciation and amortization and $3.5 billion of stock-based compensation expense. |
| full-gemini-lite-v1 | CRM | operating_cash_flow | 14996000000.0 | 1000000000.0 | Net cash provided by operating activities during fiscal 2026 was further benefited by the changes in accounts payable and accrued expenses and other liabilities of $1.0 billion and unearned revenue of $2.9 billion, partially offset by the change in accounts receivable, net of $2.2 billion and costs |
| full-gemini-lite-v1 | CRM | operating_cash_flow | 14996000000.0 | 7500000000.0 | The net cash provided by operating activities during fiscal 2026 was primarily comprised of net income of $7.5 billion, adjusted for non-cash items, including $3.6 billion of depreciation and amortization and $3.5 billion of stock-based compensation expense. |
| full-gemini-lite-v1 | CRM | revenue | 41525000000.0 | 388000000.0 | (2) Agentforce 360 Platform, Slack and Other revenue for the year ended January 31, 2026 includes $388 million in subscription and support revenue from Informatica, Inc. |
| full-gemini-lite-v1 | CRM | revenue | 41525000000.0 | 72400000000.0 | maining Performance Obligation: Total remaining performance obligation, which represents all future revenue under contract yet to be recognized, as of January 31, 2026 was approximately $72.4 billion, an increase of 14 percent year-over-year . |
| full-gemini-lite-v1 | GOOGL | operating_income | 129039000000.0 | 18100000000.0 | Google Services operating income increased $18.1 billion from 2024 to 2025. |
| full-gemini-lite-v1 | GOOGL | operating_income | 129039000000.0 | 7800000000.0 | Google Cloud operating income increased $7.8 billion from 2024 to 2025. |
| full-gemini-lite-v1 | GOOGL | revenue | 402836000000.0 | 15500000000.0 | Google Cloud revenues increased $15.5 billion from 2024 to 2025, primarily driven by growth in Google Cloud Platform largely from infrastructure and platform services. |
| full-gemini-lite-v1 | GOOGL | revenue | 402836000000.0 | 16200000000.0 | Cost of revenues increased $16.2 billion from 2024 to 2025 due to an increase in other cost of revenues and TAC of $11.2 billion and $5.0 billion, respectively. |
| full-gemini-lite-v1 | GOOGL | revenue | 402836000000.0 | 26400000000.0 | Google Search & other revenues increased $26.4 billion from 2024 to 2025. |
| full-gemini-lite-v1 | GOOGL | revenue | 402836000000.0 | 4200000000.0 | YouTube ads revenues increased $4.2 billion from 2024 to 2025. |
| full-gemini-lite-v1 | GOOGL | revenue | 402836000000.0 | 567000000.0 | Google Network revenues decreased $567 million from 2024 to 2025, primarily due to a decrease in AdSense revenues, partially offset by an increase in AdMob revenues. |
| full-gemini-lite-v1 | GOOGL | revenue | 402836000000.0 | 7700000000.0 | Google subscriptions, platforms, and devices revenues increased $7.7 billion from 2024 to 2025. |
| full-gemini-lite-v1 | META | net_income | 60458000000.0 | 20430000000.0 | Cash provided by operating activities during 2025 mostly consisted of $60.46 billion net income adjusted for certain non-cash items, such as $20.43 billion of share-based compensation expense, $18.74 billion of deferred income taxes, and $18.62 billion of depreciation and amortization expense. |
| full-gemini-lite-v1 | META | operating_cash_flow | 115800000000.0 | 60460000000.0 | Cash provided by operating activities during 2025 mostly consisted of $60.46 billion net income adjusted for certain non-cash items, such as $20.43 billion of share-based compensation expense, $18.74 billion of deferred income taxes, and $18.62 billion of depreciation and amortization expense. |
| full-gemini-lite-v1 | META | operating_income | 83276000000.0 | 15360000000.0 | FoA income from operations in 2025 increased $15.36 billion, or 18%, compared to 2024. |
| full-gemini-lite-v1 | META | revenue | 200966000000.0 | 35540000000.0 | Advertising revenue in 2025 increased $35.54 billion, or 22%, compared to 2024 due to increases in ad impressions delivered and average price per ad. |
| full-gemini-lite-v1 | META | revenue | 200966000000.0 | 36400000000.0 | FoA revenue in 2025 increased $36.40 billion, or 22%, compared to 2024. |
| full-gemini-lite-v1 | META | revenue | 200966000000.0 | 6010000000.0 | Cost of revenue in 2025 increased $6.01 billion, or 20%, compared to 2024. |
| full-gemini-lite-v1 | META | revenue | 200966000000.0 | 61000000.0 | RL revenue in 2025 increased $61 million, or 3%, compared to 2024. |
| full-gemini-lite-v1 | META | revenue | 200966000000.0 | 862000000.0 | FoA other revenue in 2025 increased $862 million, or 50%, compared to 2024. |
| full-gemini-lite-v1 | NFLX | net_income | 10981201000.0 | 2270000000.0 | Net income for the year ended December 31, 2025 increased $2,270 million as compared to the prior comparative period, primarily due to a $2,909 million increase in operating income, driven by a $6,182 million increase in revenues and partially offset by a $2,237 million increase in cost of revenues |
| full-gemini-lite-v1 | NFLX | operating_cash_flow | 10149273000.0 | 2788000000.0 | Net cash provided by operating activities for the year ended December 31, 2025 increased $2,788 million as compared to the year ended December 31, 2024, primarily driven by a $2,270 million or 26% increase in net income and a $1,646 million increase in adjustments for non-cash expenses, partially of |
| full-gemini-lite-v1 | NVDA | operating_income | 130387000000.0 | 4500000000.0 | Reportable segment operating income – The year over year increase in Compute & Networking segment operating income was driven by growth in revenue, partially offset by a $4.5 billion charge associated with H20 excess inventory and purchase obligations in the first quarter of fiscal year 2026. |
| full-gemini-lite-v1 | NVDA | revenue | 215938000000.0 | 4500000000.0 | he year over year increase in Compute & Networking segment operating income was driven by growth in revenue, partially offset by a $4.5 billion charge associated with H20 excess inventory and purchase obligations in the first quarter of fiscal year 2026. |
| full-gemini-lite-v1 | ORCL | net_income | 17087000000.0 | 42700000000.0 | apital as of May 31, 2026 in comparison to May 31, 2025 was primarily due to favorable impacts from net income; proceeds from the issuance of senior notes, net of issuance costs, of $42.7 billion during fiscal 2026; $5.0 billion of cash proceeds from the issuance of Mandatory Convertible Preferred S |
| full-gemini-lite-v1 | ORCL | net_income | 17087000000.0 | 4600000000.0 | ctivities increased by $11.2 billion in fiscal 2026 relative to fiscal 2025 primarily due to higher net income adjusted for certain non-cash charges and higher cash favorable working capital changes, net, which includes $4.6 billion cash inflows from customer prepayments with significant financing c |
| full-gemini-lite-v1 | ORCL | operating_cash_flow | 31977000000.0 | 11200000000.0 | Net cash provided by operating activities increased by $11.2 billion in fiscal 2026 relative to fiscal 2025 primarily due to higher net income adjusted for certain non-cash charges and higher cash favorable working capital changes, net, which includes $4.6 billion cash inflows from customer prepayme |
| full-gemini-lite-v1 | ORCL | revenue | 67357000000.0 | 1000000.0 | For example, if an entity reporting in Euros had revenues of 1.0 million Euros from products sold on May 31, 2026 and 2025, our financial statements would reflect reported revenues of $1.16 million in fiscal 2026 (using 1.16 as the applicable average exchange rate for the period) and $1.13 million |
| full-gemini-lite-v1 | ORCL | revenue | 67357000000.0 | 10000000000.0 | Total revenues increased by $10.0 billion in reported currency in fiscal 2026 relative to fiscal 2025 due to a $9.3 billion increase in cloud and software revenues, a $510 million increase in services revenues and a $148 million increase in hardware revenues, in each case during fiscal 2026 relative |
| full-gemini-lite-v1 | ORCL | revenue | 67357000000.0 | 1160000.0 | Euros from products sold on May 31, 2026 and 2025, our financial statements would reflect reported revenues of $1.16 million in fiscal 2026 (using 1.16 as the applicable average exchange rate for the period) and $1.13 million in fiscal 2025 (using 1.13 as the applicable average exchange rate for th |
| full-gemini-lite-v1 | ORCL | revenue | 67357000000.0 | 148000000.0 | Total hardware revenues increased by $148 million in reported currency in fiscal 2026 relative to fiscal 2025. |
| full-gemini-lite-v1 | ORCL | revenue | 67357000000.0 | 148000000.0 | due to a $9.3 billion increase in cloud and software revenues, a $510 million increase in services revenues and a $148 million increase in hardware revenues, in each case during fiscal 2026 relative to fiscal 2025. |
| full-gemini-lite-v1 | ORCL | revenue | 67357000000.0 | 510000000.0 | Total services revenues increased by $510 million in reported currency in fiscal 2026 relative to fiscal 2025. |
| full-gemini-lite-v1 | ORCL | revenue | 67357000000.0 | 510000000.0 | urrency in fiscal 2026 relative to fiscal 2025 due to a $9.3 billion increase in cloud and software revenues, a $510 million increase in services revenues and a $148 million increase in hardware revenues, in each case during fiscal 2026 relative to fiscal 2025. |
| full-gemini-lite-v1 | ORCL | revenue | 67357000000.0 | 9300000000.0 | Our cloud and software business’ total revenues increased by $9.3 billion in reported currency in fiscal 2026 relative to fiscal 2025 primarily due to an increase in cloud revenues as customers purchased our applications and infrastructure technologies and renewed their related cloud contracts. |

## Limitations

- Free hosted models, 15 companies and the configured form type(s); results describe this sample.

- Model architectures and generation settings differ across model families; compare the recorded configurations. Open-model parameter counts describe total rather than necessarily active parameters.

- XBRL tag coverage can be incomplete. Missing ground truth is excluded and shown separately; accession matching is never relaxed.

- Configured parent-attributable income/equity tags can differ from consolidated totals including noncontrolling interests. Segment/component values are also distinct from company totals.

- Quote, number, scale, year and sanity checks cannot prove that a quoted row/column denotes the requested financial concept.

- Conservative checks can abstain on correct financial values when scale or quotation validation fails.

- Some filings require whole-document section fallback or incorporate statements by reference; source coverage affects retrieval.

- Provider errors and free quotas affect coverage and time. Zero known usage on an error does not prove the server did no work.

## Reproducibility

Main run IDs: full-gemini-lite-v1.

Re-run dv report with these run IDs and optional cache run IDs. All result numbers are recomputed from SQLite.

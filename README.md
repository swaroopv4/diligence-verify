# Diligence Verify

Diligence Verify extracts 9 financial numbers from 15 public companies’ SEC 10-K filings, verifies source quotes, numbers, scales, fiscal columns and financial row labels with deterministic code, and checks the results against SEC XBRL. The read-only Streamlit dashboard includes traceable filing evidence, caught errors and measured cost per company. No API keys are required.

| Mode | Model | Correct | Wrong | Unverified | Not found | No ground truth | Precision on answered |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline | gemini-3.5-flash-lite | 109 | 5 | 0 | 17 | 4 | 95.6% |
| Verified | gemini-3.5-flash-lite | 111 | 0 | 3 | 17 | 4 | 100.0% |

Code verification removed all 5 wrong answers: 3 corrected on retry, 2 flagged for human review.

**Unverified · flagged for review: 3**
includes 2 caught baseline errors

Each mode covers 135 facts; missing ground truth is excluded from precision.

## Examples

- INTC operating income: $12.70B vs XBRL −$2.21B; corrected to −$2.21B.
- INTC stockholders equity: $126.36B vs XBRL $114.28B; corrected to $114.28B.
- ORCL stockholders equity: $43.06B vs XBRL $42.51B; corrected to $42.51B.

## Verification

- V1: Source belongs to this filing.
- V2: Quote matches the source exactly.
- V3: Displayed number is copied exactly.
- V4: Number can be parsed.
- V5: Scale and per-share units are supported.
- V6: Selected column matches the fiscal period.
- V7: Financial sanity checks.
- V8: Row label and financial scope match.

## Cost per company

- Baseline: $0.11 at reference token prices; 45s average.
- Verified: $0.14 at reference token prices; 58s average.

## Limitations

One model, 15 companies, 10-K filings only. Ground-truth coverage is incomplete; precision does not measure missing answers. Intel section labels remain unknown because its Item references are in an index rather than body headings. Results describe this sample and do not guarantee financial correctness.

## Run locally

Use Python 3.11, then:

```bash
git clone https://github.com/swaroopV4/diligence-verify.git
cd diligence-verify
python -m venv .venv
# Activate .venv (Windows: .venv\Scripts\Activate.ps1; Linux/macOS: source .venv/bin/activate)
python -m pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

[Full results](reports/results.md) · [GitHub](https://github.com/swaroopV4/diligence-verify)

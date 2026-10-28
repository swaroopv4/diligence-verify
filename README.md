# Diligence Verify

Diligence Verify compares LLM extraction of 9 financial metrics from 15 public companies' SEC 10-K filings with deterministic source, scale, period-column and row-scope checks, then evaluates the results against accession-matched SEC XBRL. The read-only dashboard presents the measured baseline and latest verified results, caught errors, exact filing evidence, and recorded cost/cache statistics. It runs entirely from the committed SQLite database and public filing snapshots, with no API keys or live model calls.

**Live app:** [YOUR-APP-NAME.streamlit.app](https://YOUR-APP-NAME.streamlit.app) — placeholder; deployment has not been published.

## Headline results

| Mode | Model | Correct | Wrong | Unverified | Not found | Precision |
| --- | --- | --- | --- | --- | --- | --- |
| Baseline | gemini-3.5-flash-lite | 109 | 5 | 0 | 17 | 95.6% |
| Verified | gemini-3.5-flash-lite | 111 | 0 | 3 | 17 | 100.0% |

The table is generated from `data/runs.db`. Each mode has 131 facts with ground truth; 4 cases without matching XBRL data are excluded from accuracy. Precision is correct / (correct + wrong), not coverage. The second-model benchmark remains pending. These observed results do not guarantee financial correctness on other filings. Detailed diagnosis and limitations: [Phase 5b results](reports/phase5b-results.md).

## Run the dashboard locally

Use **Python 3.11** (the version tested for deployment). Clone this standalone repository, then run from its root:

```bash
git clone <YOUR_GITHUB_REPOSITORY_URL> diligence-verify
cd diligence-verify
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

Install only the dashboard dependencies and start it:

```bash
python -m pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

No `.env`, Streamlit secrets, SEC identity or model credentials are required. The app opens the database read-only, verifies source snapshot hashes, and makes no live SEC or LLM requests. It can run without an internet connection after dependencies are installed. The source checkout is loaded directly; do not run `pip install -e .` for deployment, because that installs the separate research pipeline dependencies.

## Deploy on Streamlit Community Cloud

1. Push this standalone repository to your own GitHub repository. The prepared local branch is `codex/streamlit-cloud`.
2. In Community Cloud, create an app using that repository and branch.
3. Set the entrypoint to `app/streamlit_app.py`.
4. In Advanced settings, choose **Python 3.11** and leave Secrets empty.
5. Deploy, then replace the live-app placeholder above with the assigned URL.

Community Cloud installs the pinned dashboard-only `requirements.txt` from the repository root. The research `pyproject.toml` is not the deployment dependency file. See the official [dependency guidance](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies) and [deployment settings](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy).

## Committed data and cost interpretation

`data/runs.db` and the 15 immutable source snapshots listed in [data/deployment-manifest.json](data/deployment-manifest.json) are included in Git. The manifest records sizes and SHA-256 hashes; source paths written on Windows are normalized when read on Linux. Raw downloads and unused working copies are excluded. Partial research trials remain in the database audit history but do not appear as completed comparisons.

Accuracy uses the latest verified rules and the compatible original baseline. Cost cards/charts use recorded uncached-call costs from the first completed study, never the all-cache replay. That first study already had some cache reuse, so no fully cold end-to-end cost or speed claim is made. The cache comparison uses the original verified run and its same-settings, identical-result replay.

## Optional research development

To download filings or run new model experiments, install the full project separately with `python -m pip install -e .`, copy `.env.example` to `.env`, and configure your own SEC contact/model credentials. These steps are unnecessary for the deployed dashboard. Never commit `.env` or `.streamlit/secrets.toml`. The benchmark's source-verification and answer-key isolation rules are in [AGENTS.md](AGENTS.md); validation and development history are in [PROGRESS.md](PROGRESS.md).

```bash
python -m pytest
python -m dv.cli --help
```

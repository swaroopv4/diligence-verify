"""Identified, rate-limited SEC JSON access. No financial statement parsing."""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections.abc import Callable
from types import TracebackType
from typing import Any, Self

import httpx
from pydantic import BaseModel, TypeAdapter
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential

from dv.config import SECSettings
from dv.models import FilingMetadata

logger = logging.getLogger(__name__)


class TickerEntry(BaseModel):
    cik_str: int
    ticker: str
    title: str


class SubmissionRows(BaseModel):
    accessionNumber: list[str]
    filingDate: list[str]
    reportDate: list[str]
    form: list[str]
    primaryDocument: list[str]

    def latest_10k(self, ticker: str, cik: int) -> FilingMetadata | None:
        rows: list[FilingMetadata] = []
        columns = [self.accessionNumber, self.filingDate, self.reportDate, self.form, self.primaryDocument]
        if len({len(column) for column in columns}) != 1:
            raise ValueError("SEC submission arrays have inconsistent lengths")
        for accession, filed, period, form, document in zip(*columns, strict=True):
            if form == "10-K":
                rows.append(FilingMetadata(ticker=ticker, cik=cik, accession=accession,
                                          filing_date=filed, period_of_report=period,
                                          primary_document=document))
        return max(rows, key=lambda row: row.filing_date) if rows else None


class HistoricalFile(BaseModel):
    name: str


class SubmissionFilings(BaseModel):
    recent: SubmissionRows
    files: list[HistoricalFile] = []


class Submissions(BaseModel):
    filings: SubmissionFilings


def retryable(error: BaseException) -> bool:
    if isinstance(error, httpx.TransportError):
        return True
    return isinstance(error, httpx.HTTPStatusError) and (
        error.response.status_code == 429 or error.response.status_code >= 500
    )


class SECClient:
    """One shared instance serializes requests below the configured SEC ceiling."""

    def __init__(self, settings: SECSettings, *, transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        identity = os.environ.get(settings.user_agent_env, "").strip()
        if not re.fullmatch(r".+\s+[^\s@]+@[^\s@]+\.[^\s@]+", identity) or any(
            placeholder in identity.lower() for placeholder in ("your name", "your@email", "example.com")
        ):
            raise ValueError(f"Set {settings.user_agent_env} to your real name and email in the project .env")
        self.user_agent = identity
        self._http = httpx.Client(headers={"User-Agent": identity, "Accept": "application/json"},
                                  timeout=60, transport=transport, follow_redirects=True)
        self._interval = 1 / settings.max_requests_per_second
        self._last_request: float | None = None
        self._lock = threading.Lock()
        self._sleep = sleep
        self._clock = clock

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 traceback: TracebackType | None) -> None:
        self._http.close()

    def _throttle(self) -> None:
        with self._lock:
            if self._last_request is not None:
                delay = self._interval - (self._clock() - self._last_request)
                if delay > 0:
                    self._sleep(delay)
            self._last_request = self._clock()

    def get_json(self, url: str, *, ticker: str, step: str, mode: str = "evaluation") -> dict[str, Any]:
        for attempt in Retrying(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, max=8),
                                retry=retry_if_exception(retryable), sleep=self._sleep, reraise=True):
            with attempt:
                self._throttle()
                try:
                    response = self._http.get(url)
                    response.raise_for_status()
                    return TypeAdapter(dict[str, Any]).validate_python(response.json())
                except Exception:
                    logger.exception("ticker=%s step=%s mode=%s url=%s attempt=%s",
                                     ticker, step, mode, url, attempt.retry_state.attempt_number)
                    raise
        raise RuntimeError("Unreachable retry state")

    def cik_for_ticker(self, ticker: str) -> int:
        payload = self.get_json("https://www.sec.gov/files/company_tickers.json", ticker=ticker, step="cik_lookup")
        entries = TypeAdapter(dict[str, TickerEntry]).validate_python(payload)
        for entry in entries.values():
            if entry.ticker.upper() == ticker.upper():
                return entry.cik_str
        raise ValueError(f"No SEC CIK found for ticker {ticker!r}")

    def latest_filing(self, ticker: str, cik: int | None = None) -> FilingMetadata:
        ticker = ticker.upper()
        cik = cik or self.cik_for_ticker(ticker)
        payload = self.get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", ticker=ticker, step="filing_metadata")
        submissions = Submissions.model_validate(payload)
        recent = submissions.filings.recent.latest_10k(ticker, cik)
        if recent is not None:
            return recent
        historical: list[FilingMetadata] = []
        for item in submissions.filings.files:
            data = self.get_json(f"https://data.sec.gov/submissions/{item.name}", ticker=ticker, step="historical_metadata")
            filing = SubmissionRows.model_validate(data).latest_10k(ticker, cik)
            if filing is not None:
                historical.append(filing)
        if not historical:
            raise ValueError(f"No 10-K found for {ticker}")
        return max(historical, key=lambda row: row.filing_date)

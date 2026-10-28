"""Offline configuration contract tests."""
import pytest
from pydantic import ValidationError

from dv.config import LLMSettings, SECSettings, load_config


def test_spec_configuration_loads() -> None:
    config = load_config()
    assert len(config.metrics) == 9
    assert len(config.companies.full) == 15
    assert config.companies.dev == ["AAPL", "MSFT", "CRM"]
    assert config.llm.temperature == 0


def test_sec_rate_stays_under_limit() -> None:
    with pytest.raises(ValidationError):
        SECSettings(max_requests_per_second=10)


def test_nonzero_temperature_rejected() -> None:
    data = load_config().llm.model_dump()
    data["temperature"] = 1
    with pytest.raises(ValidationError):
        LLMSettings.model_validate(data)

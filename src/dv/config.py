"""Validated project configuration; secrets are loaded only from the project .env."""
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SECSettings(SettingsModel):
    user_agent_env: str = "SEC_USER_AGENT"
    max_requests_per_second: float = Field(default=8, gt=0, le=8)


class CompanySettings(SettingsModel):
    dev: list[str]
    full: list[str]


class FilingSettings(SettingsModel):
    form: Literal["10-K"] = "10-K"
    which: Literal["latest"] = "latest"


class ProviderSettings(SettingsModel):
    name: str
    base_url: str
    api_key_env: str | None
    model: str
    thinking_level: Literal["minimal", "low", "medium", "high"] | None = None


class ReferencePrices(SettingsModel):
    input: float = Field(default=3, ge=0)
    output: float = Field(default=15, ge=0)


class LLMSettings(SettingsModel):
    temperature: Literal[0] = 0
    max_output_tokens: int = Field(default=2000, gt=0)
    timeout_seconds: float = Field(default=120, gt=0)
    providers: list[ProviderSettings]
    reference_prices_per_million: ReferencePrices


class RetrievalSettings(SettingsModel):
    top_k: int = Field(default=5, gt=0)
    retry_extra_k: int = Field(default=5, gt=0)


class VerificationSettings(SettingsModel):
    max_retries: int = Field(default=2, ge=0)
    relative_tolerance: float = Field(default=0.005, ge=0)
    eps_absolute_tolerance: float = Field(default=0.01, ge=0)


class MetricSettings(SettingsModel):
    kind: Literal["duration", "instant"]
    unit: Literal["USD", "USD/shares"]
    query: str
    xbrl_tags: list[str] = Field(min_length=1)
    row_labels: list[str] = Field(default_factory=list)
    exclude_labels: list[str] = Field(default_factory=list)


class AppConfig(SettingsModel):
    sec: SECSettings
    companies: CompanySettings
    filing: FilingSettings
    llm: LLMSettings
    retrieval: RetrievalSettings
    verification: VerificationSettings
    metrics: dict[str, MetricSettings]


def project_root() -> Path:
    """Resolve the editable project independently of the caller's working directory."""
    return Path(__file__).resolve().parents[2]


def load_config(path: Path | None = None) -> AppConfig:
    # Research-only dependencies are unnecessary for the read-only dashboard.
    import yaml
    from dotenv import load_dotenv

    config_path = path or project_root() / "config.yaml"
    load_dotenv(config_path.parent / ".env", override=False)
    with config_path.open(encoding="utf-8") as stream:
        return AppConfig.model_validate(yaml.safe_load(stream))

"""One schema-validated financial extraction, without deterministic verification."""
from typing import Literal

from pydantic import create_model

from dv.llm import CallContext, LLMClient
from dv.models import Chunk, ExtractedFact, FilingMetadata
from dv.prompts import extraction_prompt


def extract_fact(client: LLMClient, context: CallContext, metric: str, query: str,
                 filing: FilingMetadata, chunks: list[Chunk], feedback: str | None = None) -> ExtractedFact:
    prompt = extraction_prompt(metric, query, filing, chunks, feedback)
    schema = create_model(f"ExtractedFact_{metric}", __base__=ExtractedFact,
                          metric=(Literal[metric], ...))
    fact = client.complete(prompt, schema, context, pin_model=True)
    return ExtractedFact.model_validate(fact.model_dump())

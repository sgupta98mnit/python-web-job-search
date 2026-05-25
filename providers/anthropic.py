"""Anthropic provider using forced tool use for structured output."""

from __future__ import annotations

import logging
import time
from typing import Any

from anthropic import Anthropic
from pydantic import ValidationError

from .base import (
    SCORED_JOB_SCHEMA,
    SYSTEM_PROMPT,
    BatchOutcome,
    LLMCallRecord,
    LLMProvider,
    ScoredJob,
    build_user_prompt,
)

log = logging.getLogger(__name__)


_TOOL = {
    "name": "submit_scores",
    "description": "Return scored job results matching the schema.",
    "input_schema": SCORED_JOB_SCHEMA,
}


class AnthropicProvider(LLMProvider):
    provider_name = "anthropic"

    def __init__(self, *, api_key: str | None, model: str) -> None:
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required for the anthropic provider")
        self.client = Anthropic(api_key=api_key)
        self.model = model

    def score_batch(self, results: list[dict], criteria: str) -> BatchOutcome:
        outcome = BatchOutcome(provider=self.provider_name, model=self.model)
        if not results:
            return outcome
        prompt = build_user_prompt(results, criteria)

        for attempt in (1, 2):
            t0 = time.monotonic()
            err: str | None = None
            raw: dict[str, Any] | None = None
            payload: dict | None = None
            try:
                resp = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    tools=[_TOOL],
                    tool_choice={"type": "tool", "name": "submit_scores"},
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = resp.model_dump()
                payload = self._extract_tool_payload(raw)
            except Exception as e:
                err = str(e)[:2000]
                log.warning("anthropic call failed (attempt %d): %s", attempt, e)

            latency_ms = int((time.monotonic() - t0) * 1000)
            parsed = self._validate(payload) if payload else []
            outcome.calls.append(
                LLMCallRecord(
                    mode="tool_call",
                    attempt=attempt,
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=prompt,
                    raw_response=raw,
                    parsed_ok=bool(parsed),
                    latency_ms=latency_ms,
                    error=err,
                )
            )
            if parsed:
                outcome.scored = parsed
                return outcome

        log.warning("Giving up on Anthropic batch of %d results", len(results))
        return outcome

    @staticmethod
    def _extract_tool_payload(raw: dict) -> dict | None:
        for block in raw.get("content", []):
            if block.get("type") == "tool_use":
                return block.get("input") or {}
        return None

    @staticmethod
    def _validate(payload: dict) -> list[ScoredJob]:
        jobs_raw = payload.get("jobs")
        if not isinstance(jobs_raw, list):
            return []
        out: list[ScoredJob] = []
        for item in jobs_raw:
            try:
                out.append(ScoredJob.model_validate(item))
            except ValidationError as e:
                log.debug("dropping invalid item: %s", e)
        return out

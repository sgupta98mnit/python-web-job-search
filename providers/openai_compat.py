"""One provider for every OpenAI-compatible endpoint.

Covers: OpenAI, Ollama, NVIDIA NIM, Groq, OpenRouter, LM Studio, vLLM, etc.
Returns BatchOutcome so the pipeline can persist every request/response.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from openai import OpenAI, APIStatusError, APIConnectionError, RateLimitError
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


_SCORE_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_scores",
        "description": "Return scored job results.",
        "parameters": SCORED_JOB_SCHEMA,
    },
}


class _RateLimiter:
    """Simple req-per-minute limiter."""

    def __init__(self, rpm: int | None):
        self.rpm = rpm
        self.window: list[float] = []
        self.lock = threading.Lock()

    def wait(self) -> None:
        if not self.rpm:
            return
        with self.lock:
            now = time.monotonic()
            self.window = [t for t in self.window if now - t < 60.0]
            if len(self.window) >= self.rpm:
                sleep_for = 60.0 - (now - self.window[0]) + 0.1
                if sleep_for > 0:
                    log.info("Rate-limit pause: %.1fs", sleep_for)
                    time.sleep(sleep_for)
                    now = time.monotonic()
                    self.window = [t for t in self.window if now - t < 60.0]
            self.window.append(time.monotonic())


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        *,
        provider_name: str,
        base_url: str,
        api_key: str | None,
        model: str,
        rpm_limit: int | None = None,
    ) -> None:
        self.provider_name = provider_name
        self.client = OpenAI(base_url=base_url, api_key=api_key or "not-needed")
        self.model = model
        self.limiter = _RateLimiter(rpm_limit)

    def score_batch(self, results: list[dict], criteria: str) -> BatchOutcome:
        outcome = BatchOutcome(provider=self.provider_name, model=self.model)
        if not results:
            return outcome
        prompt = build_user_prompt(results, criteria)
        attempt = 0

        for round_idx in (1, 2):
            # --- tool-calling attempt ---
            attempt += 1
            self.limiter.wait()
            rec = self._call(
                prompt, mode="tool_call", attempt=attempt, use_tools=True, retry=False
            )
            outcome.calls.append(rec)
            if rec.raw_response is not None:
                parsed = self._parse_payload(self._extract_arguments(rec.raw_response))
                if parsed:
                    rec.parsed_ok = True
                    outcome.scored = parsed
                    return outcome

            # --- json-only fallback ---
            attempt += 1
            self.limiter.wait()
            mode = "json_only_retry" if round_idx == 2 else "json_only"
            rec = self._call(
                prompt,
                mode=mode,
                attempt=attempt,
                use_tools=False,
                retry=(round_idx == 2),
            )
            outcome.calls.append(rec)
            if rec.raw_response is not None:
                content = self._extract_content(rec.raw_response)
                parsed = self._parse_payload(content)
                if parsed:
                    rec.parsed_ok = True
                    outcome.scored = parsed
                    return outcome

        log.warning("Giving up on batch of %d results", len(results))
        return outcome

    # ------------------------------------------------------------------
    _MAX_429_RETRIES = 6
    _BASE_BACKOFF = 5.0
    _MAX_BACKOFF = 60.0

    def _create_with_retry(self, kwargs: dict[str, Any], *, mode: str, attempt: int):
        """Call chat.completions.create, retrying on 429/rate-limit with backoff.

        The provider's RPM limiter is best-effort; the server may still 429
        (concurrent calls, short bursts, shared per-key quotas). Retry rather
        than give up on the batch."""
        for tries in range(self._MAX_429_RETRIES + 1):
            try:
                return self.client.chat.completions.create(**kwargs)
            except RateLimitError as e:
                if tries >= self._MAX_429_RETRIES:
                    raise
                delay = self._retry_delay(e, tries)
                log.warning(
                    "%s 429 rate-limit (mode=%s attempt=%d retry=%d/%d): sleeping %.1fs",
                    self.provider_name, mode, attempt, tries + 1,
                    self._MAX_429_RETRIES, delay,
                )
                time.sleep(delay)
            except APIStatusError as e:
                # Some providers return 429-equivalents under different codes.
                if getattr(e, "status_code", None) == 429 and tries < self._MAX_429_RETRIES:
                    delay = self._retry_delay(e, tries)
                    log.warning(
                        "%s 429 (APIStatusError) retry %d/%d, sleeping %.1fs",
                        self.provider_name, tries + 1, self._MAX_429_RETRIES, delay,
                    )
                    time.sleep(delay)
                    continue
                raise
            except APIConnectionError as e:
                if tries >= self._MAX_429_RETRIES:
                    raise
                delay = self._retry_delay(e, tries)
                log.warning(
                    "%s connection error retry %d/%d, sleeping %.1fs: %s",
                    self.provider_name, tries + 1, self._MAX_429_RETRIES, delay, e,
                )
                time.sleep(delay)
        # unreachable
        raise RuntimeError("retry loop exited unexpectedly")

    def _retry_delay(self, err: Exception, tries: int) -> float:
        # Honor Retry-After header when the server provides one.
        try:
            resp = getattr(err, "response", None)
            if resp is not None:
                ra = resp.headers.get("Retry-After") or resp.headers.get("retry-after")
                if ra:
                    return min(float(ra), self._MAX_BACKOFF)
        except (AttributeError, ValueError, TypeError):
            pass
        return min(self._BASE_BACKOFF * (2 ** tries), self._MAX_BACKOFF)

    def _call(
        self,
        prompt: str,
        *,
        mode: str,
        attempt: int,
        use_tools: bool,
        retry: bool,
    ) -> LLMCallRecord:
        sys_prompt = SYSTEM_PROMPT
        user = prompt
        if retry:
            user += (
                "\n\nReturn ONLY a JSON object with a top-level `jobs` array. "
                "No prose, no markdown fences."
            )

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
        }
        if use_tools:
            kwargs["tools"] = [_SCORE_TOOL]
            kwargs["tool_choice"] = {
                "type": "function",
                "function": {"name": "submit_scores"},
            }

        t0 = time.monotonic()
        try:
            resp = self._create_with_retry(kwargs, mode=mode, attempt=attempt)
            latency_ms = int((time.monotonic() - t0) * 1000)
            raw = resp.model_dump()
            return LLMCallRecord(
                mode=mode,
                attempt=attempt,
                system_prompt=sys_prompt,
                user_prompt=user,
                raw_response=raw,
                parsed_ok=False,
                latency_ms=latency_ms,
                error=None,
            )
        except Exception as e:
            latency_ms = int((time.monotonic() - t0) * 1000)
            log.warning("%s call failed (attempt %d, mode=%s): %s",
                        self.provider_name, attempt, mode, e)
            return LLMCallRecord(
                mode=mode,
                attempt=attempt,
                system_prompt=sys_prompt,
                user_prompt=user,
                raw_response=None,
                parsed_ok=False,
                latency_ms=latency_ms,
                error=str(e)[:2000],
            )

    @staticmethod
    def _extract_arguments(raw: dict) -> str:
        """Pull the tool-call arguments JSON string from a chat-completions dump."""
        try:
            choice = raw["choices"][0]["message"]
            calls = choice.get("tool_calls") or []
            if calls:
                return calls[0]["function"]["arguments"] or ""
            return choice.get("content") or ""
        except (KeyError, IndexError, TypeError):
            return ""

    @staticmethod
    def _extract_content(raw: dict) -> str:
        try:
            return raw["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError, TypeError):
            return ""

    @staticmethod
    def _parse_payload(raw: str) -> list[ScoredJob]:
        text = (raw or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return []
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return []
        if isinstance(data, list):
            data = {"jobs": data}
        jobs_raw = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(jobs_raw, list):
            return []
        out: list[ScoredJob] = []
        for item in jobs_raw:
            try:
                out.append(ScoredJob.model_validate(item))
            except ValidationError as e:
                log.debug("dropping invalid item: %s", e)
        return out

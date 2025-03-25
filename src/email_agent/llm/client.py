"""One code path for every model call.

Both providers speak the OpenAI chat API (Ollama exposes a compatible
endpoint), so a single client covers both. Structured output goes through
`beta.chat.completions.parse` with a pydantic schema; if the provider rejects
json_schema mode we fall back to json_object mode and validate ourselves.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Protocol, TypeVar

from openai import APIConnectionError, APIStatusError, OpenAI
from pydantic import BaseModel, ValidationError

from ..core.config import Provider
from ..core.errors import AnalysisError

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class StructuredCaller(Protocol):
    """What analyzers depend on. Tests substitute a fake."""

    def structured(
        self, schema: type[T], *, system: str, user: str, model: str | None = None
    ) -> T: ...

    def text(
        self, *, system: str, user: str, model: str | None = None, max_tokens: int = 256
    ) -> str: ...


class LLMClient:
    def __init__(
        self,
        provider: Provider,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.1,
        timeout: float = 90.0,
    ) -> None:
        self.provider = provider
        self.model = model
        self.temperature = temperature
        self.base_url = base_url or (
            "http://localhost:11434/v1" if provider == Provider.OLLAMA else None
        )
        if provider == Provider.OLLAMA:
            self._client = OpenAI(
                base_url=base_url or "http://localhost:11434/v1",
                api_key=api_key or "ollama",
                timeout=timeout,
            )
        else:
            if not api_key:
                raise AnalysisError("OPENAI_API_KEY is required for the openai provider")
            self._client = OpenAI(api_key=api_key, timeout=timeout)

    def ping(self) -> bool:
        try:
            self._client.models.list()
            return True
        except Exception as e:  # noqa: BLE001 - surface any transport failure as "not reachable"
            log.warning("LLM provider %s not reachable: %s", self.provider.value, e)
            return False

    def structured(self, schema: type[T], *, system: str, user: str, model: str | None = None) -> T:
        model = model or self.model
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            try:
                resp = self._client.beta.chat.completions.parse(
                    model=model,
                    messages=messages,
                    response_format=schema,
                    temperature=self.temperature,
                )
                parsed = resp.choices[0].message.parsed
                if parsed is not None:
                    return parsed
                raw = resp.choices[0].message.content or ""
            except (APIConnectionError, APIStatusError):
                raise
            except Exception as e:  # noqa: BLE001 - provider may not support json_schema
                log.debug("structured parse failed (%s); falling back to json_object", e)
                raw = self._json_object(schema, messages, model)
        except APIConnectionError as e:
            raise AnalysisError(self._unreachable()) from e
        except APIStatusError as e:
            raise AnalysisError(
                f"{self.provider.value} returned {e.status_code}: {e.message}"
            ) from e
        return self._coerce(schema, raw)

    def _unreachable(self) -> str:
        if self.provider == Provider.OLLAMA:
            return f"Cannot reach Ollama at {self.base_url}. Start it with `ollama serve` and pull `{self.model}`."
        return "Cannot reach the OpenAI API. Check your network and OPENAI_API_KEY."

    def text(
        self, *, system: str, user: str, model: str | None = None, max_tokens: int = 256
    ) -> str:
        resp = self._client.chat.completions.create(
            model=model or self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=self.temperature,
            max_tokens=max_tokens,
        )
        return (resp.choices[0].message.content or "").strip()

    def _json_object(
        self, schema: type[BaseModel], messages: list[dict[str, str]], model: str
    ) -> str:
        hint = (
            "\n\nRespond with a single JSON object matching this JSON schema exactly:\n"
            + json.dumps(schema.model_json_schema())
        )
        messages = [{**messages[0], "content": messages[0]["content"] + hint}, messages[1]]
        resp = self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=self.temperature,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content or ""

    @staticmethod
    def _coerce(schema: type[T], raw: str) -> T:
        try:
            return schema.model_validate_json(raw)
        except ValidationError:
            m = _JSON_BLOCK.search(raw)
            if m:
                try:
                    return schema.model_validate_json(m.group(0))
                except ValidationError as e:
                    raise AnalysisError(f"model returned invalid {schema.__name__}: {e}") from e
            raise AnalysisError(f"model returned no JSON for {schema.__name__}") from None


# Alias used in type hints throughout the package.
LLM = StructuredCaller

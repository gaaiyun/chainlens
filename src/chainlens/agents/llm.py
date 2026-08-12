"""OpenAI-compatible LLM providers used only for autonomous SQL planning."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Callable


class LLMConfigurationError(RuntimeError):
    """Required provider configuration is missing or invalid."""


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    base_url: str
    api_key: str
    model: str
    temperature: float = 0.0
    timeout_seconds: float = 60.0

    @classmethod
    def from_mapping(cls, source: Mapping[str, Any] | None = None) -> "LLMSettings":
        data = source or os.environ
        provider = str(data.get("LLM_PROVIDER") or "openai_compatible").strip()
        if provider == "openai_compatible":
            return cls(
                provider=provider,
                base_url=str(data.get("OPENAI_BASE_URL") or "https://sub.anzhiyu.com/v1"),
                api_key=str(data.get("OPENAI_API_KEY") or ""),
                model=str(data.get("OPENAI_MODEL") or "grok-4.5"),
                temperature=float(data.get("MODEL_TEMPERATURE") or 0.0),
                timeout_seconds=float(data.get("LLM_TIMEOUT_SECONDS") or 60),
            )
        if provider != "openai_compatible":
            raise ValueError(f"不支持的 LLM_PROVIDER: {provider}")
        raise AssertionError("openai_compatible mapping should have returned above")


class OpenAICompatibleProvider:
    def __init__(
        self,
        settings: LLMSettings | None = None,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.settings = settings or LLMSettings.from_mapping()
        if not self.settings.api_key:
            raise LLMConfigurationError("未配置 OPENAI_API_KEY")
        if client_factory is None:
            from openai import OpenAI

            client_factory = OpenAI
        self.client = client_factory(
            base_url=self.settings.base_url,
            api_key=self.settings.api_key,
            timeout=self.settings.timeout_seconds,
            max_retries=1,
        )
        self.name = self.settings.provider

    def complete(
        self,
        messages: Sequence[dict[str, str]],
        *,
        max_tokens: int = 600,
        temperature: float | None = None,
    ) -> str:
        response = self.client.chat.completions.create(
            model=self.settings.model,
            messages=list(messages),
            max_tokens=max_tokens,
            temperature=(
                self.settings.temperature if temperature is None else temperature
            ),
        )
        return (response.choices[0].message.content or "").strip()


class FallbackProvider:
    """Try the primary provider once, then an optional secondary provider."""

    def __init__(self, primary: Any, secondary: Any) -> None:
        self.primary = primary
        self.secondary = secondary
        self.last_provider = getattr(primary, "name", type(primary).__name__)

    def complete(self, messages: Sequence[dict[str, str]], **kwargs: Any) -> str:
        try:
            result = self.primary.complete(messages, **kwargs)
            self.last_provider = getattr(
                self.primary, "name", type(self.primary).__name__
            )
            return result
        except Exception:
            result = self.secondary.complete(messages, **kwargs)
            self.last_provider = getattr(
                self.secondary, "name", type(self.secondary).__name__
            )
            return result


class LazyProvider:
    """Delay provider construction until a question actually requires an LLM."""

    def __init__(self, factory: Callable[[], Any]) -> None:
        self.factory = factory
        self._provider: Any | None = None
        self.last_provider = "not_called"

    def complete(self, messages: Sequence[dict[str, str]], **kwargs: Any) -> str:
        if self._provider is None:
            self._provider = self.factory()
        result = self._provider.complete(messages, **kwargs)
        self.last_provider = getattr(
            self._provider,
            "last_provider",
            getattr(self._provider, "name", type(self._provider).__name__),
        )
        return result


def build_llm(source: Mapping[str, Any] | None = None) -> Any:
    data = dict(source or os.environ)
    primary_settings = LLMSettings.from_mapping(data)
    primary = OpenAICompatibleProvider(primary_settings)
    return primary

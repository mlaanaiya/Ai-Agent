"""LLM client factory — picks Gemini or Ollama based on config."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import OrchestratorSettings
    from .gemini import GeminiClient
    from .ollama import OllamaClient
    from .openai_compatible import OpenAICompatibleClient

    LLMClient = GeminiClient | OllamaClient | OpenAICompatibleClient


def build_llm(settings: OrchestratorSettings) -> LLMClient:
    """Return the appropriate LLM client for the configured backend."""
    if settings.llm_backend == "gemini":
        from .gemini import GeminiClient

        return GeminiClient(
            api_key=settings.gemini_api_key,
            default_model=settings.gemini_model,
            timeout=settings.gemini_timeout,
        )

    if settings.llm_backend == "openai":
        from .openai_compatible import OpenAICompatibleClient

        return OpenAICompatibleClient(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            default_model=settings.openai_model,
            timeout=settings.openai_timeout,
        )

    from .ollama import OllamaClient

    return OllamaClient(
        base_url=settings.ollama_base_url,
        default_model=settings.ollama_default_model,
        timeout=settings.ollama_timeout,
    )

"""LLM client factory — picks Gemini or Ollama based on config."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import OrchestratorSettings
    from .gemini import GeminiClient
    from .ollama import OllamaClient

    LLMClient = GeminiClient | OllamaClient


def build_llm(settings: OrchestratorSettings) -> LLMClient:
    """Return the appropriate LLM client for the configured backend."""
    if settings.llm_backend == "gemini":
        from .gemini import GeminiClient

        return GeminiClient(
            api_key=settings.gemini_api_key,
            default_model=settings.gemini_model,
            timeout=settings.gemini_timeout,
        )

    from .ollama import OllamaClient

    return OllamaClient(
        base_url=settings.ollama_base_url,
        default_model=settings.ollama_default_model,
        timeout=settings.ollama_timeout,
    )

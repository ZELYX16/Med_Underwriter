from __future__ import annotations

from typing import Any

from app.config import settings


class LLMProvider:
    def create(
        self,
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> Any:
        raise NotImplementedError


class OllamaProvider(LLMProvider):
    def create(
        self,
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> Any:
        from langchain_ollama import ChatOllama

        ollama_kwargs: dict[str, Any] = {
            "model": model,
            "base_url": settings.ollama_base_url,
            "temperature": (
                settings.temperature
                if temperature is None
                else temperature
            ),
            "num_predict": max_tokens or settings.max_tokens,
            "keep_alive": settings.ollama_keep_alive,
            "num_ctx": settings.ollama_num_ctx,
            "client_kwargs": {"timeout": settings.llm_timeout_sec},
            "max_retries": settings.llm_max_retries,
        }
        if json_mode:
            ollama_kwargs["format"] = "json"
        return ChatOllama(**ollama_kwargs)


class GroqProvider(LLMProvider):
    def create(
        self,
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> Any:
        from langchain_groq import ChatGroq

        if not settings.groq_api_key:
            raise ValueError(
                "GROQ_API_KEY is required when "
                "LLM_PROVIDER=groq."
            )

        groq_kwargs: dict[str, Any] = {
            "model": model,
            "api_key": settings.groq_api_key,
            "temperature": (
                settings.temperature
                if temperature is None
                else temperature
            ),
            "max_tokens": max_tokens or settings.max_tokens,
            "max_retries": settings.llm_max_retries,
        }
        if json_mode:
            groq_kwargs["response_format"] = {"type": "json_object"}
        return ChatGroq(**groq_kwargs)


class GeminiProvider(LLMProvider):
    def create(
        self,
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> Any:
        from langchain_google_genai import (
            ChatGoogleGenerativeAI,
        )

        if not settings.gemini_api_key:
            raise ValueError(
                "GEMINI_API_KEY is required when "
                "LLM_PROVIDER=gemini."
            )

        gemini_kwargs: dict[str, Any] = {
            "model": model,
            "google_api_key": settings.gemini_api_key,
            "temperature": (
                settings.temperature
                if temperature is None
                else temperature
            ),
            "max_output_tokens": max_tokens or settings.max_tokens,
            "max_retries": settings.llm_max_retries,
        }
        if json_mode:
            gemini_kwargs["response_mime_type"] = "application/json"
        return ChatGoogleGenerativeAI(**gemini_kwargs)


def get_provider() -> LLMProvider:
    providers = {
        "ollama": OllamaProvider,
        "groq": GroqProvider,
        "gemini": GeminiProvider,
    }

    provider_class = providers.get(
        settings.llm_provider
    )

    if provider_class is None:
        raise ValueError(
            f"Unsupported LLM provider: "
            f"{settings.llm_provider}"
        )

    return provider_class()
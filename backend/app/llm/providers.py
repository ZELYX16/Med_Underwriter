from __future__ import annotations

from typing import Any

from app.config import settings


class LLMProvider:
    def create(
        self,
        model: str,
        temperature: float | None = None,
    ) -> Any:
        raise NotImplementedError


class OllamaProvider(LLMProvider):
    def create(
        self,
        model: str,
        temperature: float | None = None,
    ) -> Any:
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=model,
            base_url=settings.ollama_base_url,
            temperature=(
                settings.temperature
                if temperature is None
                else temperature
            ),
            num_predict=settings.max_tokens,
        )


class GroqProvider(LLMProvider):
    def create(
        self,
        model: str,
        temperature: float | None = None,
    ) -> Any:
        from langchain_groq import ChatGroq

        if not settings.groq_api_key:
            raise ValueError(
                "GROQ_API_KEY is required when "
                "LLM_PROVIDER=groq."
            )

        return ChatGroq(
            model=model,
            api_key=settings.groq_api_key,
            temperature=(
                settings.temperature
                if temperature is None
                else temperature
            ),
            max_tokens=settings.max_tokens,
        )


class GeminiProvider(LLMProvider):
    def create(
        self,
        model: str,
        temperature: float | None = None,
    ) -> Any:
        from langchain_google_genai import (
            ChatGoogleGenerativeAI,
        )

        if not settings.gemini_api_key:
            raise ValueError(
                "GEMINI_API_KEY is required when "
                "LLM_PROVIDER=gemini."
            )

        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=settings.gemini_api_key,
            temperature=(
                settings.temperature
                if temperature is None
                else temperature
            ),
            max_output_tokens=settings.max_tokens,
        )


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
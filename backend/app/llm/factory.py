from typing import Literal

from langchain_core.language_models import BaseChatModel

from app.config import settings
from app.llm.providers import (
    create_gemini_model,
    create_groq_model,
    create_ollama_model,
)


LLMRole = Literal["planner", "reasoning", "reflection"]


def get_llm(
    role: LLMRole = "reasoning",
    temperature: float | None = None,
) -> BaseChatModel:
    provider = settings.llm_provider
    model = settings.get_model(role)

    if provider == "ollama":
        return create_ollama_model(
            model=model,
            temperature=temperature,
        )

    if provider == "groq":
        return create_groq_model(
            model=model,
            temperature=temperature,
        )

    if provider == "gemini":
        return create_gemini_model(
            model=model,
            temperature=temperature,
        )

    raise ValueError(
        f"Unsupported LLM provider: {provider}"
    )
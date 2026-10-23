from __future__ import annotations

from typing import Any, Literal

from app.config import settings
from app.llm.providers import get_provider


LLMRole = Literal[
    "planner",
    "reasoning",
    "reflection",
]


def get_llm(
    role: LLMRole = "reasoning",
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> Any:
    model = settings.get_model(role)

    provider = get_provider()

    return provider.create(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
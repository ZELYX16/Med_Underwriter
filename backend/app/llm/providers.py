from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama

from app.config import settings


def create_ollama_model(
    model: str,
    temperature: float | None = None,
) -> BaseChatModel:
    return ChatOllama(
        model=model,
        base_url=settings.ollama_base_url,
        temperature=(
            settings.temperature
            if temperature is None
            else temperature
        ),
    )


def create_groq_model(
    model: str,
    temperature: float | None = None,
) -> BaseChatModel:
    if not settings.groq_api_key:
        raise ValueError("GROQ_API_KEY is not configured.")

    return ChatGroq(
        model=model,
        api_key=settings.groq_api_key,
        temperature=(
            settings.temperature
            if temperature is None
            else temperature
        ),
    )


def create_gemini_model(
    model: str,
    temperature: float | None = None,
) -> BaseChatModel:
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY is not configured.")

    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=settings.gemini_api_key,
        temperature=(
            settings.temperature
            if temperature is None
            else temperature
        ),
    )
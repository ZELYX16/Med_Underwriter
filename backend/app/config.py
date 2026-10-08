from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


LLMProvider = Literal["ollama", "groq", "gemini"]


class Settings(BaseSettings):
    # Application
    app_name: str = "MedUnderwrite AI"
    app_version: str = "1.0.0"
    environment: str = "development"
    debug: bool = True

    # LLM
    llm_provider: LLMProvider = "ollama"

    ollama_base_url: str = "http://localhost:11434"
    planner_model: str = "qwen2.5:3b"
    reasoning_model: str = "gemma3:4b"
    reflection_model: str = "gemma3:4b"

    groq_api_key: str = ""
    groq_planner_model: str = ""
    groq_reasoning_model: str = ""
    groq_reflection_model: str = ""

    gemini_api_key: str = ""
    gemini_planner_model: str = ""
    gemini_reasoning_model: str = ""
    gemini_reflection_model: str = ""

    temperature: float = 0.1
    max_tokens: int = 4096

    # Storage
    sqlite_path: str = "data/medunderwrite.db"

    data_root: str = "data"
    raw_data_path: str = "data/raw"
    synthetic_data_path: str = "data/synthetic"
    processed_data_path: str = "data/processed"
    chroma_path: str = "data/processed/chroma"

    # RAG
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    top_k_results: int = 5

    # LangSmith
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "medunderwrite-ai"

    # API / Security
    cors_origins: str = "http://localhost:4200,http://localhost:8501"
    secret_key: str = "development-secret-key"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def base_path(self) -> Path:
        return Path(__file__).resolve().parents[2]

    @property
    def sqlite_file(self) -> Path:
        path = self.base_path / self.sqlite_path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def data_directory(self) -> Path:
        path = self.base_path / self.data_root
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def raw_data_directory(self) -> Path:
        path = self.base_path / self.raw_data_path
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def synthetic_data_directory(self) -> Path:
        path = self.base_path / self.synthetic_data_path
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def processed_data_directory(self) -> Path:
        path = self.base_path / self.processed_data_path
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def chroma_directory(self) -> Path:
        path = self.base_path / self.chroma_path
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def allowed_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]

    def get_model(
        self,
        role: Literal["planner", "reasoning", "reflection"],
    ) -> str:
        if self.llm_provider == "ollama":
            models = {
                "planner": self.planner_model,
                "reasoning": self.reasoning_model,
                "reflection": self.reflection_model,
            }

        elif self.llm_provider == "groq":
            models = {
                "planner": self.groq_planner_model,
                "reasoning": self.groq_reasoning_model,
                "reflection": self.groq_reflection_model,
            }

        else:
            models = {
                "planner": self.gemini_planner_model,
                "reasoning": self.gemini_reasoning_model,
                "reflection": self.gemini_reflection_model,
            }

        model = models[role]

        if not model:
            raise ValueError(
                f"No model configured for role '{role}' "
                f"with provider '{self.llm_provider}'."
            )

        return model


settings = Settings()
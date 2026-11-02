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
    llm_timeout_sec: float = 90.0
    llm_max_retries: int = 1
    ollama_keep_alive: str = "30m"
    ollama_num_ctx: int = 4096  # explicit, smaller context = less prefill/memory

    # Token / latency controls
    reasoning_max_tokens: int = 250  # short assessment; structure comes from code
    reasoning_cache_size: int = 256
    prompt_version: str = "v3"
    batch_max_group_size: int = 8
    batch_concurrency: int = 2  # parallel workflows; keep low for Ollama
    pattern_cache_enabled: bool = True
    pattern_cache_ttl_sec: float = 7 * 24 * 3600
    pattern_cache_max_entries: int = 2000
    skip_llm_for_simple_cases: bool = True
    skip_llm_risk_ceiling: float = 40.0
    reflection_llm_enabled: bool = True  # LLM critique for complex/high-risk cases
    reflection_max_tokens: int = 450  # room for complete JSON; short prompt keeps it small
    warm_llm_on_startup: bool = True  # Ollama only: preload models

    # Underwriting safety / human-review gates
    medical_risk_human_review_threshold: float = 80.0
    overall_risk_human_review_threshold: float = 70.0
    confidence_human_review_threshold: float = 0.70
    max_reflection_rounds: int = 3
    fraud_review_threshold: float = 60.0
    router_complex_threshold: int = 4  # weighted routing score >= this is complex
    max_upload_mb: int = 20
    fraud_high_sum_insured: float = 5_000_000.0

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
    # Relevance / budget limits (cosine distance: lower is closer)
    retrieval_max_distance: float = 0.65
    retrieval_relative_margin: float = 0.15  # keep hits within best+margin
    retrieval_per_source_k: int = 3
    retrieval_chunk_chars: int = 600
    rag_max_calls_per_case: int = 12
    rag_max_chunks_per_case: int = 25
    rag_max_seconds_per_case: float = 20.0
    crag_max_correction_rounds: int = 1
    agentic_max_subsearches: int = 3

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
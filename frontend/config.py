from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    app_name: str = "MedUnderwrite AI"
    app_subtitle: str = "Medical Underwriting Workstation"

    backend_url: str = os.getenv(
        "MEDUNDERWRITE_BACKEND_URL",
        "http://127.0.0.1:8000",
    )

    request_timeout: int = int(
        os.getenv("MEDUNDERWRITE_REQUEST_TIMEOUT", "60")
    )


settings = Settings()
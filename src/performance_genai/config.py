from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Loads keys from process env, and also from a local .env file for convenience in v0.
    model_config = SettingsConfigDict(env_prefix="", extra="ignore", env_file=".env", env_file_encoding="utf-8")

    data_dir: str = "data"

    # Keys
    gemini_api_key: str | None = None
    openai_api_key: str | None = None

    # Models (set via env vars as needed; defaults are placeholders)
    gemini_vision_model: str = "gemini-2.0-flash"
    gemini_image_model: str = "imagen-3.0-generate-002"
    openai_text_model: str = "gpt-4.1-mini"

    # Rendering
    master_sizes: dict[str, tuple[int, int]] = {
        "1:1": (1080, 1080),
        "4:5": (1080, 1350),
        "9:16": (1080, 1920),
    }


settings = Settings()

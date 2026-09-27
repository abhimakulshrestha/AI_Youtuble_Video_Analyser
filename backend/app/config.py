from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent.parent

class Settings(BaseSettings):
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "google/gemma-4-31b-it:free"
    OPENROUTER_FALLBACK_MODEL: str = "qwen/qwen3.8-27b:free"
    OPENROUTER_VIDEO_MODEL: str = "qwen/qwen3.8-27b:free"
    OPENROUTER_VIDEO_FALLBACK_MODEL: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_SITE_URL: str = ""
    OPENROUTER_APP_NAME: str = "YouTube AI Analyzer"
    OPENROUTER_REASONING_ENABLED: bool = True
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "qwen/qwen3.8-27b"
    
    CORS_ALLOWED_ORIGINS: str = ""
    CORS_ALLOWED_ORIGIN_REGEX: str = r"chrome-extension://.*"
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(env_file=str(ROOT_DIR / ".env"), env_file_encoding="utf-8", extra="ignore")

settings = Settings()

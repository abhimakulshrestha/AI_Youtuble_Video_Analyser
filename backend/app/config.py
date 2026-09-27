from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent.parent

class Settings(BaseSettings):
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "openai/gpt-oss-20b"
    GROQ_FALLBACK_MODEL: str = "qwen/qwen3.8-27b"
    GROQ_VISION_MODEL: str = "qwen/qwen3.8-27b"
    GROQ_SEARCH_MODEL: str = "openai/gpt-oss-20b"
    
    CORS_ALLOWED_ORIGINS: str = ""
    CORS_ALLOWED_ORIGIN_REGEX: str = r"chrome-extension://.*"
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(env_file=str(ROOT_DIR / ".env"), env_file_encoding="utf-8", extra="ignore")

settings = Settings()

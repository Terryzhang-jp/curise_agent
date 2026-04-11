import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # Database - same Supabase instance as v1
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        os.getenv("SUPABASE_DB_URL", "postgresql://postgres:postgres@localhost/cruise_system_dev"),
    )

    # JWT - must match v1 settings for token compatibility
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30  # Short-lived access token
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7  # Long-lived refresh token

    # CORS
    ALLOWED_ORIGINS: list[str] = [
        o.strip()
        for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3001").split(",")
        if o.strip()
    ]

    # Google AI (Gemini)
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")

    # Kimi K2.5 (Moonshot) — preferred for agent tool calling (93% accuracy)
    MOONSHOT_API_KEY: str = os.getenv("MOONSHOT_API_KEY", "")

    # DeepSeek — preferred for PDF extraction (fast, cheap, paid tier)
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")

    # Google Document AI (optional — for OCR extraction)
    DOCUMENT_AI_PROJECT_ID: str = os.getenv("DOCUMENT_AI_PROJECT_ID", "")
    DOCUMENT_AI_PROCESSOR_ID: str = os.getenv("DOCUMENT_AI_PROCESSOR_ID", "")
    DOCUMENT_AI_LOCATION: str = os.getenv("DOCUMENT_AI_LOCATION", "us")

    # LINE Bot
    LINE_CHANNEL_SECRET: str = os.getenv("LINE_CHANNEL_SECRET", "")
    LINE_CHANNEL_ACCESS_TOKEN: str = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")

    # Server
    ENV: str = os.getenv("ENV", "development")
    DEBUG: bool = ENV == "development"

    # File uploads
    UPLOAD_DIR: str = os.path.join(os.path.dirname(__file__), "uploads")
    MAX_UPLOAD_SIZE: int = 30 * 1024 * 1024  # 30 MB

    # Supabase Storage
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")
    STORAGE_BUCKET: str = os.getenv("STORAGE_BUCKET", "v2-files")

    # Agent workspace root (session-isolated working directories)
    AGENT_WORKSPACE_ROOT: str = os.getenv("AGENT_WORKSPACE_ROOT", "/tmp/workspace")


settings = Settings()

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/docprocessor"
    REDIS_URL: str = "redis://localhost:6379/0"

    LLM_MODEL: str = "openai/gpt-4o-mini"
    LLM_API_KEY: str = ""
    LLM_API_BASE: str | None = None

    MAX_TOKENS_PER_JOB: int = 4000
    MAX_DOCUMENT_SIZE: int = 10_485_760  # 10 MB
    SSL_VERIFY: bool = True

    WORKER_CONCURRENCY: int = 2
    LOG_LEVEL: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

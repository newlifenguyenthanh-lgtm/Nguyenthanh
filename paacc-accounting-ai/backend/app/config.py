from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PAACC_", env_file=".env", extra="ignore")
    default_ai_provider: str = "echo"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    local_model_url: str = "http://localhost:11434/v1"
    database_url: str = ""


def get_settings() -> Settings:
    return Settings()

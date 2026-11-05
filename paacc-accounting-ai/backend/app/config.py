from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PAACC_", env_file=".env", extra="ignore")
    default_ai_provider: str = "echo"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    local_model_url: str = "http://localhost:11434/v1"
    database_url: str = "sqlite:///./paacc_dev.db"  # use PostgreSQL URL in real deployments
    jwt_secret: str = ""
    jwt_hours: int = 8
    storage_dir: str = "./storage"  # local file store; swap for S3/MinIO in cloud
    max_upload_mb: int = 100
    boq_four_eyes: bool = True  # submitter may not approve their own BOQ
    pdf_max_pages: int = 200
    geometry_on_process: bool = True  # extract vector geometry during drawing processing (Phase 5A)
    ocr_enabled: bool = True
    ocr_dpi: int = 300
    ocr_max_side_px: int = 7000
    ocr_min_text_chars: int = 20  # below this a page with large images is treated as scanned


def get_settings() -> Settings:
    return Settings()

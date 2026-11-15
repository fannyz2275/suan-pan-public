from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", hide_input_in_errors=True)
    provider_keys_encryption_keys: str = Field(default="", repr=False, exclude=True)
    provider_keys_active_version: str = "v1"
    openrouter_api_key: str = Field(default="", repr=False, exclude=True)
    evidence_advisor_enabled: bool = False

    supabase_url: str = "https://your-project.supabase.co"
    supabase_service_key: str = Field(default="", repr=False, exclude=True)
    google_project_id: str = ""
    google_api_key: str = Field(default="", repr=False, exclude=True)
    plaid_client_id: str = "placeholder"
    plaid_secret: str = "placeholder"
    plaid_env: str = "sandbox"
    frontend_url: str = "http://localhost:5173"


settings = Settings()

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central config. Reads from environment variables / a .env file.

    Only ANTHROPIC_API_KEY is required for phase 1 — Quo and Monday are
    stubbed, so their settings exist here as placeholders for when we wire
    up the real integrations.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"

    crm_store_path: str = "data/crm_store.json"
    conversations_dir: str = "data/conversations"
    chroma_persist_dir: str = "data/chroma"

    # Phase 2 — nightly batch jobs
    triage_store_dir: str = "data/triage"
    batch_state_path: str = "data/batch_state.json"
    stub_calls_path: str = "data/stub_calls.json"
    follow_up_after_hours: int = 48

    # Stubbed for phase 1 — not read by anything yet.
    quo_api_key: str = ""
    quo_webhook_secret: str = ""
    monday_api_token: str = ""
    monday_board_id: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()

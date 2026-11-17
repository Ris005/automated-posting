"""Application settings loaded from environment variables / `.env`."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- General -------------------------------------------------------------
    app_name: str = "Automated Multi-Platform Posting"
    timezone: str = "Asia/Kolkata"
    http_timeout_seconds: float = 15.0
    platform_timeout_seconds: float = 30.0
    verify_public_access: bool = True
    log_level: str = "INFO"
    log_file: str | None = "logs/posting.log"

    # --- Telegram (Bot API) --------------------------------------------------
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    # --- Discord (Webhook) ---------------------------------------------------
    discord_webhook_url: str | None = None

    # --- Mastodon ------------------------------------------------------------
    mastodon_base_url: str = "https://mastodon.social"
    mastodon_access_token: str | None = None

    # --- Bluesky (AT Protocol) -----------------------------------------------
    bluesky_service_url: str = "https://bsky.social"
    bluesky_handle: str | None = None
    bluesky_app_password: str | None = None

    # --- DEV Community (Forem API) -------------------------------------------
    devto_api_key: str | None = None
    devto_tags: str = "showdev,webdev"

    # --- GitHub Gist ---------------------------------------------------------
    github_token: str | None = None

    # --- Pastebin ------------------------------------------------------------
    pastebin_api_key: str | None = None
    pastebin_user_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()

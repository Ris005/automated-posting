"""Registry of platform integrations. The service posts to every platform listed here."""

from app.platforms.base import BasePlatform, PlatformError, PublishedPost
from app.platforms.bluesky import BlueskyPlatform
from app.platforms.devto import DevToPlatform
from app.platforms.discord import DiscordPlatform
from app.platforms.github_gist import GitHubGistPlatform
from app.platforms.mastodon import MastodonPlatform
from app.platforms.pastebin import PastebinPlatform
from app.platforms.telegram import TelegramPlatform

PLATFORM_CLASSES: tuple[type[BasePlatform], ...] = (
    TelegramPlatform,
    DiscordPlatform,
    MastodonPlatform,
    BlueskyPlatform,
    DevToPlatform,
    GitHubGistPlatform,
    PastebinPlatform,
)

__all__ = ["PLATFORM_CLASSES", "BasePlatform", "PlatformError", "PublishedPost"]

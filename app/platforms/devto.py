"""DEV Community (Forem API v1) — https://developers.forem.com/api/v1#tag/articles/operation/createArticle"""

import re

from app.platforms.base import BasePlatform, PublishedPost, build_title

API_URL = "https://dev.to/api/articles"
MAX_TAGS = 4  # Forem limit


def parse_tags(raw: str) -> list[str]:
    tags = (re.sub(r"[^a-z0-9]", "", tag.lower()) for tag in raw.split(","))
    return [tag for tag in tags if tag][:MAX_TAGS]


class DevToPlatform(BasePlatform):
    name = "DEV Community"
    required_settings = ("devto_api_key",)

    async def publish(self, message: str, link: str) -> PublishedPost:
        response = await self._request(
            "POST",
            API_URL,
            headers={
                "api-key": self.settings.devto_api_key or "",
                "Accept": "application/vnd.forem.api-v1+json",
            },
            json={
                "article": {
                    "title": build_title(message, link),
                    "body_markdown": message,
                    "published": True,
                    "tags": parse_tags(self.settings.devto_tags),
                }
            },
        )
        self._ensure_ok(response)
        data = self._json(response)
        return PublishedPost(url=data["url"], public=bool(data.get("published", True)))

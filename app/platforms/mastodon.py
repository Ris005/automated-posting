"""Mastodon — https://docs.joinmastodon.org/methods/statuses/#create"""

import uuid

from app.platforms.base import BasePlatform, PublishedPost


class MastodonPlatform(BasePlatform):
    name = "Mastodon"
    required_settings = ("mastodon_access_token",)

    async def publish(self, message: str, link: str) -> PublishedPost:
        response = await self._request(
            "POST",
            f"{self.settings.mastodon_base_url.rstrip('/')}/api/v1/statuses",
            headers={
                "Authorization": f"Bearer {self.settings.mastodon_access_token}",
                # Mastodon de-duplicates statuses sent with the same key.
                "Idempotency-Key": str(uuid.uuid4()),
            },
            json={"status": message, "visibility": "public"},
        )
        self._ensure_ok(response)
        data = self._json(response)
        return PublishedPost(
            url=data.get("url") or data["uri"],
            public=data.get("visibility") == "public",
        )

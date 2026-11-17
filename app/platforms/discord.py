"""Discord webhooks — https://discord.com/developers/docs/resources/webhook#execute-webhook"""

from app.platforms.base import BasePlatform, PlatformError, PublishedPost


class DiscordPlatform(BasePlatform):
    name = "Discord"
    required_settings = ("discord_webhook_url",)

    async def publish(self, message: str, link: str) -> PublishedPost:
        webhook_url = self.settings.discord_webhook_url
        assert webhook_url

        # wait=true makes Discord return the created message instead of 204 No Content.
        response = await self._request(
            "POST",
            webhook_url,
            params={"wait": "true"},
            json={"content": message, "allowed_mentions": {"parse": []}},
        )
        self._ensure_ok(response)
        data = self._json(response)

        guild_id = data.get("guild_id") or await self._guild_id(webhook_url)
        url = f"https://discord.com/channels/{guild_id}/{data['channel_id']}/{data['id']}"
        # Discord messages are only visible to logged-in members of the server.
        return PublishedPost(url=url, public=False)

    async def _guild_id(self, webhook_url: str) -> str:
        response = await self._request("GET", webhook_url)
        self._ensure_ok(response)
        guild_id = self._json(response).get("guild_id")
        if not guild_id:
            raise PlatformError("Posted, but could not resolve the Discord server id for the URL.")
        return str(guild_id)

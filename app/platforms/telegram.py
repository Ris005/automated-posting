"""Telegram Bot API — https://core.telegram.org/bots/api#sendmessage"""

from app.platforms.base import BasePlatform, PlatformError, PublishedPost

API_BASE = "https://api.telegram.org"


class TelegramPlatform(BasePlatform):
    name = "Telegram"
    required_settings = ("telegram_bot_token", "telegram_chat_id")

    async def publish(self, message: str, link: str) -> PublishedPost:
        # The token is part of the URL, so it must never appear in errors or logs.
        response = await self._request(
            "POST",
            f"{API_BASE}/bot{self.settings.telegram_bot_token}/sendMessage",
            json={
                "chat_id": self.settings.telegram_chat_id,
                "text": message,
                "link_preview_options": {"url": link},
            },
        )
        data = self._json(response)
        if not data.get("ok"):
            code = data.get("error_code", response.status_code)
            raise PlatformError(f"Telegram API error ({code}): {data.get('description', 'unknown')}")

        result = data["result"]
        message_id = result["message_id"]
        chat = result["chat"]

        username = chat.get("username")
        if username:  # public channel / group -> anyone can open t.me/<username>/<id>
            return PublishedPost(url=f"https://t.me/{username}/{message_id}", public=True)

        internal_id = str(chat["id"]).removeprefix("-100")
        return PublishedPost(url=f"https://t.me/c/{internal_id}/{message_id}", public=False)

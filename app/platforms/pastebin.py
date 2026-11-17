"""Pastebin — https://pastebin.com/doc_api#2"""

from app.platforms.base import BasePlatform, PlatformError, PublishedPost, build_title

API_URL = "https://pastebin.com/api/api_post.php"


class PastebinPlatform(BasePlatform):
    name = "Pastebin"
    required_settings = ("pastebin_api_key",)

    async def publish(self, message: str, link: str) -> PublishedPost:
        form = {
            "api_dev_key": self.settings.pastebin_api_key or "",
            "api_option": "paste",
            "api_paste_code": message,
            "api_paste_name": build_title(message, link),
            "api_paste_private": "0",  # 0 = public
            "api_paste_expire_date": "N",  # never
            "api_paste_format": "text",
        }
        if self.settings.pastebin_user_key:
            form["api_user_key"] = self.settings.pastebin_user_key

        response = await self._request("POST", API_URL, data=form)
        # Pastebin answers with plain text: the paste URL, or "Bad API request, <reason>".
        body = response.text.strip()
        if not response.is_success or not body.startswith("http"):
            raise PlatformError(f"Pastebin API error (HTTP {response.status_code}): {body[:200]}")
        return PublishedPost(url=body, public=True)

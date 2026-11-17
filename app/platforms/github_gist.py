"""GitHub Gists — https://docs.github.com/en/rest/gists/gists#create-a-gist"""

from app.platforms.base import BasePlatform, PublishedPost, build_title

API_URL = "https://api.github.com/gists"


class GitHubGistPlatform(BasePlatform):
    name = "GitHub Gist"
    required_settings = ("github_token",)

    async def publish(self, message: str, link: str) -> PublishedPost:
        response = await self._request(
            "POST",
            API_URL,
            headers={
                "Authorization": f"Bearer {self.settings.github_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={
                "description": build_title(message, link),
                "public": True,
                "files": {"post.md": {"content": message + "\n"}},
            },
        )
        self._ensure_ok(response)
        data = self._json(response)
        return PublishedPost(url=data["html_url"], public=bool(data.get("public", True)))

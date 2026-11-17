"""Bluesky (AT Protocol).

- Session:  https://docs.bsky.app/docs/api/com-atproto-server-create-session
- Post:     https://docs.bsky.app/docs/api/com-atproto-repo-create-record
- Links:    https://docs.bsky.app/docs/advanced-guides/post-richtext (facets use UTF-8 byte offsets)
"""

from datetime import datetime, timezone
from typing import Any

from app.platforms.base import BasePlatform, PublishedPost

POST_COLLECTION = "app.bsky.feed.post"


def build_link_facet(text: str, link: str) -> dict[str, Any] | None:
    """Make the link clickable. Bluesky indexes facets by UTF-8 bytes, not characters."""
    char_index = text.find(link)
    if char_index < 0:
        return None
    byte_start = len(text[:char_index].encode("utf-8"))
    byte_end = byte_start + len(link.encode("utf-8"))
    return {
        "index": {"byteStart": byte_start, "byteEnd": byte_end},
        "features": [{"$type": "app.bsky.richtext.facet#link", "uri": link}],
    }


class BlueskyPlatform(BasePlatform):
    name = "Bluesky"
    required_settings = ("bluesky_handle", "bluesky_app_password")

    async def publish(self, message: str, link: str) -> PublishedPost:
        base = self.settings.bluesky_service_url.rstrip("/")

        session_response = await self._request(
            "POST",
            f"{base}/xrpc/com.atproto.server.createSession",
            json={
                "identifier": self.settings.bluesky_handle,
                "password": self.settings.bluesky_app_password,
            },
        )
        self._ensure_ok(session_response)
        session = self._json(session_response)

        record: dict[str, Any] = {
            "$type": POST_COLLECTION,
            "text": message,
            "createdAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
                "+00:00", "Z"
            ),
        }
        facet = build_link_facet(message, link)
        if facet:
            record["facets"] = [facet]

        response = await self._request(
            "POST",
            f"{base}/xrpc/com.atproto.repo.createRecord",
            headers={"Authorization": f"Bearer {session['accessJwt']}"},
            json={"repo": session["did"], "collection": POST_COLLECTION, "record": record},
        )
        self._ensure_ok(response)
        uri = self._json(response)["uri"]  # at://<did>/app.bsky.feed.post/<rkey>
        record_key = uri.rsplit("/", 1)[-1]
        return PublishedPost(
            url=f"https://bsky.app/profile/{session['handle']}/post/{record_key}",
            public=True,
        )

"""Each integration is exercised against a mocked HTTP transport that mimics the real API."""

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest

from app.config import Settings
from app.platforms.base import BasePlatform, PlatformError, PublishedPost, build_title
from app.platforms.bluesky import BlueskyPlatform, build_link_facet
from app.platforms.devto import DevToPlatform, parse_tags
from app.platforms.discord import DiscordPlatform
from app.platforms.github_gist import GitHubGistPlatform
from app.platforms.mastodon import MastodonPlatform
from app.platforms.pastebin import PastebinPlatform
from app.platforms.telegram import TelegramPlatform

MESSAGE = "Grow your visibility 🚀 https://example.com"
LINK = "https://example.com"

Handler = Callable[[httpx.Request], httpx.Response]


def run(platform_class: type[BasePlatform], handler: Handler, **settings: object) -> PublishedPost:
    async def _go() -> PublishedPost:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            platform = platform_class(Settings(_env_file=None, **settings), client)  # type: ignore[arg-type]
            return await platform.publish(MESSAGE, LINK)

    return asyncio.run(_go())


# --- Telegram ------------------------------------------------------------------


def test_telegram_public_channel_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/botTOKEN/sendMessage"
        assert json.loads(request.content)["chat_id"] == "@mychannel"
        return httpx.Response(
            200,
            json={"ok": True, "result": {"message_id": 42, "chat": {"id": -1001, "username": "mychannel"}}},
        )

    post = run(TelegramPlatform, handler, telegram_bot_token="TOKEN", telegram_chat_id="@mychannel")
    assert post == PublishedPost("https://t.me/mychannel/42", public=True)


def test_telegram_private_chat_is_not_public() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"ok": True, "result": {"message_id": 7, "chat": {"id": -1009876}}}
        )

    post = run(TelegramPlatform, handler, telegram_bot_token="T", telegram_chat_id="-1009876")
    assert post == PublishedPost("https://t.me/c/9876/7", public=False)


def test_telegram_error_does_not_leak_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"ok": False, "error_code": 401, "description": "Unauthorized"}
        )

    with pytest.raises(PlatformError) as exc:
        run(TelegramPlatform, handler, telegram_bot_token="SECRET", telegram_chat_id="@c")
    assert str(exc.value) == "Telegram API error (401): Unauthorized"
    assert "SECRET" not in str(exc.value)


# --- Discord -------------------------------------------------------------------


def test_discord_builds_message_link() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            assert request.url.params["wait"] == "true"
            return httpx.Response(200, json={"id": "111", "channel_id": "222"})
        return httpx.Response(200, json={"guild_id": "333"})

    post = run(DiscordPlatform, handler, discord_webhook_url="https://discord.com/api/webhooks/1/x")
    assert post == PublishedPost("https://discord.com/channels/333/222/111", public=False)


# --- Mastodon ------------------------------------------------------------------


def test_mastodon_posts_public_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://fosstodon.org/api/v1/statuses"
        assert request.headers["Authorization"] == "Bearer tok"
        assert request.headers["Idempotency-Key"]
        assert json.loads(request.content) == {"status": MESSAGE, "visibility": "public"}
        return httpx.Response(
            200, json={"url": "https://fosstodon.org/@me/1", "visibility": "public"}
        )

    post = run(
        MastodonPlatform, handler,
        mastodon_base_url="https://fosstodon.org/", mastodon_access_token="tok",
    )
    assert post == PublishedPost("https://fosstodon.org/@me/1", public=True)


def test_mastodon_auth_error_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "The access token is invalid"})

    with pytest.raises(PlatformError, match=r"Authentication failed \(HTTP 401\): The access token"):
        run(MastodonPlatform, handler, mastodon_access_token="bad")


# --- Bluesky -------------------------------------------------------------------


def test_bluesky_link_facet_uses_utf8_byte_offsets() -> None:
    facet = build_link_facet(MESSAGE, LINK)
    assert facet is not None
    start = MESSAGE.encode().index(LINK.encode())
    assert facet["index"] == {"byteStart": start, "byteEnd": start + len(LINK)}
    assert start != MESSAGE.index(LINK)  # the emoji makes bytes != characters


def test_bluesky_creates_session_then_post() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("createSession"):
            return httpx.Response(
                200, json={"accessJwt": "jwt", "did": "did:plc:abc", "handle": "me.bsky.social"}
            )
        assert request.headers["Authorization"] == "Bearer jwt"
        body = json.loads(request.content)
        assert body["repo"] == "did:plc:abc"
        assert body["record"]["text"] == MESSAGE
        assert body["record"]["createdAt"].endswith("Z")
        assert body["record"]["facets"][0]["features"][0]["uri"] == LINK
        return httpx.Response(200, json={"uri": "at://did:plc:abc/app.bsky.feed.post/3kxyz"})

    post = run(
        BlueskyPlatform, handler, bluesky_handle="me.bsky.social", bluesky_app_password="pw"
    )
    assert post == PublishedPost("https://bsky.app/profile/me.bsky.social/post/3kxyz", public=True)


# --- DEV Community -------------------------------------------------------------


def test_devto_publishes_article() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["api-key"] == "key"
        article = json.loads(request.content)["article"]
        assert article["title"] == "Grow your visibility 🚀"
        assert article["published"] is True
        assert article["tags"] == ["showdev", "webdev"]
        return httpx.Response(201, json={"url": "https://dev.to/me/grow-1", "published": True})

    post = run(DevToPlatform, handler, devto_api_key="key")
    assert post == PublishedPost("https://dev.to/me/grow-1", public=True)


def test_devto_tags_are_sanitised_and_capped() -> None:
    assert parse_tags("Web-Dev, python ,, a,b,c,d") == ["webdev", "python", "a", "b"]


# --- GitHub Gist ---------------------------------------------------------------


def test_github_gist_is_public() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["public"] is True
        assert body["files"]["post.md"]["content"] == MESSAGE + "\n"
        return httpx.Response(201, json={"html_url": "https://gist.github.com/me/abc", "public": True})

    post = run(GitHubGistPlatform, handler, github_token="ghp")
    assert post == PublishedPost("https://gist.github.com/me/abc", public=True)


# --- Pastebin ------------------------------------------------------------------


def test_pastebin_returns_plain_text_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert b"api_paste_private=0" in request.content
        return httpx.Response(200, text="https://pastebin.com/AbCd1234")

    post = run(PastebinPlatform, handler, pastebin_api_key="dev")
    assert post == PublishedPost("https://pastebin.com/AbCd1234", public=True)


def test_pastebin_bad_request_is_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="Bad API request, invalid api_dev_key")

    with pytest.raises(PlatformError, match="invalid api_dev_key"):
        run(PastebinPlatform, handler, pastebin_api_key="dev")


# --- shared helpers ------------------------------------------------------------


def test_connect_errors_are_retried_once_then_reported() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("refused")

    with pytest.raises(PlatformError, match="Could not connect to GitHub Gist"):
        run(GitHubGistPlatform, handler, github_token="ghp")
    assert calls == 2


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Hello world https://a.com", "Hello world"),
        ("https://a.com", "New post"),
        ("word " * 30 + "https://a.com", ("word " * 15).strip() + "…"),
    ],
)
def test_build_title(message: str, expected: str) -> None:
    assert build_title(message, "https://a.com") == expected

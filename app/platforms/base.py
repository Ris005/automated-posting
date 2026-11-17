"""Common contract and HTTP helpers shared by every platform integration."""

import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

import httpx

from app.config import Settings

_STATUS_LABELS = {
    400: "Bad request",
    401: "Authentication failed",
    403: "Permission denied",
    404: "Not found",
    413: "Payload too large",
    422: "Rejected by platform",
    429: "Rate limited",
}
_ERROR_KEYS = ("error_description", "description", "message", "error", "errors", "detail")


class PlatformError(Exception):
    """A platform rejected the post or returned something we cannot use."""


@dataclass(frozen=True)
class PublishedPost:
    url: str
    public: bool  # visibility as declared by the platform itself


def extract_error_message(response: httpx.Response, limit: int = 300) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text.strip()[:limit]

    if isinstance(body, dict):
        for key in _ERROR_KEYS:
            value = body.get(key)
            if value:
                text = value if isinstance(value, str) else json.dumps(value)
                return text[:limit]
    return json.dumps(body)[:limit]


def describe_http_error(response: httpx.Response) -> str:
    label = _STATUS_LABELS.get(response.status_code, "HTTP error")
    detail = extract_error_message(response)
    prefix = f"{label} (HTTP {response.status_code})"
    return f"{prefix}: {detail}" if detail else prefix


class BasePlatform(ABC):
    name: ClassVar[str]
    required_settings: ClassVar[tuple[str, ...]] = ()

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self.settings = settings
        self.client = client

    def missing_settings(self) -> list[str]:
        return [key.upper() for key in self.required_settings if not getattr(self.settings, key)]

    def is_configured(self) -> bool:
        return not self.missing_settings()

    @abstractmethod
    async def publish(self, message: str, link: str) -> PublishedPost:
        """Publish `message` and return where it lives. Raise PlatformError on rejection."""

    # --- helpers -------------------------------------------------------------

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Send a request, retrying once only when the connection was never established.

        Retrying after the request reached the server could publish the post twice,
        so read timeouts and HTTP errors are never retried here.
        """
        for attempt in range(2):
            try:
                return await self.client.request(method, url, **kwargs)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if attempt == 1:
                    raise PlatformError(f"Could not connect to {self.name}.") from exc
                await asyncio.sleep(0.5)
        raise AssertionError("unreachable")

    @staticmethod
    def _ensure_ok(response: httpx.Response) -> None:
        if not response.is_success:
            raise PlatformError(describe_http_error(response))

    def _json(self, response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise PlatformError(f"{self.name} returned a non-JSON response.") from exc
        if not isinstance(data, dict):
            raise PlatformError(f"{self.name} returned an unexpected response.")
        return data


def build_title(message: str, link: str, max_length: int = 80) -> str:
    """Short title for platforms that need one: the message text without the link."""
    text = " ".join(message.replace(link, " ").split()).strip(" -:|,")
    if not text:
        return "New post"
    if len(text) <= max_length:
        return text
    cut = text[: max_length - 1].rsplit(" ", 1)[0] or text[: max_length - 1]
    return cut.rstrip(" ,.;:") + "…"

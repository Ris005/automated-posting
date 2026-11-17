"""Fan a message out to every platform concurrently, isolating each platform's failure."""

import asyncio
import logging
from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from app.config import Settings
from app.platforms import PLATFORM_CLASSES, BasePlatform, PlatformError, PublishedPost
from app.schemas import PlatformResult, PlatformStatus, PostStatus

logger = logging.getLogger(__name__)

USER_AGENT = "automated-posting/1.0 (+FastAPI)"
# Status codes that prove an anonymous visitor cannot see the post.
NOT_PUBLIC_STATUSES = {401, 404, 410}


class PostingService:
    def __init__(
        self,
        settings: Settings,
        platform_classes: Sequence[type[BasePlatform]] = PLATFORM_CLASSES,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.platform_classes = platform_classes
        self._transport = transport  # injectable for tests
        self._tz = ZoneInfo(settings.timezone)

    def platform_statuses(self) -> list[PlatformStatus]:
        statuses = []
        for platform_class in self.platform_classes:
            platform = platform_class(self.settings, client=None)  # type: ignore[arg-type]
            missing = platform.missing_settings()
            statuses.append(
                PlatformStatus(
                    platform=platform.name, configured=not missing, missing_settings=missing
                )
            )
        return statuses

    async def publish(self, message: str, link: str) -> list[PlatformResult]:
        async with httpx.AsyncClient(
            timeout=self.settings.http_timeout_seconds,
            headers={"User-Agent": USER_AGENT},
            transport=self._transport,
        ) as client:
            platforms = [cls(self.settings, client) for cls in self.platform_classes]
            results = await asyncio.gather(
                *(self._publish_to(platform, message, link, client) for platform in platforms)
            )
        return list(results)

    async def _publish_to(
        self, platform: BasePlatform, message: str, link: str, client: httpx.AsyncClient
    ) -> PlatformResult:
        missing = platform.missing_settings()
        if missing:
            error = f"Not configured: set {', '.join(missing)} in .env"
            logger.info("[%s] skipped - %s", platform.name, error)
            return self._failed(platform.name, error)

        try:
            post = await asyncio.wait_for(
                platform.publish(message, link), timeout=self.settings.platform_timeout_seconds
            )
        except PlatformError as exc:
            error = str(exc)
        except (TimeoutError, asyncio.TimeoutError, httpx.TimeoutException):  # 3.10-safe
            error = f"Timed out after {self.settings.platform_timeout_seconds:g}s"
        except httpx.HTTPError as exc:
            error = f"Network error: {type(exc).__name__}"
        except (KeyError, TypeError, ValueError):
            logger.exception("[%s] unexpected response shape", platform.name)
            error = f"Unexpected response format from {platform.name}"
        except Exception:  # noqa: BLE001 - one platform must never break the others
            logger.exception("[%s] unexpected error", platform.name)
            error = "Unexpected internal error"
        else:
            return await self._succeeded(platform.name, post, client)

        logger.warning("[%s] failed - %s", platform.name, error)
        return self._failed(platform.name, error)

    async def _succeeded(
        self, name: str, post: PublishedPost, client: httpx.AsyncClient
    ) -> PlatformResult:
        posted_at = datetime.now(self._tz)
        public = post.public and await self._is_publicly_reachable(client, post.url)
        logger.info("[%s] posted %s (public=%s)", name, post.url, public)
        return PlatformResult(
            platform=name,
            status=PostStatus.SUCCESS,
            posted_url=post.url,
            public_access=public,
            date=posted_at.strftime("%Y-%m-%d"),
            time=posted_at.strftime("%H:%M:%S"),
            error=None,
        )

    async def _is_publicly_reachable(self, client: httpx.AsyncClient, url: str) -> bool:
        """Open the post anonymously. Only a definite 401/404/410 marks it as not public;
        bot-protection pages and network errors are inconclusive, so the platform's
        declared visibility stands."""
        if not self.settings.verify_public_access:
            return True
        try:
            response = await client.get(url, follow_redirects=True, timeout=10)
        except httpx.HTTPError:
            return True
        return response.status_code not in NOT_PUBLIC_STATUSES

    @staticmethod
    def _failed(name: str, error: str) -> PlatformResult:
        return PlatformResult(
            platform=name,
            status=PostStatus.FAILED,
            posted_url=None,
            public_access=False,
            date=None,
            time=None,
            error=error,
        )

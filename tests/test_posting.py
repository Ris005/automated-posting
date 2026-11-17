"""API, validation and fan-out tests. No real network calls are made."""

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app, get_posting_service
from app.platforms.base import BasePlatform, PlatformError, PublishedPost
from app.services.posting_service import PostingService

VALID_MESSAGE = (
    "Check out our latest business platform and grow your online visibility. https://example.com"
)


def make_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {"log_file": None, "platform_timeout_seconds": 0.5}
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)  # type: ignore[arg-type]


# --- fake platforms ----------------------------------------------------------


class OkPlatform(BasePlatform):
    name = "Ok"

    async def publish(self, message: str, link: str) -> PublishedPost:
        return PublishedPost(url="https://ok.example/post/1", public=True)


class PrivatePlatform(BasePlatform):
    name = "Private"

    async def publish(self, message: str, link: str) -> PublishedPost:
        return PublishedPost(url="https://private.example/post/1", public=False)


class AuthFailPlatform(BasePlatform):
    name = "AuthFail"

    async def publish(self, message: str, link: str) -> PublishedPost:
        raise PlatformError("Authentication failed (HTTP 401): bad token")


class CrashPlatform(BasePlatform):
    name = "Crash"

    async def publish(self, message: str, link: str) -> PublishedPost:
        raise RuntimeError("boom")


class SlowPlatform(BasePlatform):
    name = "Slow"

    async def publish(self, message: str, link: str) -> PublishedPost:
        await asyncio.sleep(5)
        return PublishedPost(url="https://slow.example", public=True)


class UnconfiguredPlatform(BasePlatform):
    name = "Unconfigured"
    required_settings = ("github_token",)

    async def publish(self, message: str, link: str) -> PublishedPost:
        raise AssertionError("must not be called")


def public_check_transport(status: int = 200) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(status))


@pytest.fixture
def client_with(request: pytest.FixtureRequest):
    def _build(*platforms: type[BasePlatform], status: int = 200, **settings: object) -> TestClient:
        service = PostingService(
            make_settings(**settings), platforms, transport=public_check_transport(status)
        )
        app.dependency_overrides[get_posting_service] = lambda: service
        return TestClient(app)

    yield _build
    app.dependency_overrides.clear()


# --- validation --------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"message": "x" * 190 + " https://example.com"}, "must not exceed 200 characters"),
        ({"message": "No link in this message"}, "exactly one CTA link (none found)"),
        ({"message": "Two https://a.com and https://b.com"}, "exactly one CTA link (found 2)"),
        ({"message": "Bare link www.example.com"}, "must start with http:// or https://"),
        ({"message": "FTP link ftp://example.com/file"}, "must use http or https"),
        ({"message": "Bad host https://exa mple"}, "invalid domain"),
        ({"message": "No TLD https://localhost:8000"}, "invalid domain"),
        ({"message": "Private https://192.168.1.10/x"}, "public address"),
        ({"message": "Creds https://user:pass@example.com"}, "must not contain credentials"),
        ({"message": "Bad port https://example.com:99999"}, "invalid port"),
        ({"message": "   "}, "must not be empty"),
        ({"message": 123}, "valid string"),
        ({}, "Field required"),
        ({"message": VALID_MESSAGE, "platforms": ["x"]}, "Extra inputs are not permitted"),
    ],
)
def test_invalid_messages_return_422(client_with, body: dict, expected: str) -> None:
    response = client_with(OkPlatform).post("/posting", json=body)

    assert response.status_code == 422
    data = response.json()
    assert data["success"] is False
    assert expected in data["errors"][0]["error"]


def test_malformed_json_returns_422(client_with) -> None:
    response = client_with(OkPlatform).post(
        "/posting", content="{not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["success"] is False


@pytest.mark.parametrize(
    "message",
    [
        VALID_MESSAGE,
        "Trailing punctuation is fine: https://example.com/path?q=1.",
        "Unicode domain works https://bücher.de 🚀",
        "x" * 180 + " https://a.co",  # exactly 200 chars
    ],
)
def test_valid_messages_are_accepted(client_with, message: str) -> None:
    response = client_with(OkPlatform).post("/posting", json={"message": message})
    assert response.status_code == 200, response.text


# --- fan-out / error isolation ---------------------------------------------


def test_one_failure_does_not_stop_other_platforms(client_with) -> None:
    client = client_with(
        OkPlatform, AuthFailPlatform, CrashPlatform, SlowPlatform, UnconfiguredPlatform,
        platform_timeout_seconds=0.2,
    )
    response = client.post("/posting", json={"message": VALID_MESSAGE})

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["summary"] == {"total": 5, "succeeded": 1, "failed": 4}

    results = {r["platform"]: r for r in data["results"]}
    ok = results["Ok"]
    assert ok["status"] == "success"
    assert ok["posted_url"] == "https://ok.example/post/1"
    assert ok["public_access"] is True
    assert ok["date"] and ok["time"] and ok["error"] is None

    assert results["AuthFail"]["error"] == "Authentication failed (HTTP 401): bad token"
    assert results["Crash"]["error"] == "Unexpected internal error"
    assert results["Slow"]["error"].startswith("Timed out")
    assert results["Unconfigured"]["error"] == "Not configured: set GITHUB_TOKEN in .env"
    for name in ("AuthFail", "Crash", "Slow", "Unconfigured"):
        failed = results[name]
        assert failed["status"] == "failed"
        assert failed["posted_url"] is None and failed["date"] is None
        assert failed["public_access"] is False


def test_all_failed_reports_success_false(client_with) -> None:
    data = client_with(AuthFailPlatform).post("/posting", json={"message": VALID_MESSAGE}).json()
    assert data["success"] is False


def test_public_access_reflects_declared_visibility(client_with) -> None:
    data = client_with(PrivatePlatform).post("/posting", json={"message": VALID_MESSAGE}).json()
    assert data["results"][0]["public_access"] is False


def test_public_access_false_when_anonymous_get_404s(client_with) -> None:
    data = client_with(OkPlatform, status=404).post(
        "/posting", json={"message": VALID_MESSAGE}
    ).json()
    assert data["results"][0]["status"] == "success"
    assert data["results"][0]["public_access"] is False


def test_public_access_inconclusive_403_keeps_declared_visibility(client_with) -> None:
    data = client_with(OkPlatform, status=403).post(
        "/posting", json={"message": VALID_MESSAGE}
    ).json()
    assert data["results"][0]["public_access"] is True


def test_platforms_endpoint_lists_configuration(client_with) -> None:
    data = client_with(OkPlatform, UnconfiguredPlatform).get("/platforms").json()
    assert data == [
        {"platform": "Ok", "configured": True, "missing_settings": []},
        {"platform": "Unconfigured", "configured": False, "missing_settings": ["GITHUB_TOKEN"]},
    ]

"""Request / response models and message validation rules."""

import ipaddress
import re
from enum import Enum
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_MESSAGE_LENGTH = 200
ALLOWED_SCHEMES = ("http", "https")

# Anything that looks like a link: "<scheme>://..." or a bare "www.".
_LINK_PATTERN = re.compile(r"(?:\b[a-z][a-z0-9+.\-]*://|\bwww\.)[^\s<>\"']+", re.IGNORECASE)
_HOSTNAME_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:(?!-)[a-z0-9-]{1,63}(?<!-)\.)+(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$",
    re.IGNORECASE,
)


def _strip_trailing_punctuation(link: str) -> str:
    """Drop sentence punctuation glued to the end of a link ("...example.com.")."""
    while link:
        last = link[-1]
        if last in ".,;:!?'\"":
            link = link[:-1]
        elif last == ")" and link.count("(") < link.count(")"):
            link = link[:-1]
        elif last == "]" and link.count("[") < link.count("]"):
            link = link[:-1]
        else:
            break
    return link


def extract_links(text: str) -> list[str]:
    links = (_strip_trailing_punctuation(m.group(0)) for m in _LINK_PATTERN.finditer(text))
    return [link for link in links if link]


def validate_cta_url(link: str) -> str:
    """Raise ValueError with a client-friendly reason if `link` is not a valid public URL."""
    if link.lower().startswith("www."):
        raise ValueError(f"CTA link '{link}' must start with http:// or https://.")

    parts = urlsplit(link)
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise ValueError(f"CTA link '{link}' must use http or https (got '{parts.scheme}').")
    if parts.username or parts.password:
        raise ValueError("CTA link must not contain credentials.")
    try:
        parts.port  # noqa: B018 - accessing .port validates it
    except ValueError as exc:
        raise ValueError(f"CTA link '{link}' has an invalid port.") from exc

    host = parts.hostname
    if not host:
        raise ValueError(f"CTA link '{link}' has no host.")

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if not ip.is_global:
            raise ValueError("CTA link must point to a public address.")
        return link

    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError(f"CTA link '{link}' has an invalid domain.") from exc
    if not _HOSTNAME_PATTERN.match(ascii_host):
        raise ValueError(f"CTA link '{link}' has an invalid domain.")
    return link


class PostingRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "message": "Check out our latest business platform and grow your "
                    "online visibility. https://example.com"
                }
            ]
        },
    )

    message: str = Field(
        ...,
        description=f"Text to publish (max {MAX_MESSAGE_LENGTH} characters) "
        "containing exactly one http(s) CTA link.",
    )

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        message = value.strip()
        if not message:
            raise ValueError("Message must not be empty.")
        if len(message) > MAX_MESSAGE_LENGTH:
            raise ValueError(
                f"Message must not exceed {MAX_MESSAGE_LENGTH} characters (got {len(message)})."
            )

        links = extract_links(message)
        if not links:
            raise ValueError("Message must include exactly one CTA link (none found).")
        if len(links) > 1:
            raise ValueError(f"Message must include exactly one CTA link (found {len(links)}).")

        validate_cta_url(links[0])
        return message

    @property
    def cta_url(self) -> str:
        return extract_links(self.message)[0]


class PostStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"


class PlatformResult(BaseModel):
    platform: str
    status: PostStatus
    posted_url: str | None = None
    public_access: bool = False
    date: str | None = None
    time: str | None = None
    error: str | None = None


class PostingSummary(BaseModel):
    total: int
    succeeded: int
    failed: int


class PostingResponse(BaseModel):
    success: bool = Field(description="True when at least one platform published the message.")
    summary: PostingSummary
    results: list[PlatformResult]


class ErrorDetail(BaseModel):
    field: str
    error: str


class ValidationErrorResponse(BaseModel):
    success: bool = False
    errors: list[ErrorDetail]


class PlatformStatus(BaseModel):
    platform: str
    configured: bool
    missing_settings: list[str]

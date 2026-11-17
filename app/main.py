"""FastAPI entrypoint: `uvicorn app.main:app --host 0.0.0.0 --port 4000`"""

import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.schemas import (
    PlatformStatus,
    PostingRequest,
    PostingResponse,
    PostingSummary,
    PostStatus,
    ValidationErrorResponse,
)
from app.services.posting_service import PostingService


def configure_logging(settings: Settings) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if settings.log_file:
        Path(settings.log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(settings.log_file, encoding="utf-8"))
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    # httpx logs full request URLs at INFO; the Telegram URL contains the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


configure_logging(get_settings())
logger = logging.getLogger("app")

app = FastAPI(
    title="Automated Multi-Platform Posting",
    version="1.0.0",
    description="Validates a short message with one CTA link and publishes it to every "
    "configured platform concurrently. One platform failing never stops the others.",
)


def get_posting_service() -> PostingService:
    return PostingService(get_settings())


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = []
    for err in exc.errors():
        field = ".".join(str(part) for part in err["loc"] if part != "body") or "body"
        errors.append({"field": field, "error": str(err["msg"]).removeprefix("Value error, ")})
    return JSONResponse(status_code=422, content={"success": False, "errors": errors})


@app.post(
    "/posting",
    response_model=PostingResponse,
    responses={422: {"model": ValidationErrorResponse, "description": "Invalid message"}},
    summary="Publish a message to all platforms",
)
async def create_posting(
    payload: PostingRequest, service: PostingService = Depends(get_posting_service)
) -> PostingResponse:
    logger.info("Posting request received (%d chars, link=%s)", len(payload.message), payload.cta_url)
    results = await service.publish(payload.message, payload.cta_url)
    succeeded = sum(result.status is PostStatus.SUCCESS for result in results)
    logger.info("Posting finished: %d/%d platforms succeeded", succeeded, len(results))
    return PostingResponse(
        success=succeeded > 0,
        summary=PostingSummary(
            total=len(results), succeeded=succeeded, failed=len(results) - succeeded
        ),
        results=results,
    )


@app.get("/platforms", response_model=list[PlatformStatus], summary="Which platforms are configured")
async def list_platforms(
    service: PostingService = Depends(get_posting_service),
) -> list[PlatformStatus]:
    return service.platform_statuses()


@app.get("/health", summary="Liveness check")
async def health() -> dict[str, str]:
    return {"status": "ok"}

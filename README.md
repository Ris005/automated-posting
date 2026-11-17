# Automated Multi-Platform Posting (FastAPI)

A FastAPI service with one endpoint, `POST /posting`. It checks a short message that contains exactly one call-to-action (CTA) link, then **publishes it to 7 platforms at the same time** through their official APIs. Each platform runs on its own, so if one fails (bad token, rate limit, timeout, crash) the others still post. You get one result per platform.

| | |
|---|---|
| Stack | Python 3.11+, FastAPI, Uvicorn, Pydantic v2, pydantic-settings, HTTPX (async) |
| Endpoint | `POST http://localhost:4000/posting` |
| Docs | `http://localhost:4000/docs` (Swagger UI) |
| Tests | 42 pytest tests, all HTTP mocked, no credentials needed |
| Quick start | `./run.sh` (or `run.bat`). Full step-by-step guide and test report: **[HOW_TO_RUN.md](HOW_TO_RUN.md)** |
| Demo without keys | `./scripts/demo_without_keys.sh` |
| Submitting | Requirement review, GitHub push steps and email template: **[SUBMISSION.md](SUBMISSION.md)** |

---

## Platforms integrated

| # | Platform | API used | Auth | Posted URL | Public? |
|---|---|---|---|---|---|
| 1 | **Telegram** | [Bot API `sendMessage`](https://core.telegram.org/bots/api#sendmessage) | Bot token | `https://t.me/<channel>/<id>` | Yes for a public channel; `t.me/c/...` (members only) for a private one |
| 2 | **Discord** | [Execute Webhook](https://discord.com/developers/docs/resources/webhook#execute-webhook) (`?wait=true`) | Webhook URL | `https://discord.com/channels/<guild>/<channel>/<msg>` | No, server members only |
| 3 | **Mastodon** | [`POST /api/v1/statuses`](https://docs.joinmastodon.org/methods/statuses/#create) | OAuth bearer token | status `url` | Yes (`visibility=public`) |
| 4 | **Bluesky** | AT Protocol [`createSession`](https://docs.bsky.app/docs/api/com-atproto-server-create-session) + [`createRecord`](https://docs.bsky.app/docs/api/com-atproto-repo-create-record) | App password | `https://bsky.app/profile/<handle>/post/<rkey>` | Yes |
| 5 | **DEV Community** | [Forem API v1 `POST /api/articles`](https://developers.forem.com/api/v1#tag/articles/operation/createArticle) | `api-key` header | article `url` | Yes (`published=true`) |
| 6 | **GitHub Gist** | [`POST /gists`](https://docs.github.com/en/rest/gists/gists#create-a-gist) | Bearer token (gist scope) | `html_url` | Yes (`public=true`) |
| 7 | **Pastebin** | [`api_post.php`](https://pastebin.com/doc_api#2) | Developer API key | paste URL (plain text response) | Yes (`api_paste_private=0`) |

Integration details:

- **Bluesky facets.** A link in a Bluesky post is only clickable when it is sent as a *facet* with **UTF-8 byte offsets**, not character offsets. `build_link_facet` computes those offsets, and a test with an emoji proves they differ from character positions.
- **Mastodon idempotency.** Every status carries an `Idempotency-Key`, so a repeated request cannot create a duplicate post.
- **Discord.** A webhook returns `204 No Content` unless you add `?wait=true`. The service adds it to get the message id, then looks up the server (guild) id to build a clickable message link. Mentions are disabled so a message can never ping `@everyone`.
- **Telegram.** The bot token is part of the API URL. Error messages never include it, and the `httpx` request logger is turned down to WARNING so the URL never reaches the logs.
- **DEV Community / Gist / Pastebin.** These platforms need a title. It is made from the message text with the link removed, cut at a word boundary.

Some well-known platforms were left out on purpose. X/Twitter charges for write access to its API. LinkedIn and Reddit need an app review or approval before you can post through their APIs, which can't be done within a 2–4 hour test.

---

## How it works

```
POST /posting
   │
   ├─ PostingRequest (Pydantic) ── validation fails ──> 422 {"success": false, "errors": [...]}
   │
   └─ PostingService.publish()
         ├─ one shared httpx.AsyncClient (timeouts, User-Agent)
         └─ asyncio.gather( _publish_to(platform) for each of the 7 platforms )
               ├─ not configured?     -> failed "Not configured: set X in .env"
               ├─ asyncio.wait_for(platform.publish(), PLATFORM_TIMEOUT_SECONDS)
               ├─ PlatformError       -> failed with the platform's own error text
               ├─ timeout             -> failed "Timed out after Ns"
               ├─ network error       -> failed "Network error: ..."
               ├─ any other exception -> failed "Unexpected internal error" (stack trace logged)
               └─ success             -> date/time stamped, public access verified
```

```
app/
├── main.py                  # FastAPI app, routes, 422 handler, logging setup
├── config.py                # pydantic-settings: all credentials from env / .env
├── schemas.py               # request validation + response models
├── platforms/
│   ├── base.py              # BasePlatform contract, PlatformError, HTTP/error helpers
│   ├── telegram.py  discord.py  mastodon.py  bluesky.py
│   ├── devto.py  github_gist.py  pastebin.py
│   └── __init__.py          # PLATFORM_CLASSES registry
└── services/
    └── posting_service.py   # concurrent fan-out, failure isolation, public-access check
tests/
├── test_posting.py          # API + validation + failure isolation
└── test_platforms.py        # each integration against a mocked HTTP transport
```

**Choosing platforms.** The app picks the platforms itself (the request has no platform field, and extra fields are rejected). It posts to every platform in `PLATFORM_CLASSES`. Adding a platform takes one new file with a `publish()` method plus one entry in that registry.

**Retries.** A request is retried **only** when the connection was never established (`ConnectError`/`ConnectTimeout`). In that case the server never saw it, so a retry can't post twice. Read timeouts and HTTP errors are not retried, because the post may already be live.

**Public Access.** This is worked out in two steps:
1. The platform's own visibility for the post: Gist `public`, Mastodon `visibility`, DEV `published`, Telegram channel with a username, and Discord always private.
2. If step 1 says public, the service opens the posted URL anonymously. A `401`, `404` or `410` marks the post not public. Bot-protection pages (`403`/`429`) and network errors don't prove anything, so the step-1 visibility stands.

Turn step 2 off with `VERIFY_PUBLIC_ACCESS=false`.

**Date and time** are when the platform accepted the post, in `TIMEZONE` (default `Asia/Kolkata`).

**Top-level `success`** is `true` when at least one platform published the message. `summary` gives the counts.

---

## Input validation

| Rule | Example input | Error |
|---|---|---|
| Not empty | `"   "` | `Message must not be empty.` |
| ≤ 200 characters (after trimming) | 201 chars | `Message must not exceed 200 characters (got 201).` |
| Exactly one CTA link | no link | `Message must include exactly one CTA link (none found).` |
| | two links | `Message must include exactly one CTA link (found 2).` |
| Scheme must be http/https | `www.example.com`, `ftp://…` | `must start with http:// or https://` / `must use http or https` |
| Valid domain with a TLD | `https://localhost:8000`, `https://exa mple` | `has an invalid domain.` |
| No private / loopback IPs | `https://192.168.1.10` | `CTA link must point to a public address.` |
| No embedded credentials | `https://user:pass@site.com` | `CTA link must not contain credentials.` |
| Valid port | `https://example.com:99999` | `has an invalid port.` |
| Body shape | missing `message`, non-string, extra fields, malformed JSON | Pydantic message |

Punctuation at the end of a sentence is not counted as part of the link (`...https://example.com.` works). Internationalised domains (`https://bücher.de`) are supported through IDNA.

---

## Setup

```bash
git clone <this-repo> && cd automated-posting
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env        # then fill in the platforms you want
```

Where to get each credential is written next to it in [`.env.example`](.env.example). Any platform you leave blank still shows up in the response as `failed` with `Not configured: set … in .env`, and the app keeps running.

## Run

```bash
uvicorn app.main:app --host 0.0.0.0 --port 4000
```

- Swagger UI: http://localhost:4000/docs
- `GET /platforms` lists which platforms are configured (it never shows secrets).
- `GET /health` is a liveness check.
- Logs go to the console and to `logs/posting.log`.

## Tests

```bash
pytest
```

Each integration is tested against `httpx.MockTransport`, which mimics the real API's request and response format. The tests also cover validation and failure isolation: one platform succeeds while others fail auth, crash, time out, or are not configured.

---

## Sample requests and responses

### Success with partial failure (real output)

This output comes from `./scripts/demo_without_keys.sh`:
- Discord, Mastodon and Bluesky posted to a local fake of their APIs.
- Telegram, DEV, GitHub and Pastebin were sent fake keys and returned the errors from their **real** APIs.

Full output: [`docs/logs/demo-run-output.txt`](docs/logs/demo-run-output.txt).

```bash
curl -X POST http://localhost:4000/posting \
  -H "Content-Type: application/json" \
  -d '{"message": "Grow your online visibility today https://example.com"}'
```

```json
{
  "success": true,
  "summary": { "total": 7, "succeeded": 3, "failed": 4 },
  "results": [
    { "platform": "Telegram", "status": "failed", "posted_url": null, "public_access": false,
      "date": null, "time": null, "error": "Telegram API error (401): Unauthorized" },
    { "platform": "Discord", "status": "success", "posted_url": "https://discord.com/channels/333/222/111",
      "public_access": false, "date": "2026-11-17", "time": "11:46:33", "error": null },
    { "platform": "Mastodon", "status": "success", "posted_url": "http://127.0.0.1:4100/@me/1",
      "public_access": true, "date": "2026-11-17", "time": "11:46:33", "error": null },
    { "platform": "Bluesky", "status": "success", "posted_url": "https://bsky.app/profile/me.test/post/3abc",
      "public_access": true, "date": "2026-11-17", "time": "11:46:33", "error": null },
    { "platform": "DEV Community", "status": "failed", "posted_url": null, "public_access": false,
      "date": null, "time": null, "error": "Authentication failed (HTTP 401): unauthorized" },
    { "platform": "GitHub Gist", "status": "failed", "posted_url": null, "public_access": false,
      "date": null, "time": null, "error": "Authentication failed (HTTP 401): Bad credentials" },
    { "platform": "Pastebin", "status": "failed", "posted_url": null, "public_access": false,
      "date": null, "time": null, "error": "Pastebin API error (HTTP 422): Bad API request, invalid api_dev_key" }
  ]
}
```

> After you post with real keys, add that response here too, with live post URLs.

### No credentials configured (real output)

```json
{
  "success": false,
  "summary": { "total": 7, "succeeded": 0, "failed": 7 },
  "results": [
    {
      "platform": "Telegram",
      "status": "failed",
      "posted_url": null,
      "public_access": false,
      "date": null,
      "time": null,
      "error": "Not configured: set TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID in .env"
    }
  ]
}
```

(Only the first of the 7 entries is shown here.)

### Validation error (HTTP 422)

```bash
curl -X POST http://localhost:4000/posting \
  -H "Content-Type: application/json" \
  -d '{"message": "Visit https://a.com and https://b.com"}'
```

```json
{
  "success": false,
  "errors": [
    { "field": "message", "error": "Message must include exactly one CTA link (found 2)." }
  ]
}
```

---

## Screenshots / logs

| Proof | File |
|---|---|
| Swagger UI (`/docs`) | [`docs/screenshots/swagger.png`](docs/screenshots/swagger.png) |
| Full request/response run | [`docs/logs/demo-run-output.txt`](docs/logs/demo-run-output.txt) |
| Server log of that run | [`docs/logs/demo-server.log`](docs/logs/demo-server.log) |

![Swagger UI](docs/screenshots/swagger.png)

Server log from the demo run:

```
INFO    app: Posting request received (53 chars, link=https://example.com)
INFO    app.services.posting_service: [Discord] posted https://discord.com/channels/333/222/111 (public=False)
INFO    app.services.posting_service: [Mastodon] posted http://127.0.0.1:4100/@me/1 (public=True)
WARNING app.services.posting_service: [Pastebin] failed - Pastebin API error (HTTP 422): Bad API request, invalid api_dev_key
WARNING app.services.posting_service: [DEV Community] failed - Authentication failed (HTTP 401): unauthorized
WARNING app.services.posting_service: [GitHub Gist] failed - Authentication failed (HTTP 401): Bad credentials
WARNING app.services.posting_service: [Telegram] failed - Telegram API error (401): Unauthorized
INFO    app.services.posting_service: [Bluesky] posted https://bsky.app/profile/me.test/post/3abc (public=True)
INFO    app: Posting finished: 3/7 platforms succeeded
```

The platforms finish in whatever order their APIs answer. All requests run at the same time, and a failure on one never blocks another.

> After a real run, add screenshots of the live posts on each platform to `docs/screenshots/`.

## Security

- No credentials are committed. They come from the environment or `.env` (which is git-ignored). `.env.example` contains only placeholders.
- Secrets are never placed in error messages, responses or logs.
- Discord mentions are disabled, so a message can't ping `@everyone`.
- CTA links that point at private or loopback addresses are rejected.

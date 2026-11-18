"""Account-free, one-time secret sharing backed by Vault response wrapping."""

import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import hvac
import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from app.i18n import catalog, message, normalize_language, render_page
from app.middleware import RequestSizeLimitMiddleware
from app.vault import VaultClientManager, VaultUnavailable

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

VAULT_ADDR = os.getenv("VAULT_ADDR", "https://vault.example.com")
VAULT_TOKEN = os.getenv("VAULT_TOKEN")
VAULT_ROLE = os.getenv("VAULT_ROLE")
VAULT_NAMESPACE = os.getenv("VAULT_NAMESPACE", "")
VAULT_AUTH_MOUNT = os.getenv("VAULT_AUTH_MOUNT", "kubernetes")
VAULT_TIMEOUT = int(os.getenv("VAULT_TIMEOUT", "10"))
APP_LANGUAGE = normalize_language(os.getenv("APP_LANGUAGE", "en"))
DEFAULT_WRAP_TTL = os.getenv("DEFAULT_WRAP_TTL", "5m")
MAX_WRAP_TTL = os.getenv("MAX_WRAP_TTL", "24h")
MAX_REQUEST_SIZE = int(os.getenv("MAX_REQUEST_SIZE", str(1024 * 1024)))
_default_ttl_seconds = 0
_max_ttl_seconds = 0


def translate(key: str, **values) -> str:
    return message(APP_LANGUAGE, key, **values)


vault_manager = VaultClientManager(
    url=VAULT_ADDR,
    token=VAULT_TOKEN,
    role=VAULT_ROLE,
    namespace=VAULT_NAMESPACE,
    auth_mount=VAULT_AUTH_MOUNT,
    timeout=VAULT_TIMEOUT,
)


def parse_ttl(ttl_str: str) -> int:
    """Normalize positive seconds or an s/m/h/d duration without changing its units."""
    if not ttl_str or not isinstance(ttl_str, str):
        raise ValueError(translate("err_ttl_required"))
    ttl_str = ttl_str.strip().lower()
    if not ttl_str:
        raise ValueError(translate("err_ttl_empty"))
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    try:
        if ttl_str.isdigit():
            value = int(ttl_str)
        elif ttl_str[-1] in multipliers:
            value = int(ttl_str[:-1]) * multipliers[ttl_str[-1]]
        else:
            raise ValueError("Unsupported TTL suffix")
    except (ValueError, IndexError) as exc:
        raise ValueError(translate("err_ttl_format", value=ttl_str)) from exc
    if value <= 0:
        raise ValueError(translate("err_ttl_positive", seconds=value))
    return value


def validate_ttl_config() -> tuple[int, int]:
    """Reject invalid server limits before serving requests."""
    try:
        max_ttl = parse_ttl(MAX_WRAP_TTL)
    except ValueError as exc:
        raise ValueError(
            translate("err_config_invalid", name="MAX_WRAP_TTL", reason=exc)
        ) from exc
    try:
        default_ttl = parse_ttl(DEFAULT_WRAP_TTL)
    except ValueError as exc:
        raise ValueError(
            translate("err_config_invalid", name="DEFAULT_WRAP_TTL", reason=exc)
        ) from exc
    if default_ttl > max_ttl:
        raise ValueError(
            translate(
                "err_config_ttl_limit",
                default=DEFAULT_WRAP_TTL,
                default_seconds=default_ttl,
                maximum=MAX_WRAP_TTL,
                max_seconds=max_ttl,
            )
        )
    return default_ttl, max_ttl


def validate_request_ttl(ttl_str: str) -> int:
    """Validate a user-supplied duration before contacting Vault."""
    try:
        ttl_seconds = parse_ttl(ttl_str)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if ttl_seconds > _max_ttl_seconds:
        raise HTTPException(
            status_code=400,
            detail=translate(
                "err_request_ttl_limit",
                requested=ttl_str,
                seconds=ttl_seconds,
                maximum=MAX_WRAP_TTL,
                max_seconds=_max_ttl_seconds,
            ),
        )
    return ttl_seconds


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate public limits without requiring Vault during process startup."""
    global _default_ttl_seconds, _max_ttl_seconds
    normalize_language(APP_LANGUAGE)
    _default_ttl_seconds, _max_ttl_seconds = validate_ttl_config()
    if MAX_REQUEST_SIZE <= 0:
        raise ValueError(translate("err_size_config"))
    if VAULT_TIMEOUT <= 0:
        raise ValueError(translate("err_timeout_config"))
    try:
        yield
    finally:
        vault_manager.close()


app = FastAPI(
    title="Vault Wrap Proxy",
    description="One-time secret sharing using Vault",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    RequestSizeLimitMiddleware,
    max_size=lambda: MAX_REQUEST_SIZE,
    language=lambda: APP_LANGUAGE,
)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    response = await request_validation_exception_handler(request, exc)
    payload = json.loads(response.body)
    translations = catalog(APP_LANGUAGE)
    for error in payload["detail"]:
        key = "validation_" + error["type"]
        error["msg"] = translate(key if key in translations else "validation_invalid")
    return JSONResponse(payload, status_code=response.status_code)


class WrapRequest(BaseModel):
    """User-supplied data to share."""

    data: dict = Field(..., description="Data to wrap (JSON object)")
    ttl: str = Field(
        default=DEFAULT_WRAP_TTL,
        description=f"Wrapping token lifetime (e.g. 5m, 1h). Maximum: {MAX_WRAP_TTL}",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "data": {"username": "admin", "password": "secret123"},
                    "ttl": "10m",
                }
            ]
        }
    }


class WrapResponse(BaseModel):
    """The generated wrapping token."""

    token: str = Field(..., description="Wrapped token")
    ttl: int = Field(..., description="Lifetime in seconds")
    creation_time: str = Field(..., description="Creation time")


class UnwrapRequest(BaseModel):
    """A wrapping token to consume."""

    token: str = Field(..., description="Wrapping token to reveal")

    model_config = {"json_schema_extra": {"examples": [{"token": "hvs.CAESIA..."}]}}


class UnwrapResponse(BaseModel):
    """The revealed data."""

    data: dict = Field(..., description="Revealed data")


class LookupRequest(BaseModel):
    """A wrapping token to inspect without consuming it."""

    token: str = Field(..., description="Wrapping token to inspect")


class LookupResponse(BaseModel):
    """Wrapping token metadata."""

    creation_time: str | None = Field(None, description="Creation time")
    creation_ttl: int | None = Field(None, description="Initial lifetime in seconds")
    ttl: int | None = Field(None, description="Remaining lifetime in seconds")


class ConfigResponse(BaseModel):
    language: Literal["en", "fr", "es"]
    default_wrap_ttl: str
    default_wrap_ttl_seconds: int
    max_wrap_ttl: str
    max_wrap_ttl_seconds: int
    max_request_size: int


def perform_vault(operation, *, token_operation=False):
    """Translate upstream failures without exposing data or exception messages."""
    try:
        return vault_manager.perform(operation)
    except hvac.exceptions.InvalidRequest as exc:
        detail = (
            translate("err_invalid_token")
            if token_operation
            else translate("err_vault_request")
        )
        raise HTTPException(status_code=400, detail=detail) from exc
    except (
        hvac.exceptions.VaultError,
        requests.RequestException,
        VaultUnavailable,
    ) as exc:
        logger.warning("Vault unavailable (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=503, detail=translate("err_vault_unavailable")
        ) from exc


@app.get("/health", tags=["Health"])
def health_check():
    """Liveness: the process responds, independently of Vault availability."""
    return {"status": "healthy"}


@app.get("/ready", tags=["Health"])
def readiness_check():
    """Readiness: a real authenticated Vault request must succeed."""
    if not vault_manager.is_ready():
        return JSONResponse({"status": "not_ready"}, status_code=503)
    return {"status": "ready"}


@app.get("/api/config", response_model=ConfigResponse, tags=["Config"])
def get_config():
    """Public UI settings only; no upstream address, credentials or namespace."""
    return ConfigResponse(
        language=APP_LANGUAGE,
        default_wrap_ttl=DEFAULT_WRAP_TTL,
        default_wrap_ttl_seconds=_default_ttl_seconds,
        max_wrap_ttl=MAX_WRAP_TTL,
        max_wrap_ttl_seconds=_max_ttl_seconds,
        max_request_size=MAX_REQUEST_SIZE,
    )


@app.post("/api/wrap", response_model=WrapResponse, tags=["Wrapping"])
def wrap_data(request: WrapRequest):
    """Wrap user-supplied JSON; validate TTL before contacting Vault."""
    ttl_seconds = validate_request_ttl(request.ttl)
    result = perform_vault(
        lambda client: client.sys.wrap(payload=request.data, ttl=ttl_seconds)
    )
    info = result["wrap_info"]
    return WrapResponse(
        token=info["token"], ttl=info["ttl"], creation_time=info["creation_time"]
    )


@app.post("/api/unwrap", response_model=UnwrapResponse, tags=["Wrapping"])
def unwrap_token(request: UnwrapRequest):
    """Consume a wrapping token once. Ambiguous network failures are not retried."""
    result = perform_vault(
        lambda client: client.sys.unwrap(token=request.token), token_operation=True
    )
    return UnwrapResponse(data=result.get("data", {}))


@app.post("/api/lookup", response_model=LookupResponse, tags=["Wrapping"])
def lookup_token(request: LookupRequest):
    """Inspect a token using the same namespace and transport as other calls."""
    result = perform_vault(
        lambda client: client.adapter.post(
            "/v1/sys/wrapping/lookup", json={"token": request.token}
        ),
        token_operation=True,
    )
    data = result.get("data", {})
    created = data.get("creation_time")
    ttl = data.get("creation_ttl")
    remaining = None
    if created and ttl:
        try:
            instant = datetime.fromisoformat(created.replace("Z", "+00:00"))
            remaining = max(
                0, int(ttl - (datetime.now(timezone.utc) - instant).total_seconds())
            )
        except ValueError, TypeError:
            logger.warning("Invalid Vault creation time")
    return LookupResponse(creation_time=created, creation_ttl=ttl, ttl=remaining)


HTML_TEMPLATE = (Path(__file__).parent / "static" / "index.html").read_text(
    encoding="utf-8"
)


@app.get("/", response_class=HTMLResponse, tags=["UI"])
def web_ui():
    return HTMLResponse(
        render_page(HTML_TEMPLATE, APP_LANGUAGE), headers={"Cache-Control": "no-store"}
    )

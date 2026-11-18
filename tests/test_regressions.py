"""Regression tests for the review findings, using the actual ASGI app."""

import asyncio
import json
import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main


@pytest.fixture
def configured_app(monkeypatch):
    client = MagicMock()
    client.sys.wrap.return_value = {
        "wrap_info": {
            "token": "hvs.review",
            "ttl": 60,
            "creation_time": datetime.now(timezone.utc).isoformat(),
        }
    }
    manager = MagicMock()
    manager.perform.side_effect = lambda operation: operation(client)
    manager.is_ready.return_value = True
    monkeypatch.setattr(main, "vault_manager", manager)
    monkeypatch.setattr(main, "DEFAULT_WRAP_TTL", "30s")
    monkeypatch.setattr(main, "MAX_WRAP_TTL", "60s")
    monkeypatch.setattr(main, "MAX_REQUEST_SIZE", 256)
    with TestClient(main.app):
        yield main.app, client, manager


@pytest.mark.asyncio
async def test_chunked_oversized_body_is_rejected_before_vault(configured_app):
    app, vault, _ = configured_app
    read_chunks = []

    async def body():
        for index in range(20):
            read_chunks.append(index)
            yield b" " * 128

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/wrap", content=body(), headers={"Content-Type": "application/json"}
        )
    assert "content-length" not in response.request.headers
    assert response.status_code == 413
    assert len(read_chunks) == 3
    vault.sys.wrap.assert_not_called()


@pytest.mark.asyncio
async def test_chunked_valid_body_preserves_json(configured_app):
    app, vault, _ = configured_app
    data = {"unicode": "é中文", "nested": {"list": [1, "a", None]}}
    payload = json.dumps({"data": data, "ttl": "30s"}, ensure_ascii=False).encode()

    async def body():
        for offset in range(0, len(payload), 7):
            yield payload[offset : offset + 7]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/wrap", content=body(), headers={"Content-Type": "application/json"}
        )
    assert response.status_code == 200
    vault.sys.wrap.assert_called_once_with(payload=data, ttl=30)
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
@pytest.mark.parametrize("streamed", [False, True])
async def test_exact_size_limit_is_accepted(configured_app, streamed):
    app, vault, _ = configured_app
    data = {"pad": ""}
    base = json.dumps({"data": data, "ttl": "30s"}, separators=(",", ":")).encode()
    data["pad"] = "x" * (main.MAX_REQUEST_SIZE - len(base))
    payload = json.dumps({"data": data, "ttl": "30s"}, separators=(",", ":")).encode()
    assert len(payload) == main.MAX_REQUEST_SIZE

    async def body():
        for offset in range(0, len(payload), 3):
            yield payload[offset : offset + 3]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/wrap",
            content=body() if streamed else payload,
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 200
    vault.sys.wrap.assert_called_once_with(payload=data, ttl=30)


@pytest.mark.asyncio
async def test_false_small_content_length_cannot_bypass_limit(configured_app):
    app, vault, _ = configured_app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/wrap", content=b"x" * 257, headers={"Content-Length": "1"}
        )
    assert response.status_code == 413
    vault.sys.wrap.assert_not_called()


@pytest.mark.parametrize("length", ["-1", "invalid"])
def test_invalid_content_length_is_rejected(configured_app, length):
    app, vault, _ = configured_app
    response = TestClient(app).post(
        "/api/wrap", content=b"{}", headers={"Content-Length": length}
    )
    assert response.status_code == 400
    vault.sys.wrap.assert_not_called()


def test_invalid_ttl_does_not_contact_vault(configured_app):
    app, _, manager = configured_app
    response = TestClient(app).post("/api/wrap", json={"data": {}, "ttl": "61s"})
    assert response.status_code == 400
    manager.perform.assert_not_called()


def test_readiness_fails_without_killing_liveness(configured_app):
    app, _, manager = configured_app
    manager.is_ready.return_value = False
    client = TestClient(app)
    assert client.get("/ready").status_code == 503
    assert client.get("/health").status_code == 200
    manager.is_ready.return_value = True
    assert client.get("/ready").status_code == 200


def test_public_config_contains_only_ui_limits(configured_app):
    app, _, _ = configured_app
    result = TestClient(app).get("/api/config").json()
    assert result == {
        "language": "en",
        "default_wrap_ttl": "30s",
        "default_wrap_ttl_seconds": 30,
        "max_wrap_ttl": "60s",
        "max_wrap_ttl_seconds": 60,
        "max_request_size": 256,
    }


@pytest.mark.asyncio
async def test_slow_vault_does_not_block_liveness(configured_app):
    app, vault, _ = configured_app
    started = threading.Event()
    release = threading.Event()
    result = vault.sys.wrap.return_value

    def slow_wrap(**kwargs):
        started.set()
        if not release.wait(3):
            raise RuntimeError("Vault mock was not released")
        return result

    vault.sys.wrap.side_effect = slow_wrap
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        request = asyncio.create_task(
            client.post("/api/wrap", json={"data": {}, "ttl": "30s"})
        )
        try:
            assert await asyncio.to_thread(started.wait, 1)
            response = await asyncio.wait_for(client.get("/health"), timeout=0.5)
            assert response.status_code == 200
            assert not request.done()
        finally:
            release.set()
            await request


def test_lookup_uses_configured_vault_client(configured_app):
    app, vault, _ = configured_app
    vault.adapter.post.return_value = {"data": {"creation_ttl": 30}}
    response = TestClient(app).post("/api/lookup", json={"token": "hvs.review"})
    assert response.status_code == 200
    vault.adapter.post.assert_called_once_with(
        "/v1/sys/wrapping/lookup", json={"token": "hvs.review"}
    )

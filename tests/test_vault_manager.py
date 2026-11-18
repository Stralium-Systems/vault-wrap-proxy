"""Authentication lifecycle and concurrency tests without a Kubernetes cluster."""

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import hvac
import pytest
import requests

import app.vault as vault_module
from app.vault import VaultClientManager


@pytest.fixture
def manager(tmp_path, monkeypatch):
    jwt = tmp_path / "jwt"
    jwt.write_text("synthetic-jwt")
    manager = VaultClientManager(
        "https://vault.example.com",
        role="proxy",
        jwt_path=str(jwt),
        auth_mount="custom-kubernetes",
    )
    auth_client = MagicMock()
    auth_client.auth.kubernetes.login.side_effect = [
        {"auth": {"client_token": "old", "lease_duration": 3600}},
        {"auth": {"client_token": "fresh", "lease_duration": 3600}},
    ]

    def factory(token=None):
        if token is None:
            return auth_client
        client = MagicMock()
        client.token = token
        client.is_authenticated.return_value = False
        return client

    monkeypatch.setattr(manager, "_new_client", factory)
    yield manager, auth_client
    manager.close()


def test_expired_service_token_reauthenticates_on_same_request(manager):
    manager, auth = manager
    tokens = []

    def operation(client):
        tokens.append(client.token)
        if client.token == "old":
            raise hvac.exceptions.Forbidden("expired service token")
        return "ok"

    assert manager.perform(operation) == "ok"
    assert tokens == ["old", "fresh"]
    assert auth.auth.kubernetes.login.call_count == 2
    auth.auth.kubernetes.login.assert_called_with(
        role="proxy", jwt="synthetic-jwt", mount_point="custom-kubernetes"
    )


def test_refreshes_before_known_lease_expiry(manager, monkeypatch):
    manager, auth = manager
    clock = [1000.0]
    monkeypatch.setattr(vault_module.time, "monotonic", lambda: clock[0])
    assert manager.get_client().token == "old"
    clock[0] = 4571  # Lease expires at 4600; refresh margin is 30 seconds.
    assert manager.get_client().token == "fresh"
    assert auth.auth.kubernetes.login.call_count == 2


@pytest.mark.parametrize("error", [requests.ReadTimeout, requests.ConnectionError])
def test_ambiguous_unwrap_failures_are_never_replayed(manager, error):
    manager, auth = manager
    operation = MagicMock(side_effect=error("synthetic network failure"))
    with pytest.raises(error):
        manager.perform(operation)
    operation.assert_called_once()
    assert auth.auth.kubernetes.login.call_count == 1


def test_invalid_wrapping_token_does_not_refresh_service_auth(manager):
    manager, auth = manager
    operation = MagicMock(side_effect=hvac.exceptions.InvalidRequest("invalid token"))
    with pytest.raises(hvac.exceptions.InvalidRequest):
        manager.perform(operation)
    operation.assert_called_once()
    assert auth.auth.kubernetes.login.call_count == 1


def test_permission_denial_with_valid_service_token_is_not_retried(manager):
    manager, auth = manager
    manager.get_client().is_authenticated.return_value = True
    operation = MagicMock(side_effect=hvac.exceptions.Forbidden("permission denied"))
    with pytest.raises(hvac.exceptions.Forbidden):
        manager.perform(operation)
    operation.assert_called_once()
    assert auth.auth.kubernetes.login.call_count == 1


def test_clients_are_thread_local_and_login_is_shared(manager):
    manager, auth = manager
    barrier = threading.Barrier(2)

    def operation(client):
        barrier.wait(timeout=2)
        return id(client), client.token

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: manager.perform(operation), range(2)))
    assert results[0][0] != results[1][0]
    assert [token for _, token in results] == ["old", "old"]
    auth.auth.kubernetes.login.assert_called_once()


def test_namespace_is_forwarded_by_hvac_lookup(monkeypatch):
    manager = VaultClientManager(
        "https://vault.example.com", token="synthetic", namespace="team"
    )
    client = manager.get_client()
    response = MagicMock(status_code=200)
    response.json.return_value = {"data": {}}
    request = MagicMock(return_value=response)
    monkeypatch.setattr(client.adapter.session, "request", request)
    try:
        manager.perform(
            lambda client: client.adapter.post(
                "/v1/sys/wrapping/lookup", json={"token": "hvs.synthetic"}
            )
        )
        assert request.call_args.kwargs["headers"]["X-Vault-Namespace"] == "team"
    finally:
        manager.close()


def test_transport_retries_are_disabled():
    manager = VaultClientManager("https://vault.example.com", token="synthetic")
    try:
        client = manager.get_client()
        assert client.adapter.session.get_adapter("https://").max_retries.total == 0
    finally:
        manager.close()

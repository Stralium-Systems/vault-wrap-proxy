"""
Tests unitaires des endpoints API (avec mock Vault).
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_with_mock_vault(monkeypatch):
    """Client de test avec Vault mocké."""
    # Configurer l'environnement AVANT l'import
    monkeypatch.setenv("VAULT_ADDR", "https://vault.test.local")
    monkeypatch.setenv("VAULT_TOKEN", "test-token")
    monkeypatch.setenv("DEFAULT_WRAP_TTL", "5m")
    monkeypatch.setenv("MAX_WRAP_TTL", "1h")
    monkeypatch.setenv("MAX_REQUEST_SIZE", "1048576")

    # Créer le mock du client Vault
    mock_client = MagicMock()
    mock_client.token = "test-token"
    mock_client.is_authenticated.return_value = True

    # Import après configuration
    import app.main as main_module

    # Configurer les variables du module
    monkeypatch.setattr(main_module, "DEFAULT_WRAP_TTL", "5m")
    monkeypatch.setattr(main_module, "MAX_WRAP_TTL", "1h")
    monkeypatch.setattr(main_module, "MAX_REQUEST_SIZE", 1048576)
    monkeypatch.setattr(main_module, "_default_ttl_seconds", 300)
    monkeypatch.setattr(main_module, "_max_ttl_seconds", 3600)
    manager = MagicMock()
    manager.perform.side_effect = lambda operation: operation(mock_client)
    manager.is_ready.return_value = True
    monkeypatch.setattr(main_module, "vault_manager", manager)

    mock_client.sys.wrap.return_value = {
        "wrap_info": {
            "token": "hvs.test123",
            "ttl": 300,
            "creation_time": "2026-11-17T10:00:00Z",
        }
    }
    with TestClient(main_module.app) as client:
        yield client, mock_client


class TestHealthEndpoint:
    """Tests du endpoint /health."""

    def test_health_returns_status(self, client_with_mock_vault):
        """Health check retourne les informations de base."""
        client, _ = client_with_mock_vault
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data == {"status": "healthy"}


class TestConfigEndpoint:
    """Tests du endpoint /api/config."""

    def test_config_returns_limits(self, client_with_mock_vault):
        """Config retourne les limites configurées."""
        client, _ = client_with_mock_vault
        response = client.get("/api/config")

        assert response.status_code == 200
        data = response.json()
        assert data["max_wrap_ttl"] == "1h"
        assert data["max_wrap_ttl_seconds"] == 3600
        assert data["max_request_size"] == 1048576


class TestWrapEndpoint:
    """Tests du endpoint /api/wrap."""

    def test_wrap_success(self, client_with_mock_vault, sample_secret):
        """Wrap réussit avec des données valides."""
        client, mock_vault = client_with_mock_vault

        # Configurer la réponse mock
        mock_vault.sys.wrap.return_value = {
            "wrap_info": {
                "token": "hvs.test123",
                "ttl": 300,
                "creation_time": "2024-01-15T10:00:00Z",
            }
        }

        response = client.post("/api/wrap", json={"data": sample_secret, "ttl": "5m"})

        assert response.status_code == 200
        data = response.json()
        assert data["token"] == "hvs.test123"
        assert data["ttl"] == 300

    def test_wrap_ttl_exceeds_max_rejected(self, client_with_mock_vault, sample_secret):
        """TTL dépassant le maximum est rejeté."""
        client, _ = client_with_mock_vault

        response = client.post(
            "/api/wrap",
            json={"data": sample_secret, "ttl": "48h"},  # Dépasse MAX_WRAP_TTL=1h
        )

        assert response.status_code == 400
        assert "exceeds the maximum" in response.json()["detail"]

    def test_wrap_invalid_ttl_rejected(self, client_with_mock_vault, sample_secret):
        """TTL invalide est rejeté."""
        client, _ = client_with_mock_vault

        response = client.post(
            "/api/wrap", json={"data": sample_secret, "ttl": "invalid"}
        )

        assert response.status_code == 400
        assert "invalid" in response.json()["detail"].lower()

    def test_wrap_zero_ttl_rejected(self, client_with_mock_vault, sample_secret):
        """TTL zéro est rejeté."""
        client, _ = client_with_mock_vault

        response = client.post("/api/wrap", json={"data": sample_secret, "ttl": "0"})

        assert response.status_code == 400
        assert "positive" in response.json()["detail"]

    def test_wrap_negative_ttl_rejected(self, client_with_mock_vault, sample_secret):
        """TTL négatif est rejeté."""
        client, _ = client_with_mock_vault

        response = client.post("/api/wrap", json={"data": sample_secret, "ttl": "-5m"})

        assert response.status_code == 400


class TestUnwrapEndpoint:
    """Tests du endpoint /api/unwrap."""

    def test_unwrap_success(self, client_with_mock_vault, sample_secret):
        """Unwrap réussit avec un token valide."""
        client, mock_vault = client_with_mock_vault

        mock_vault.sys.unwrap.return_value = {"data": sample_secret}

        response = client.post("/api/unwrap", json={"token": "hvs.test123"})

        assert response.status_code == 200
        data = response.json()
        assert data["data"] == sample_secret

    def test_unwrap_invalid_token_rejected(self, client_with_mock_vault):
        """Token invalide retourne une erreur."""
        client, mock_vault = client_with_mock_vault

        import hvac.exceptions

        mock_vault.sys.unwrap.side_effect = hvac.exceptions.InvalidRequest(
            "invalid token"
        )

        response = client.post("/api/unwrap", json={"token": "invalid-token"})

        assert response.status_code == 400
        assert "invalid" in response.json()["detail"].lower()


class TestRequestSizeLimit:
    """Tests de la limite de taille des requêtes."""

    def test_large_request_rejected_by_header(self, client_with_mock_vault):
        """Requête avec Content-Length dépassant la limite est rejetée."""
        client, _ = client_with_mock_vault

        # Simuler une requête avec un Content-Length énorme
        response = client.post(
            "/api/wrap",
            json={"data": {"test": "data"}, "ttl": "5m"},
            headers={"Content-Length": "10000000"},  # 10 MiB
        )

        assert response.status_code == 413
        assert "too large" in response.json()["detail"]

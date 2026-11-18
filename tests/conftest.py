"""
Fixtures pytest pour les tests Vault Wrap Proxy.
"""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_env_defaults(monkeypatch):
    """Configure les variables d'environnement par défaut."""
    monkeypatch.setenv("VAULT_ADDR", "https://vault.test.local")
    monkeypatch.setenv("DEFAULT_WRAP_TTL", "5m")
    monkeypatch.setenv("MAX_WRAP_TTL", "24h")
    monkeypatch.setenv("MAX_REQUEST_SIZE", "1048576")


@pytest.fixture
def mock_vault_client():
    """Crée un mock du client Vault."""
    client = MagicMock()
    client.token = "test-token"
    client.is_authenticated.return_value = True
    return client


@pytest.fixture
def sample_secret():
    """Données de test standard."""
    return {
        "username": "testuser",
        "password": "testpass123",
        "api_key": "sk-test-12345",
    }


@pytest.fixture
def large_payload():
    """Payload dépassant la limite par défaut (1 MiB)."""
    # Crée un payload de ~1.5 MiB
    return {"data": "x" * (1024 * 1024 + 500000)}

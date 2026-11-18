"""
Tests d'intégration contre un Vault local (dev mode).

Ces tests nécessitent un serveur Vault en mode dev accessible.
Ils sont ignorés si Vault n'est pas disponible.

Version Vault testée : 2.2.2
Cible de compatibilité vérifiée : Vault 2.2.2

Usage:
    # Lancer Vault dev dans un terminal séparé :
    docker run --rm -d -p 8200:8200 --name vault-test hashicorp/vault:2.2.2 server -dev -dev-root-token-id=root

    # Exécuter les tests d'intégration :
    VAULT_ADDR=http://localhost:8200 VAULT_TOKEN=root pytest tests/test_integration.py -v

    # Arrêter Vault :
    docker stop vault-test
"""

import os
import time

import hvac
import pytest

# Skip tous les tests si Vault n'est pas configuré
VAULT_ADDR = os.getenv("VAULT_ADDR", "")
VAULT_TOKEN = os.getenv("VAULT_TOKEN", "")
INTEGRATION_ENABLED = bool(VAULT_ADDR and VAULT_TOKEN)

pytestmark = pytest.mark.skipif(
    not INTEGRATION_ENABLED,
    reason="Tests d'intégration désactivés. Configurez VAULT_ADDR et VAULT_TOKEN.",
)


@pytest.fixture(scope="module")
def vault_client():
    """Client Vault pour les tests d'intégration."""
    client = hvac.Client(url=VAULT_ADDR, token=VAULT_TOKEN)

    # Vérifier la connexion
    if not client.is_authenticated():
        pytest.skip("Impossible de se connecter à Vault")

    return client


@pytest.fixture
def test_client(monkeypatch):
    """Client FastAPI configuré pour Vault local."""
    monkeypatch.setenv("VAULT_ADDR", VAULT_ADDR)
    monkeypatch.setenv("VAULT_TOKEN", VAULT_TOKEN)
    monkeypatch.setenv("DEFAULT_WRAP_TTL", "5m")
    monkeypatch.setenv("MAX_WRAP_TTL", "1h")
    monkeypatch.setenv("MAX_REQUEST_SIZE", "1048576")

    # Réinitialiser le client Vault global
    import app.main as main_module
    from app.vault import VaultClientManager

    monkeypatch.setattr(
        main_module,
        "vault_manager",
        VaultClientManager(url=VAULT_ADDR, token=VAULT_TOKEN),
    )
    monkeypatch.setattr(main_module, "_default_ttl_seconds", 300)
    monkeypatch.setattr(main_module, "_max_ttl_seconds", 3600)
    monkeypatch.setattr(main_module, "VAULT_ADDR", VAULT_ADDR)
    monkeypatch.setattr(main_module, "VAULT_TOKEN", VAULT_TOKEN)
    monkeypatch.setattr(main_module, "DEFAULT_WRAP_TTL", "5m")
    monkeypatch.setattr(main_module, "MAX_WRAP_TTL", "1h")

    from fastapi.testclient import TestClient

    with TestClient(main_module.app) as client:
        yield client


class TestWrapUnwrapIntegration:
    """Tests d'intégration wrap/unwrap."""

    def test_wrap_then_unwrap_returns_exact_data(self, test_client):
        """Wrap puis unwrap retourne les données exactes."""
        original_data = {
            "username": "integration_test",
            "password": "secret_password_123",
            "nested": {"key": "value"},
            "list": [1, 2, 3],
            "unicode": "éàü中文",
        }

        # Wrap
        wrap_response = test_client.post(
            "/api/wrap", json={"data": original_data, "ttl": "5m"}
        )
        assert wrap_response.status_code == 200, f"Wrap failed: {wrap_response.text}"

        wrap_result = wrap_response.json()
        token = wrap_result["token"]
        assert token.startswith("hvs.") or token.startswith("s.")

        # Unwrap
        unwrap_response = test_client.post("/api/unwrap", json={"token": token})
        assert (
            unwrap_response.status_code == 200
        ), f"Unwrap failed: {unwrap_response.text}"

        unwrap_result = unwrap_response.json()
        assert unwrap_result["data"] == original_data

    def test_second_unwrap_fails(self, test_client):
        """Le second unwrap échoue (usage unique)."""
        # Wrap
        wrap_response = test_client.post(
            "/api/wrap", json={"data": {"secret": "one-time-only"}, "ttl": "5m"}
        )
        assert wrap_response.status_code == 200
        token = wrap_response.json()["token"]

        # Premier unwrap - succès
        first_unwrap = test_client.post("/api/unwrap", json={"token": token})
        assert first_unwrap.status_code == 200

        # Second unwrap - échec
        second_unwrap = test_client.post("/api/unwrap", json={"token": token})
        assert second_unwrap.status_code == 400
        assert "invalid" in second_unwrap.json()["detail"].lower()

    def test_invalid_token_rejected(self, test_client):
        """Token invalide est rejeté."""
        response = test_client.post(
            "/api/unwrap", json={"token": "hvs.totally_invalid_token_12345"}
        )
        assert response.status_code == 400
        assert "invalid" in response.json()["detail"].lower()

    def test_expired_token_rejected(self, test_client):
        """Token expiré est rejeté."""
        # Créer un token avec TTL très court
        wrap_response = test_client.post(
            "/api/wrap",
            json={"data": {"secret": "will-expire"}, "ttl": "1s"},  # 1 seconde
        )
        assert wrap_response.status_code == 200
        token = wrap_response.json()["token"]

        # Attendre l'expiration
        time.sleep(2)

        # Unwrap doit échouer
        unwrap_response = test_client.post("/api/unwrap", json={"token": token})
        assert unwrap_response.status_code == 400

    def test_excessive_ttl_rejected(self, test_client):
        """TTL dépassant le maximum est rejeté."""
        response = test_client.post(
            "/api/wrap",
            json={"data": {"secret": "test"}, "ttl": "48h"},  # Dépasse MAX_WRAP_TTL=1h
        )
        assert response.status_code == 400
        assert "exceeds the maximum" in response.json()["detail"]

    def test_invalid_ttl_formats_rejected(self, test_client):
        """Formats TTL invalides sont rejetés."""
        invalid_ttls = ["abc", "5x", "-10m", "0", ""]

        for ttl in invalid_ttls:
            response = test_client.post(
                "/api/wrap", json={"data": {"secret": "test"}, "ttl": ttl}
            )
            assert response.status_code == 400, f"TTL '{ttl}' aurait dû être rejeté"


class TestLookupIntegration:
    """Tests d'intégration lookup."""

    def test_lookup_valid_token(self, test_client):
        """Lookup retourne les infos d'un token valide."""
        # Wrap
        wrap_response = test_client.post(
            "/api/wrap", json={"data": {"secret": "lookup-test"}, "ttl": "5m"}
        )
        assert wrap_response.status_code == 200
        token = wrap_response.json()["token"]

        # Lookup
        lookup_response = test_client.post("/api/lookup", json={"token": token})
        assert lookup_response.status_code == 200

        lookup_result = lookup_response.json()
        assert lookup_result["creation_ttl"] == 300  # 5 minutes
        assert lookup_result["ttl"] > 0
        assert lookup_result["ttl"] <= 300

    def test_lookup_does_not_consume_token(self, test_client):
        """Lookup ne consomme pas le token."""
        # Wrap
        wrap_response = test_client.post(
            "/api/wrap", json={"data": {"secret": "lookup-preserve"}, "ttl": "5m"}
        )
        token = wrap_response.json()["token"]

        # Lookup multiple fois
        for _ in range(3):
            lookup_response = test_client.post("/api/lookup", json={"token": token})
            assert lookup_response.status_code == 200

        # Unwrap doit toujours fonctionner
        unwrap_response = test_client.post("/api/unwrap", json={"token": token})
        assert unwrap_response.status_code == 200


class TestRequestSizeIntegration:
    """Tests d'intégration limite de taille."""

    def test_large_request_rejected(self, test_client):
        """Requête dépassant la limite est rejetée."""
        # Créer un payload de ~1.5 MiB
        large_data = {"data": "x" * (1024 * 1024 + 500000)}

        response = test_client.post(
            "/api/wrap",
            json={"data": large_data, "ttl": "5m"},
            headers={"Content-Length": str(len(str(large_data)) + 1000000)},
        )

        assert response.status_code == 413

    def test_acceptable_size_accepted(self, test_client):
        """Requête de taille acceptable est acceptée."""
        # Payload de ~100 KB
        data = {"content": "x" * 100000}

        response = test_client.post("/api/wrap", json={"data": data, "ttl": "5m"})

        assert response.status_code == 200

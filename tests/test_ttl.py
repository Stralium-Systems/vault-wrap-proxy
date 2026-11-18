"""
Tests unitaires pour la validation TTL.
"""

import pytest

from app.main import parse_ttl, validate_ttl_config


class TestParseTTL:
    """Tests de la fonction parse_ttl."""

    def test_parse_seconds_numeric(self):
        """Nombre seul interprété comme secondes."""
        assert parse_ttl("300") == 300
        assert parse_ttl("1") == 1
        assert parse_ttl("86400") == 86400

    def test_parse_seconds_suffix(self):
        """Suffixe 's' pour secondes."""
        assert parse_ttl("30s") == 30
        assert parse_ttl("120s") == 120
        assert parse_ttl("30S") == 30  # Majuscule

    def test_parse_minutes(self):
        """Suffixe 'm' pour minutes."""
        assert parse_ttl("5m") == 300
        assert parse_ttl("1m") == 60
        assert parse_ttl("60m") == 3600
        assert parse_ttl("5M") == 300  # Majuscule

    def test_parse_hours(self):
        """Suffixe 'h' pour heures."""
        assert parse_ttl("1h") == 3600
        assert parse_ttl("24h") == 86400
        assert parse_ttl("72h") == 259200
        assert parse_ttl("1H") == 3600  # Majuscule

    def test_parse_days(self):
        """Suffixe 'd' pour jours."""
        assert parse_ttl("1d") == 86400
        assert parse_ttl("7d") == 604800
        assert parse_ttl("30d") == 2592000
        assert parse_ttl("1D") == 86400  # Majuscule

    def test_parse_case_insensitive(self):
        """Le parsing est insensible à la casse et gère les espaces."""
        assert parse_ttl("5M") == 300
        assert parse_ttl("1H") == 3600
        assert parse_ttl("2D") == 172800
        assert parse_ttl("  5m  ") == 300
        assert parse_ttl("10S") == 10

    def test_parse_all_documented_formats(self):
        """Tous les formats documentés dans le README sont supportés."""
        # Formats avec suffixes (documentés)
        assert parse_ttl("30s") == 30  # secondes
        assert parse_ttl("5m") == 300  # minutes
        assert parse_ttl("1h") == 3600  # heures
        assert parse_ttl("24h") == 86400  # heures
        assert parse_ttl("1d") == 86400  # jours
        assert parse_ttl("7d") == 604800  # jours
        # Nombre seul = secondes
        assert parse_ttl("300") == 300

    def test_parse_invalid_empty(self):
        """TTL vide lève une erreur."""
        with pytest.raises(ValueError, match="(empty|required)"):
            parse_ttl("")
        with pytest.raises(ValueError, match="required"):
            parse_ttl(None)

    def test_parse_invalid_format(self):
        """Format invalide lève une erreur."""
        with pytest.raises(ValueError, match="Invalid"):
            parse_ttl("abc")
        with pytest.raises(ValueError, match="Invalid"):
            parse_ttl("5x")
        with pytest.raises(ValueError, match="Invalid"):
            parse_ttl("m5")

    def test_parse_zero_rejected(self):
        """TTL zéro est rejeté."""
        with pytest.raises(ValueError, match="strictly positive"):
            parse_ttl("0")
        with pytest.raises(ValueError, match="strictly positive"):
            parse_ttl("0m")

    def test_parse_negative_rejected(self):
        """TTL négatif est rejeté."""
        with pytest.raises(ValueError, match="(strictly positive|Invalid)"):
            parse_ttl("-5m")
        with pytest.raises(ValueError, match="(strictly positive|Invalid)"):
            parse_ttl("-1")


class TestValidateTTLConfig:
    """Tests de la validation de configuration TTL au démarrage."""

    def test_valid_config(self, monkeypatch):
        """Configuration valide acceptée."""
        monkeypatch.setenv("DEFAULT_WRAP_TTL", "5m")
        monkeypatch.setenv("MAX_WRAP_TTL", "24h")

        # Recharger les variables
        import app.main as main_module

        monkeypatch.setattr(main_module, "DEFAULT_WRAP_TTL", "5m")
        monkeypatch.setattr(main_module, "MAX_WRAP_TTL", "24h")

        default_ttl, max_ttl = validate_ttl_config()
        assert default_ttl == 300  # 5 minutes
        assert max_ttl == 86400  # 24 heures

    def test_default_exceeds_max_rejected(self, monkeypatch):
        """Défaut supérieur au max est rejeté."""
        import app.main as main_module

        monkeypatch.setattr(main_module, "DEFAULT_WRAP_TTL", "48h")
        monkeypatch.setattr(main_module, "MAX_WRAP_TTL", "24h")

        with pytest.raises(ValueError, match="exceeds MAX_WRAP_TTL"):
            validate_ttl_config()

    def test_invalid_max_ttl_rejected(self, monkeypatch):
        """MAX_WRAP_TTL invalide est rejeté."""
        import app.main as main_module

        monkeypatch.setattr(main_module, "MAX_WRAP_TTL", "invalid")

        with pytest.raises(ValueError, match="MAX_WRAP_TTL is invalid"):
            validate_ttl_config()

    def test_invalid_default_ttl_rejected(self, monkeypatch):
        """DEFAULT_WRAP_TTL invalide est rejeté."""
        import app.main as main_module

        monkeypatch.setattr(main_module, "DEFAULT_WRAP_TTL", "bad")
        monkeypatch.setattr(main_module, "MAX_WRAP_TTL", "24h")

        with pytest.raises(ValueError, match="DEFAULT_WRAP_TTL is invalid"):
            validate_ttl_config()

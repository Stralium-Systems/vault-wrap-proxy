"""Language configuration, localized responses, and safe translation rendering."""

import ast
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from string import Formatter
from unittest.mock import MagicMock

import hvac
import pytest
import requests
from fastapi.testclient import TestClient

import app.i18n as i18n
import app.main as main


@pytest.fixture
def localized_client(monkeypatch):
    vault = MagicMock()
    vault.sys.wrap.return_value = {
        "wrap_info": {
            "token": "synthetic-code",
            "ttl": 30,
            "creation_time": "2026-11-18T12:00:00Z",
        }
    }
    manager = MagicMock()
    manager.perform.side_effect = lambda operation: operation(vault)
    manager.is_ready.return_value = True
    monkeypatch.setattr(main, "vault_manager", manager)
    monkeypatch.setattr(main, "DEFAULT_WRAP_TTL", "5m")
    monkeypatch.setattr(main, "MAX_WRAP_TTL", "1h")
    monkeypatch.setattr(main, "MAX_REQUEST_SIZE", 1024)

    def create(language):
        monkeypatch.setattr(main, "APP_LANGUAGE", language)
        return TestClient(main.app)

    return create, vault


@pytest.mark.parametrize("language", i18n.SUPPORTED_LANGUAGES)
def test_page_and_config_use_the_selected_language(localized_client, language):
    create, _ = localized_client
    with create(language) as client:
        page = client.get("/")
        assert f'<html lang="{language}">' in page.text
        assert html.escape(i18n.message(language, "page_title")) in page.text
        assert (
            html.escape(i18n.message(language, "default_username"), quote=True)
            in page.text
        )
        assert "__APP_" not in page.text
        assert page.headers["content-language"] == language
        assert page.headers["cache-control"] == "no-store"
        payload = re.search(
            r'id="app-translations" type="application/json">(.*?)</script>',
            page.text,
            re.S,
        )
        assert json.loads(payload[1]) == i18n.catalog(language)
        config = client.get("/api/config")
        assert config.json()["language"] == language
        assert config.headers["content-language"] == language
        assert "vault" not in json.dumps(config.json()).lower()


@pytest.mark.parametrize("language", i18n.SUPPORTED_LANGUAGES)
def test_localized_api_errors_preserve_status_codes(localized_client, language):
    create, vault = localized_client
    with create(language) as client:
        response = client.post("/api/wrap", json={"data": {}, "ttl": "bad"})
        assert response.status_code == 400
        assert response.json()["detail"] == i18n.message(
            language, "err_ttl_format", value="bad"
        )
        vault.sys.wrap.assert_not_called()
        response = client.post("/api/wrap", json={"data": {}, "ttl": "2h"})
        assert response.status_code == 400
        assert response.json()["detail"] == i18n.message(
            language,
            "err_request_ttl_limit",
            requested="2h",
            seconds=7200,
            maximum="1h",
            max_seconds=3600,
        )
        response = client.post(
            "/api/wrap", content="{}", headers={"Content-Length": "100000"}
        )
        assert response.status_code == 413
        assert response.json()["detail"] == i18n.message(
            language, "err_request_too_large", limit=1024
        )
        response = client.post(
            "/api/wrap", content="{}", headers={"Content-Length": "invalid"}
        )
        assert response.status_code == 400
        assert response.json()["detail"] == i18n.message(language, "err_content_length")
        vault.sys.unwrap.side_effect = hvac.exceptions.InvalidRequest(
            "private upstream detail"
        )
        response = client.post("/api/unwrap", json={"token": "synthetic-code"})
        assert response.status_code == 400
        assert response.json()["detail"] == i18n.message(language, "err_invalid_token")
        vault.sys.unwrap.side_effect = requests.Timeout("private upstream detail")
        response = client.post("/api/unwrap", json={"token": "synthetic-code"})
        assert response.status_code == 503
        assert response.json()["detail"] == i18n.message(
            language, "err_vault_unavailable"
        )
        assert "private upstream detail" not in response.text


@pytest.mark.parametrize("language", i18n.SUPPORTED_LANGUAGES)
@pytest.mark.parametrize(
    "data,error_type",
    [
        ({}, "missing"),
        ({"data": []}, "dict_type"),
        ({"data": {}, "ttl": 3}, "string_type"),
    ],
)
def test_request_validation_is_localized(localized_client, language, data, error_type):
    create, vault = localized_client
    with create(language) as client:
        response = client.post("/api/wrap", json=data)
        assert response.status_code == 422
        error = response.json()["detail"][0]
        assert error["type"] == error_type
        assert error["msg"] == i18n.message(language, "validation_" + error_type)
        vault.sys.wrap.assert_not_called()


@pytest.mark.parametrize("language", i18n.SUPPORTED_LANGUAGES)
def test_language_does_not_translate_secret_data(localized_client, language):
    create, vault = localized_client
    data = {"original key": "Identifiant contraseña é中文 <&>", "nested": ["hello", 1]}
    with create(language) as client:
        response = client.post("/api/wrap", json={"data": data, "ttl": "30s"})
        assert response.status_code == 200
        vault.sys.wrap.assert_called_once_with(payload=data, ttl=30)


@pytest.mark.parametrize("language", i18n.SUPPORTED_LANGUAGES)
def test_malformed_json_error_is_localized(localized_client, language):
    create, vault = localized_client
    with create(language) as client:
        response = client.post(
            "/api/wrap", content="{", headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422
        assert response.json()["detail"][0]["msg"] == i18n.message(
            language, "validation_json_invalid"
        )
        vault.sys.wrap.assert_not_called()


def test_default_language_is_english_and_invalid_configuration_fails():
    env = dict(os.environ)
    env.pop("APP_LANGUAGE", None)
    command = [
        sys.executable,
        "-c",
        "from app.main import APP_LANGUAGE; print(APP_LANGUAGE)",
    ]
    result = subprocess.run(
        command, env=env, text=True, capture_output=True, check=True
    )
    assert result.stdout.strip() == "en"
    for invalid in ("de", "../../secret", ""):
        result = subprocess.run(
            command,
            env={**env, "APP_LANGUAGE": invalid},
            text=True,
            capture_output=True,
        )
        assert result.returncode != 0
        assert "APP_LANGUAGE must be one of: en, fr, es" in result.stderr
    assert i18n.normalize_language(" FR ") == "fr"


def test_catalogs_cover_all_messages_and_keep_format_placeholders():
    english = i18n.catalog("en")
    root = Path(__file__).resolve().parents[1]
    sources = "\n".join(
        (root / p).read_text()
        for p in ("app/main.py", "app/middleware.py", "app/static/index.html")
    )
    keys = set(re.findall(r"\bt\(\s*[\"\x27]([a-z_]+)[\"\x27]", sources))
    for filename in ("app/main.py", "app/middleware.py"):
        for node in ast.walk(ast.parse((root / filename).read_text())):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            index = {"translate": 0, "translate_message": 1}.get(node.func.id)
            if (
                index is not None
                and len(node.args) > index
                and isinstance(node.args[index], ast.Constant)
            ):
                keys.add(node.args[index].value)
    keys |= set(
        re.findall(r'data-i18n(?:-title|-placeholder|-value)?="([a-z_]+)"', sources)
    )
    keys.discard("duration_")
    assert keys <= english.keys(), keys - english.keys()
    formatter = Formatter()
    for language in i18n.SUPPORTED_LANGUAGES:
        messages = i18n.catalog(language)
        assert messages.keys() == english.keys()
        assert all(isinstance(value, str) and value for value in messages.values())
        for key in english:
            if key == "json_placeholder":
                continue

            def fields(text):
                return {
                    field
                    for _, field, _, _ in formatter.parse(text)
                    if field is not None
                }

            assert fields(messages[key]) == fields(english[key]), (language, key)


def test_translation_payload_cannot_escape_its_html_context(monkeypatch):
    messages = dict(i18n.catalog("en"))
    marker = '</script><script>window.injected=1</script><img src=x onerror="alert(1)">'
    messages["wrap_intro"] = marker
    messages["site_title"] = marker
    monkeypatch.setattr(i18n, "catalog", lambda language: messages)
    rendered = i18n.render_page(main.HTML_TEMPLATE, "en")
    assert marker not in rendered
    assert html.escape(marker) in rendered
    payload = re.search(
        r'id="app-translations" type="application/json">(.*?)</script>', rendered, re.S
    )
    assert json.loads(payload[1])["wrap_intro"] == marker

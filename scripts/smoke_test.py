"""Exercise a running instance using fictitious data only."""

import json
import os
import urllib.error
import urllib.request

BASE_URL = os.environ.get("PROXY_URL", "http://127.0.0.1:8080").rstrip("/")


def request(path, data=None):
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(
        BASE_URL + path, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)


def main():
    request("/health")
    request("/ready")
    config = request("/api/config")
    language = config["language"]
    assert language in ("en", "fr", "es")
    if os.environ.get("EXPECTED_LANGUAGE"):
        assert language == os.environ["EXPECTED_LANGUAGE"]
    with urllib.request.urlopen(BASE_URL + "/", timeout=10) as response:
        page = response.read().decode("utf-8")
        assert response.headers["Content-Language"] == language
        assert f'<html lang="{language}">' in page
        assert "__APP_" not in page
    assert config["default_wrap_ttl_seconds"] > 0
    data = {"example": "fictitious-only", "unicode": "é中文", "nested": [1, True]}
    wrapped = request("/api/wrap", {"data": data, "ttl": "30s"})
    token = wrapped["token"]
    assert wrapped["ttl"] == 30
    assert request("/api/lookup", {"token": token})["creation_ttl"] == 30
    assert request("/api/unwrap", {"token": token})["data"] == data
    try:
        request("/api/unwrap", {"token": token})
    except urllib.error.HTTPError as error:
        assert error.code == 400, error.code
    else:
        raise AssertionError("Wrapping token was reusable")
    print(
        f"Smoke test passed ({language}): readiness, config, wrap, lookup, unwrap and single use"
    )


if __name__ == "__main__":
    main()

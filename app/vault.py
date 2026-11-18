"""Thread-local Vault clients and coordinated Kubernetes authentication."""

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import hvac
import requests
from requests.adapters import HTTPAdapter

T = TypeVar("T")


class VaultUnavailable(RuntimeError):
    """Vault service authentication is not configured or cannot be established."""


class VaultClientManager:
    """Share credentials, never a mutable HTTP client, across worker threads.

    Kubernetes credentials are refreshed before their known lease expires.
    A definitive HTTP 403 may be retried once, but only after verifying that
    the service token is invalid. Timeouts and other ambiguous failures are
    never replayed: an unwrap may already have consumed the wrapping token.
    """

    def __init__(
        self,
        url: str,
        token: str | None = None,
        role: str | None = None,
        namespace: str = "",
        timeout: int = 10,
        auth_mount: str = "kubernetes",
        jwt_path: str = "/var/run/secrets/kubernetes.io/serviceaccount/token",
    ) -> None:
        self.url = url
        self.static_token = token
        self.role = role
        self.namespace = namespace
        self.timeout = timeout
        self.auth_mount = auth_mount
        self.jwt_path = Path(jwt_path)
        self._local = threading.local()
        self._lock = threading.Lock()
        self._token: str | None = None
        self._refresh_at = 0.0
        self._clients: list[hvac.Client] = []

    def _new_client(self, token: str | None = None) -> hvac.Client:
        session = requests.Session()
        # No transport retries, including POSTs. A lost unwrap response must
        # not cause a second, automatic consumption attempt.
        session.mount("https://", HTTPAdapter(max_retries=0))
        session.mount("http://", HTTPAdapter(max_retries=0))
        return hvac.Client(
            url=self.url,
            token=token,
            namespace=self.namespace,
            session=session,
            timeout=self.timeout,
        )

    def _service_token(self) -> str:
        if self.static_token:
            return self.static_token
        if not self.role:
            raise VaultUnavailable("Configure VAULT_TOKEN or VAULT_ROLE")

        with self._lock:
            if self._token and time.monotonic() < self._refresh_at:
                return self._token
            client = self._new_client()
            try:
                jwt = self.jwt_path.read_text(encoding="utf-8").strip()
                result = client.auth.kubernetes.login(
                    role=self.role, jwt=jwt, mount_point=self.auth_mount
                )
                auth = result["auth"]
                token = auth["client_token"]
                lease = int(auth.get("lease_duration", 0))
                if not isinstance(token, str) or not token or lease < 0:
                    raise VaultUnavailable("Invalid Vault authentication response")
            except (OSError, KeyError, TypeError, ValueError) as exc:
                raise VaultUnavailable("Cannot establish Vault authentication") from exc
            finally:
                client.adapter.session.close()

            self._token = token
            self._refresh_at = (
                time.monotonic() + lease - min(30, lease / 10)
                if lease
                else float("inf")
            )
            return token

    def get_client(self) -> hvac.Client:
        token = self._service_token()
        client = getattr(self._local, "client", None)
        if client is None:
            client = self._new_client(token)
            self._local.client = client
            with self._lock:
                self._clients.append(client)
        else:
            client.token = token
        return client

    def _invalidate(self, expected_token: str) -> None:
        with self._lock:
            # Another thread may already have refreshed the same credential.
            if self._token == expected_token:
                self._token = None
                self._refresh_at = 0

    def perform(self, operation: Callable[[hvac.Client], T]) -> T:
        client = self.get_client()
        try:
            return operation(client)
        except hvac.exceptions.Forbidden:
            if self.static_token or not self.role or client.is_authenticated():
                raise
            self._invalidate(client.token)
            client = self.get_client()
            # Exactly one retry after an explicit authentication rejection.
            return operation(client)

    def is_ready(self) -> bool:
        try:
            self.perform(lambda client: client.auth.token.lookup_self())
        except (
            hvac.exceptions.VaultError,
            requests.RequestException,
            VaultUnavailable,
        ):
            return False
        return True

    def close(self) -> None:
        with self._lock:
            clients, self._clients = self._clients, []
        for client in clients:
            client.adapter.session.close()

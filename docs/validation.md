# Validation

## Toolchain

| Component | Version |
| --- | --- |
| Application | 1.0.0 |
| Python / Docker base | 3.15.2 / slim Trixie, pinned digest |
| Vault integration / Compose image | 2.2.2, pinned digest |
| Node.js / jsdom | 26.13.1 LTS / 31.0.1 |
| Terraform / Vault provider | 1.17.2 / 5.13.0 |
| Helm | 4.3.2 |
| Trivy / Trivy Action | 0.76.2 / 0.36.0 |
| checkout / setup-python / setup-node | 7.0.1 / 7.1.0 / 7.1.0, pinned commit SHAs |

Direct and transitive Python dependencies are hash-locked in `requirements.txt` and `requirements-dev.txt`; npm dependencies are locked in `package-lock.json`. The checked-in requirements input files record the direct pins.

The container uses a separate dependency stage and a runtime venv without pip. The runtime stage applies available Debian package fixes and removes ensurepip. This addresses the first scan's findings in zlib and pip's vendored dependencies, while preserving the application dependency lock.

## Checks

The test suite covers Python unit/regression tests, 10 integrations against a disposable real Vault 2.2.2, jsdom UI tests, Black, Ruff, dependency audits and infrastructure validation. English, French and Spanish are checked for configuration, user-facing errors, rendering and preservation of secret data. Tests use fictitious data only.

The current [GitHub Actions run](https://github.com/Stralium-Systems/vault-wrap-proxy/actions/workflows/test.yml) is the authoritative record for the exact commit under review. In addition to these checks, CI runs full Terraform validation, builds and starts the Docker Compose stack, executes `scripts/smoke_test.py` over HTTP and scans the built image. Trivy fails on fixable HIGH/CRITICAL vulnerabilities; this does not establish the absence of all vulnerabilities.

CI also rebuilds the dependency stage without cache using an optional `build_ca` secret containing the runner's public CA bundle. This exercises the custom-bundle build path with public CAs. Proxy connectivity and trust in private certificate chains require validation in the target build environment.

The container job also checks that fictitious local configuration and certificate files are excluded from the Docker build context while application source and the runtime dependency lock remain available. Full Terraform validation and Docker execution run on GitHub-hosted runners.

No production Vault, live Kubernetes cluster, or external infrastructure is modified by these checks. Kubernetes authentication lifecycle is covered by controlled test doubles. Live Kubernetes Auth, private CA chains, gateway access controls and Vault Enterprise namespaces remain environment-specific acceptance checks.

## Main regression coverage

- English is selected by default; French and Spanish work through runtime and Helm configuration.
- Translation catalogs contain the same keys and interpolation fields; text cannot inject executable markup.
- Localized dates, durations and dynamic messages preserve the original secret content.
- CI runs real HTTP sharing against the image in all three languages.


- Oversized streamed bodies are rejected without relying on Content-Length or calling Vault.
- Bodies exactly at the limit are accepted; raw UTF-8 and nested JSON are preserved.
- Quoted field names/values remain data, without injected attributes or handlers.
- Expired service credentials trigger coordinated reauthentication without the previous five-minute failure window.
- Invalid wrapping tokens and ambiguous network failures do not cause blind unwrap retries.
- Clients are thread-local, and slow Vault requests do not block process liveness.
- Lookup forwards the configured namespace through the shared Vault adapter.
- Readiness returns 503 independently of liveness when authenticated Vault access fails.
- The UI follows configured TTL defaults and limits.

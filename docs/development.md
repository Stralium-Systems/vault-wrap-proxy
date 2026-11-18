# Development

[Back to the README](../README.md)

Use Python **3.15.2** (`.python-version`) and Node.js **26.13.1 LTS** (`.node-version`, UI tests only). The Docker base is Python 3.15.2 slim Trixie, and the Vault test fixture is 2.2.2. Both images are pinned by digest. Terraform **1.17.2**, Vault provider **5.13.0** and Helm **4.3.2** are the infrastructure toolchain.

```bash
python3.15 -m venv .venv
. .venv/bin/activate
python -m pip install --require-hashes -r requirements-dev.txt
docker compose up --detach --wait vault

export VAULT_ADDR=http://127.0.0.1:8200
export VAULT_TOKEN=root
uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

Stop the disposable Vault with `docker compose down`.

## Tests and checks

```bash
pytest tests/ --ignore=tests/test_integration.py -v
black --check app/ tests/ scripts/
ruff check app/ tests/ scripts/
npm ci --ignore-scripts
npm test

# With the local development Vault running:
VAULT_ADDR=http://127.0.0.1:8200 VAULT_TOKEN=root \
  pytest tests/test_integration.py -v
```

CI runs Python 3.15 unit/regression tests, real Vault 2.2.2 integration tests, lint, Python/npm vulnerability audits, Node 26 DOM tests, Terraform validation and Helm lint/rendering. It also builds and starts the Docker Compose stack, runs the HTTP smoke test and scans the resulting image with Trivy. The image scan fails on fixable HIGH/CRITICAL findings; unfixed findings and lower severities are outside that gate. Kubernetes authentication lifecycle is covered with controlled test doubles; a live cluster and Vault Enterprise namespaces are not exercised by this suite.

## Dependency maintenance

Direct Python versions are declared in `requirements.in` and `requirements-dev.in`; the corresponding `.txt` files lock all dependencies with hashes. Regenerate both together with uv:

```bash
uv pip compile requirements.in --python-version 3.15 --universal --generate-hashes --no-annotate --upgrade --output-file requirements.txt
uv pip compile requirements-dev.in --python-version 3.15 --universal --generate-hashes --no-annotate --upgrade --output-file requirements-dev.txt
```

Update the direct pins in `.in` first. Commit both lock files and run the full checks. `npm ci` consumes the committed npm lock. GitHub Actions are pinned to commit SHAs. Dependabot checks Python, npm, Docker, Compose, GitHub Actions and the Terraform provider weekly. Review the CLI version files and Vault service image in CI alongside those proposals; they are explicit pins, not automatically rolling tags.

The application image is built locally or in CI; this repository does not yet publish it to a registry. Its final stage applies available Debian updates and contains the locked application venv without pip or ensurepip. Debian package updates are resolved at build time. Rebuild and scan before publishing, then use Helm's `image.digest` to deploy your published immutable image.

## Release tags

The **Create release tag** GitHub Actions workflow is manually triggered on `main`. Provide the requested tag, such as `v1.0.0`, and the full target commit SHA. The workflow checks that the commit belongs to `main`, that the tag matches the chart's `appVersion`, and that the latest push-triggered Tests workflow for the commit succeeded. Existing tags are never moved to another commit.

The application and Helm chart both start at `1.0.0` for this release. Their version numbers can evolve independently in future releases. Container images are built and published through your own registry workflow.

See [CONTRIBUTING.md](../CONTRIBUTING.md), the [validation scope](validation.md) and the [changelog](../CHANGELOG.md).

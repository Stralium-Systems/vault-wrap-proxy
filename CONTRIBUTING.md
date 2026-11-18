# Contributing

Please open an issue describing the problem, expected behavior and a minimal reproduction using fictitious data. Include relevant application and Vault versions. Never attach real secrets, wrapping tokens, service tokens, or private infrastructure details.

## Development

Use Python 3.15.2 and Node.js 26.13.1 for DOM tests. Follow the [development setup](docs/development.md), then run:

```bash
python -m pip install --require-hashes -r requirements-dev.txt
pytest tests/ --ignore=tests/test_integration.py -v
black app/ tests/ scripts/
ruff check app/ tests/ scripts/
npm ci --ignore-scripts
npm test
```

Run integration tests against the disposable Vault 2.2.2 described in the [development guide](docs/development.md). Use a dedicated local development instance, never production credentials.

Add regression tests for behavior changes. In particular, preserve one-time consumption, bounded request buffering, the distinction between service authentication and wrapping tokens, and the absence of automatic retries after ambiguous unwrap failures.

Open a pull request with the concrete behavior change and the checks actually executed. Changes are covered by the project's Apache 2.0 license.

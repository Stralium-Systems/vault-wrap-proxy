# Vault Wrap Proxy

[![Tests](https://github.com/Stralium-Systems/vault-wrap-proxy/actions/workflows/test.yml/badge.svg)](https://github.com/Stralium-Systems/vault-wrap-proxy/actions/workflows/test.yml)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

Share a password or a JSON object with a code that expires and can be opened **once**. Vault Wrap Proxy provides a web interface and an API backed by HashiCorp Vault. Recipients do not need a Vault account.

## Share a secret

If your team already runs an instance, open its URL and use the three tabs:

| Tab | What to do |
| --- | --- |
| **Protect** — share | Enter your fields or JSON, choose a lifetime, then click **Generate secret code**. |
| **Check** — check | Check a code's remaining lifetime without opening the secret. |
| **Reveal** — open | Paste the received code and click **Reveal information**. This consumes the code. |

Send the recipient **the application's URL and the generated code**, using a private channel. Anyone holding the code can open the secret. To check a code before sending it, use **Check**; **Reveal** consumes it.

See the [usage guide](docs/usage.md) for examples, API commands and common questions.

## Try it locally

Requirements: Git and Docker Engine with the Docker Compose v2 plugin.

```bash
git clone https://github.com/Stralium-Systems/vault-wrap-proxy.git
cd vault-wrap-proxy
docker compose up --build --detach --wait
```

Open **http://127.0.0.1:8080** and try sharing fictitious data between two browser tabs. To share with another person, use a deployed instance they can reach; `127.0.0.1` refers to each person's own machine.

The demo starts its own Vault in development mode, uses a fixed test token and binds both services to loopback. Stopping Vault removes the demo shares.

Optional automatic check, with Python 3:

```bash
python3 scripts/smoke_test.py
```

Stop the demo:

```bash
docker compose down
```

Build blocked by a proxy or certificate error? See [build troubleshooting](docs/deployment.md#build-behind-an-https-inspection-proxy).

## Language

English is the default. Set `APP_LANGUAGE=fr` for French or `APP_LANGUAGE=es` for Spanish. With Helm, set `app.language` instead. See [language configuration](docs/configuration.md#language) for examples.

## Deploy and configure

For an existing Vault and Kubernetes cluster, follow the [deployment guide](docs/deployment.md). You supply the Vault connection, authentication role and your published container image. Environment-specific configuration stays in your deployment repositories.

| I want to… | Guide |
| --- | --- |
| Share, receive or check a secret; call the API | [Usage](docs/usage.md) |
| Deploy against an existing Vault | [Deployment](docs/deployment.md) |
| Change TTLs, authentication or request limits | [Configuration](docs/configuration.md) |
| Run, test or contribute to the code | [Development](docs/development.md) |
| Review test coverage and its limits | [Validation](docs/validation.md) |
| Review version changes | [Changelog](CHANGELOG.md) |

## How secrets are handled

The proxy processes secrets in memory; Vault stores the shares and enforces expiry and one-time retrieval. The proxy does not read existing Vault KV secrets. This is not end-to-end encryption between browsers.

Hosted instances need HTTPS and controlled access. The application has no built-in user login; access controls belong at the deployment gateway. See the [trust model](docs/configuration.md#trust-model).

[Contributing](CONTRIBUTING.md) · [Apache License 2.0](LICENSE)

A project by **Stralium Systems** · [stralium-system.fr](https://stralium-system.fr) · [Source code on GitHub](https://github.com/Stralium-Systems/vault-wrap-proxy)

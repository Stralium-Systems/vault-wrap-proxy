# Configuration

[Back to the README](../README.md)

The application reads these environment variables at startup. In Kubernetes, the Helm chart sets them from its `app` and `vault` values. See [deployment](deployment.md) for an installation example.

| Variable | Default | Purpose |
| --- | --- | --- |
| APP_LANGUAGE | en | Interface and user-facing error language: `en`, `fr` or `es` |
| VAULT_ADDR | https://vault.example.com | Vault server URL |
| VAULT_TOKEN | unset | Static Vault token, for local development/test |
| VAULT_ROLE | unset | Kubernetes Auth role for deployment |
| VAULT_AUTH_MOUNT | kubernetes | Kubernetes Auth mount path, matching Terraform |
| VAULT_NAMESPACE | empty | Vault Enterprise namespace, forwarded for every operation |
| VAULT_TIMEOUT | 10 | Positive HTTP timeout, seconds |
| DEFAULT_WRAP_TTL | 5m | Default token lifetime, positive and at most MAX_WRAP_TTL |
| MAX_WRAP_TTL | 24h | Maximum token lifetime, enforced by the API |
| MAX_REQUEST_SIZE | 1048576 | Positive maximum HTTP request body size, bytes |

TTL accepts a positive integer in seconds or an integer with `s`, `m`, `h`, or `d`, ignoring case. Durations are normalized to seconds before being sent to Vault. Startup rejects invalid limits. The UI reads the configured default and maximum from `/api/config`.

The request size limit checks both Content-Length and the actual bytes read, including streamed/chunked requests. It bounds buffering before JSON validation and before contacting Vault. Vault can impose a smaller storage limit of its own.

`VAULT_NAMESPACE` selects an internal Vault Enterprise namespace. Leave it empty with Vault Community or when using Vault's root namespace. It is independent of the Kubernetes namespace containing the proxy pod.

For Helm, the corresponding keys include `vault.address`, `vault.role`, `vault.authMount`, `vault.namespace`, `vault.defaultTtl`, `vault.maxTtl`, `vault.maxRequestSize` and `vault.timeout`. The complete deployment options are in [values.yaml](../helm/vault-wrap-proxy/values.yaml).

## Language

`APP_LANGUAGE` selects the language for all visitors: English (`en`, default), French (`fr`) or Spanish (`es`). Static labels, dynamic messages, field placeholders, dates, durations and user-facing API errors follow this setting. User-supplied secret keys and values retain their original content. API field names, schema documentation and operational logs remain in English.

For the local Docker Compose demonstration:

```bash
APP_LANGUAGE=fr docker compose up --build --detach --wait
```

For a Kubernetes deployment, set the Helm value:

```yaml
app:
  language: es
```

Or add `--set app.language=es` to your Helm command. An existing values file that omits this setting uses English. Unsupported language codes are rejected during application startup and Helm validation. Restart the application and reload open pages after changing the configured language.

## Authentication and concurrency

In Kubernetes, the mounted ServiceAccount JWT is exchanged for a Vault token using the configured auth mount and role. The JWT is read again on subsequent logins. A shared lock coordinates authentication, while every worker thread uses its own HTTP client/session. Synchronous Vault operations run in FastAPI's worker thread pool, outside the asynchronous event loop.

The service reauthenticates before a known token lease expires. An explicit HTTP 403 is retried once only if a lookup confirms that the service token is invalid. A user's invalid wrapping token does not trigger a service login.

Timeouts, connection errors, and other ambiguous failures are never automatically replayed. In particular, an unwrap may have consumed its token even if the response was lost. Static development tokens cannot be automatically refreshed.

## Trust model

- Users supply the data. The proxy does not read existing Vault KV secrets.
- The proxy sees secrets and wrapping tokens in memory during transit. It does not persist them.
- Vault stores the wrapped response and enforces expiry and one-time consumption. This is not end-to-end encryption between browsers.
- Anyone holding a wrapping token can retrieve its contents before another party consumes it or it expires. Choose an appropriate delivery channel.
- No user login is implemented. Deploy on a controlled private network, or provide access controls at your gateway. Publishing the code does not require exposing an instance to the internet.
- Use HTTPS for production traffic to the proxy and Vault. Configure access logs, tracing and gateways to avoid capturing secret bodies or tokens.

The application logs failure categories without including request data, wrapping tokens, or raw upstream exception messages.

## Runtime certificate trust

A build-time `build_ca` secret only helps install dependencies during the image build. Provide runtime trust separately if the target Vault uses a private CA. Mount the approved CA bundle and configure the HTTP client's trust settings in your deployment. The current chart does not expose arbitrary extra environment variables or volume mounts; adapt your deployment templates for those mounts when needed. Keep certificate verification enabled.

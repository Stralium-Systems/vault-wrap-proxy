# Usage

[Back to the README](../README.md)

Open the URL supplied by the person operating your instance. The local demonstration uses `http://127.0.0.1:8080`. Both sender and recipient use the same instance. Separate proxy deployments can also interoperate when configured to use the same Vault cluster and namespace.

The instance uses English by default. Its operator can configure French or Spanish. No personal Vault account is required.

| Action | English (`en`) | Français (`fr`) | Español (`es`) |
| --- | --- | --- | --- |
| Share | Protect | Protéger | Proteger |
| Inspect | Check | Vérifier | Comprobar |
| Open | Reveal | Révéler | Revelar |
| Generate | Generate secret code | Générer le code secret | Generar código secreto |
| Copy | Copy the code | Copier le code | Copiar el código |
| Retrieve | Reveal information | Révéler les informations | Revelar información |

## Send a secret

1. Open **Protect**.
2. In **Fields**, enter a field name and its value. Use **Add a field** for additional fields. Alternatively, select **JSON** and paste a JSON object.
3. Choose the code's lifetime. The default is five minutes; available lifetimes depend on the instance's configuration.
4. Click **Generate secret code**, then **Copy the code**.
5. Send the application's URL and the code privately to the intended recipient.

Example JSON for a demonstration:

```json
{"username":"demo","password":"example-only"}
```

Use **Check** if you want to check a code before sending it. Opening it with **Reveal** consumes it, including when the sender opens it themselves.

## Receive a secret

1. Open the same application's URL and select **Reveal**.
2. Paste the code into **Received secret code**.
3. Click **Reveal information**.
4. Copy the information you need before leaving or refreshing the page. Use **Fields** or **JSON** to change its presentation.

After retrieval, the code cannot reveal the secret again. If another recipient also needs it, the sender must create a new share.

## Check a code

1. Open **Check**.
2. Paste the code and click **Check the code**.

This displays its metadata and remaining lifetime without revealing the secret or consuming the code. An expired or already consumed code is rejected.

## Call the API

The following example uses `curl` and `jq`, and only fictitious data. Replace `BASE_URL` with your instance's HTTPS URL when using a deployed instance.

```bash
set -euo pipefail
BASE_URL=http://127.0.0.1:8080

# Create a share and capture the generated code.
TOKEN="$(curl --fail --silent --show-error "$BASE_URL/api/wrap" \
  -H 'Content-Type: application/json' \
  --data '{"data":{"username":"demo","password":"example-only"},"ttl":"5m"}' \
  | jq -er '.token')"

# Inspect it without consuming it.
printf '{"token":"%s"}' "$TOKEN" \
  | curl --fail --silent --show-error "$BASE_URL/api/lookup" \
      -H 'Content-Type: application/json' --data-binary @-

# Retrieve it once.
printf '{"token":"%s"}' "$TOKEN" \
  | curl --fail --silent --show-error "$BASE_URL/api/unwrap" \
      -H 'Content-Type: application/json' --data-binary @-

unset TOKEN
```

A second unwrap of the same code returns HTTP 400. Use a JSON object for `data`; the top-level value cannot be a list or a plain string. TTL accepts seconds or a duration such as `5m`, subject to the configured maximum.

| Endpoint | Purpose |
| --- | --- |
| `POST /api/wrap` | Create a share |
| `POST /api/lookup` | Check a code without consuming it |
| `POST /api/unwrap` | Reveal and consume a code |
| `GET /api/config` | Read the UI limits |
| `GET /health` | Check that the proxy process is running |
| `GET /ready` | Check authenticated access to Vault |
| `GET /` | Open the web interface |

Interactive API documentation is available at `/docs` and `/redoc` on your instance. API responses use `Cache-Control: no-store`.

## Common questions

**Can I open the same code twice?** No. Create a new share for another retrieval. A lookup in **Check** does not count as retrieval.

**Can I recover an expired or consumed share?** No. Ask the sender to create a new one.

**What if opening the share times out?** It may already have been consumed even if the response was lost. The service does not automatically replay an ambiguous unwrap. Ask the sender for a new share if necessary.

**Who can open a code?** Anyone who possesses it and can reach the instance, until expiry or first retrieval. Use a private delivery channel.

**Does this share an existing Vault secret?** Users supply the data to share. The proxy does not read existing KV secrets.

| Problem | Next step |
| --- | --- |
| Invalid, expired or already used code — HTTP 400 | Confirm the full code and ask the sender for a new share if needed. |
| TTL rejected — HTTP 400 | Choose a lifetime within the instance's configured maximum. |
| Request too large — HTTP 413 | Reduce the JSON payload or contact the operator about the limit. |
| Invalid request — HTTP 422 | Check the JSON shape and required fields. |
| Service unavailable — HTTP 503 | Ask the operator to check `/ready` and the Vault connection. |

For instance settings, see [configuration](configuration.md). For operator diagnostics, see [deployment](deployment.md#troubleshooting).

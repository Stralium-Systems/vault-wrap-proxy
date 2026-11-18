# Deployment

[Back to the README](../README.md)

Use this guide to connect the proxy to an existing Vault and Kubernetes cluster. For a disposable local demonstration, use the [README quick start](../README.md#try-it-locally).

## Prerequisites

- An existing Vault reachable from the application pods over HTTPS.
- A Vault certificate trusted by the container; see [runtime certificate trust](configuration.md#runtime-certificate-trust) for private CAs.
- A Kubernetes Auth mount configured for the target cluster.
- Permission to provision the application's Vault policy and role, and deploy its Kubernetes resources.
- A container registry you can push to and the cluster can pull from.
- Docker, Terraform if using the example, Helm and kubectl.

## Deployment configuration boundary

This repository provides the reusable application, container build, Helm chart and an optional Terraform example for Vault permissions. Supply the target Vault address, auth mount, role, Kubernetes namespace, registry image and ingress settings through your deployment configuration.

Keep environment values, infrastructure state, credentials, private certificates and network configuration in your own deployment repositories. The Vault policy and role can be managed by your existing access-management project; assign each resource to one Terraform state. The application and chart use the resulting role and ServiceAccount references.

For local overrides, use `.local/`, `*.local.yaml`, `*.local.yml` or `compose.override.yaml`. These files, Terraform variable/state files and certificate files are excluded by `.gitignore`. The Docker build context is restricted to the Dockerfile, runtime dependency lock and application source, keeping local deployment files outside the context sent to the builder.

## Install

Configure the existing Vault Kubernetes Auth backend for your cluster first. Vault needs network access to the Kubernetes API and an identity permitted to validate ServiceAccount tokens with TokenReview.

If another infrastructure project already manages the policy and role, keep that ownership and skip the Terraform commands below. Otherwise, set `VAULT_ADDR` and supply the Vault Terraform provider's operator credentials through your approved environment, then apply the generic example:

```bash
cd terraform
terraform init
terraform apply
cd ..
```

Build the application image and push it to your own registry. Replace `YOUR_REGISTRY` and `vault.example.com` with your deployment values before running these commands:

```bash
docker build -t YOUR_REGISTRY/vault-wrap-proxy:1.0.0 .
docker push YOUR_REGISTRY/vault-wrap-proxy:1.0.0

helm upgrade --install vault-wrap-proxy ./helm/vault-wrap-proxy \
  --namespace vault-wrap-proxy --create-namespace \
  --set image.repository=YOUR_REGISTRY/vault-wrap-proxy \
  --set image.tag=1.0.0 \
  --set vault.address=https://vault.example.com:8200 \
  --set vault.role=vault-wrap-proxy \
  --set vault.authMount=kubernetes
```

The ServiceAccount name, namespace and auth mount must match Terraform. Add `--set app.language=fr` or `--set app.language=es` to choose a language; English is the default. The chart uses `/health` for liveness and `/ready` for readiness. Ingress is disabled by default; configure the class, TLS and access controls for the maintained controller used by your cluster.

Required policy, in addition to the default token self-lookup policy:

```hcl
path "sys/wrapping/wrap"   { capabilities = ["update"] }
path "sys/wrapping/unwrap" { capabilities = ["update"] }
path "sys/wrapping/lookup" { capabilities = ["update"] }
```

The default policy must allow `read` on `auth/token/lookup-self` for authenticated readiness and service-token validation. If your default policy differs, include that permission in the dedicated application policy. No KV or unused rewrap permissions are required.

## Rate limiting

Rate limiting is an infrastructure responsibility. Configure request frequency, connection limits, and maximum request size in your maintained gateway or ingress controller. Validate how the component obtains the client IP and trusts forwarded headers.

An in-memory limiter usually applies per gateway/sidecar instance. A strict shared quota across replicas needs a distributed rate-limit service or an equivalent shared facility. Neither application replication nor moving a local limiter to the ingress automatically creates a global quota.

## Verify the deployment

From the repository root, with the intended kubectl context selected:

```bash
kubectl -n vault-wrap-proxy rollout status deployment/vault-wrap-proxy
kubectl -n vault-wrap-proxy port-forward --address 127.0.0.1 service/vault-wrap-proxy 18080:80
```

Keep that terminal open. In a second terminal, from the repository root:

```bash
curl --fail http://127.0.0.1:18080/ready
PROXY_URL=http://127.0.0.1:18080 python3 scripts/smoke_test.py
```

The smoke test uses fictitious data and checks readiness, wrapping, lookup, exact recovery and rejection of a second retrieval. Open `http://127.0.0.1:18080` to try the interface. Adjust names and namespace if your release uses different values.

Configure your maintained ingress controller, DNS, HTTPS certificate and access controls to make a hosted instance available to its intended users. The chart creates an Ingress only when enabled; the controller and certificate infrastructure are environment prerequisites.

## Build behind an HTTPS inspection proxy

When your network uses an HTTPS inspection proxy, the build may need both the proxy connection settings and its trusted CA chain. A working host `curl` does not install the host's trusted CA certificates in the build image.

Supply a trusted PEM CA bundle as the optional BuildKit secret `build_ca`. On Ubuntu/WSL, the system bundle is usually `/etc/ssl/certs/ca-certificates.crt`; use the bundle configured for your host if it differs. It must contain the approved corporate CA chain. No certificate or proxy address belongs in this repository.

```bash
docker build \
  --build-arg HTTP_PROXY="${HTTP_PROXY:-${http_proxy:-}}" \
  --build-arg HTTPS_PROXY="${HTTPS_PROXY:-${https_proxy:-}}" \
  --build-arg NO_PROXY="${NO_PROXY:-${no_proxy:-}}" \
  --secret id=build_ca,src=/etc/ssl/certs/ca-certificates.crt \
  --tag vault-wrap-proxy:1.0.0 .

docker compose up --detach --wait --no-build
python3 scripts/smoke_test.py
```

For a Docker Engine running directly in WSL, add `--network=host` to the build if the proxy listens on that same host's loopback interface. This changes the build network only. BuildKit uses the CA bundle temporarily through `PIP_CERT` for dependency installation, retaining TLS verification and hash checks. The bundle and proxy settings are not installed in the runtime image. Configure runtime Vault trust separately when using a private CA.

The default build does not require this secret. To retest a changed CA bundle with BuildKit, use `--no-cache-filter dependencies`; secret content changes alone do not invalidate the build cache.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| DNS errors or connection timeouts during a build | Verify the build environment's DNS, network path and required proxy configuration. |
| Certificate verification fails during dependency installation | Supply the approved PEM bundle as the optional `build_ca` secret above. |
| `/health` works but `/ready` returns 503 | Check the Vault URL, network access, TLS trust, auth mount, role and ServiceAccount binding. |
| Vault Kubernetes login fails | Check the bound ServiceAccount name and namespace, token audience, and the identity Vault uses for TokenReview. An unset explicit reviewer JWT alone does not establish that the application's ServiceAccount needs reviewer permissions. |
| Pod cannot pull the image | Check the repository, tag or digest and the cluster's registry access. |
| Local demo cannot bind port 8080 or 8200 | Free the occupied host port or configure an available host port in a local Compose override. |

Keep diagnostics free of secret bodies, wrapping tokens and service tokens. `/ready` is the authenticated Vault check; `/health` only checks the process.

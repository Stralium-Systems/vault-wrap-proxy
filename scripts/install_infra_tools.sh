#!/usr/bin/env bash
# Install the pinned Linux amd64 CLIs after verifying official SHA256 manifests.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tools_dir="${1:?Usage: scripts/install_infra_tools.sh INSTALL_DIRECTORY}"
mkdir -p "$tools_dir"
tools_dir="$(cd "$tools_dir" && pwd)"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
terraform_version="$(cat "$repo_root/.terraform-version")"
helm_version="$(cat "$repo_root/.helm-version")"
cd "$work_dir"

archive="terraform_${terraform_version}_linux_amd64.zip"
base="https://releases.hashicorp.com/terraform/${terraform_version}"
curl --fail --silent --show-error --location --retry 3 "$base/$archive" -o "$archive"
curl --fail --silent --show-error --location --retry 3 "$base/terraform_${terraform_version}_SHA256SUMS" -o SHA256SUMS
awk -v filename="$archive" '$2 == filename {print}' SHA256SUMS > terraform.sha256
test -s terraform.sha256
sha256sum --check terraform.sha256
unzip -oq "$archive" terraform -d "$tools_dir"

archive="helm-v${helm_version}-linux-amd64.tar.gz"
curl --fail --silent --show-error --location --retry 3 "https://get.helm.sh/$archive" -o "$archive"
curl --fail --silent --show-error --location --retry 3 "https://get.helm.sh/$archive.sha256sum" -o helm.sha256
sha256sum --check helm.sha256
tar -xzf "$archive" linux-amd64/helm
install -m 755 linux-amd64/helm "$tools_dir/helm"

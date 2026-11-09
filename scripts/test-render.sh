#!/usr/bin/env bash
# Renders a copy of the repository with sample digests in every version file and checks the result:
# object counts, names, dependsOn chain, and that unreleased entries are skipped.
# Needs cue and yq on PATH (devenv shell). Never touches the working tree.
# KEEP_OUT=<dir> copies the sample render there (for kubeconform).
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
tar -C "$root" --exclude=./out --exclude=./.git -cf - . | tar -C "$work" -xf -
cd "$work"

# count <dir> <glob>: files directly in <dir> matching <glob>
count() { find "$1" -maxdepth 1 -type f -name "$2" | wc -l; }

d1="sha256:$(printf '1%.0s' {1..64})"
d2="sha256:$(printf '2%.0s' {1..64})"

# --- 1. nothing released: no Applications, no set objects
cue vet -c ./...
cue cmd render >/dev/null
test "$(count out/alpha-01/flux "*")" -eq 2   # argo-apps + kustomization.yaml
test "$(count out/alpha-01/argo "application-*")" -eq 0
test "$(count out/alpha-01/argo "applicationset-*")" -eq 2

# --- 2. samples everywhere, except system (unreleased) and notes-stats (unreleased)
cat > clusters/alpha-01/releases.json <<JSON
{
  "rbac": {"version": "0123456789abcdef", "digest": "$d1"},
  "system": {},
  "platform": {"version": "fedcba9876543210", "digest": "$d2"},
  "policy": {"version": "0123456789abcdef", "digest": "$d1"},
  "tenants": {"version": "fedcba9876543210", "digest": "$d2"}
}
JSON
echo "{\"version\": \"v1.2.0\", \"digest\": \"$d1\"}" > apps/notes/notes-api/staging.json
echo "{\"version\": \"v1.1.0\", \"digest\": \"$d2\"}" > apps/notes/notes-api/prod.json

cue vet -c ./...
cue cmd render >/dev/null

flux=out/alpha-01/flux
argo=out/alpha-01/argo
# 4 released sets x (OCIRepository + Kustomization) + argo-apps + kustomization.yaml
test "$(count $flux "*")" -eq 10
test ! -e $flux/ocirepository-set-system.yaml
# dependsOn skips the unreleased set
test "$(yq '.spec.dependsOn[0].name' $flux/kustomization-set-platform.yaml)" = "set-rbac"
test "$(yq '.spec.dependsOn[0].name' $flux/kustomization-set-policy.yaml)" = "set-platform"
test "$(yq '.spec.dependsOn[0].name' $flux/kustomization-set-tenants.yaml)" = "set-policy"
test "$(yq '.spec.dependsOn' $flux/kustomization-set-rbac.yaml)" = "null"
test "$(yq '.spec.dependsOn[0].name' $flux/kustomization-argo-apps.yaml)" = "set-tenants"
test "$(yq '.spec.ref.digest' $flux/ocirepository-set-platform.yaml)" = "$d2"
test "$(yq '.spec.url' $flux/ocirepository-set-rbac.yaml)" = "oci://ghcr.io/homelab-selfuryon/platform-components/alpha-01-rbac"
test "$(yq '.spec.wait' $flux/kustomization-set-rbac.yaml)" = "true"
test "$(yq '.spec.serviceAccountName' $flux/kustomization-set-rbac.yaml)" = "gitops-root"
test "$(yq '.spec.verify.provider' $flux/ocirepository-set-rbac.yaml)" = "cosign"
test "$(yq ".spec.verify.matchOIDCIdentity[0].subject" $flux/ocirepository-set-rbac.yaml)" = "^https://github\\.com/homelab-selfuryon/platform-components/\\.github/workflows/release\\.yaml@refs/heads/main$"

# notes-api: staging and prod, notes-stats: none
test "$(count $argo "application-*")" -eq 2
test "$(yq '.spec.source.targetRevision' $argo/application-notes-api-staging.yaml)" = "$d1"
test "$(yq '.spec.source.targetRevision' $argo/application-notes-api-prod.yaml)" = "$d2"
test "$(yq '.spec.source.repoURL' $argo/application-notes-api-prod.yaml)" = "oci://ghcr.io/homelab-selfuryon/notes-api/manifests"
test "$(yq '.spec.source.path' $argo/application-notes-api-prod.yaml)" = "prod"
test "$(yq '.spec.destination.namespace' $argo/application-notes-api-staging.yaml)" = "notes-staging"
test "$(yq '.spec.project' $argo/application-notes-api-staging.yaml)" = "notes"
test "$(yq '.spec.project' $argo/applicationset-notes-api-preview.yaml)" = "null"
test "$(yq '.spec.template.spec.project' $argo/applicationset-notes-api-preview.yaml)" = "notes-preview"

if [[ -n "${KEEP_OUT:-}" ]]; then cp -r out "$KEEP_OUT"; fi

# --- 3. a version file with only half of the data, or a bad digest, must not vet
echo '{"version": "v1.2.0"}' > apps/notes/notes-api/staging.json
if cue vet -c ./... 2>/dev/null; then echo "half a version file vetted"; exit 1; fi
echo '{"version": "v1.2.0", "digest": "sha256:abc"}' > apps/notes/notes-api/staging.json
if cue vet -c ./... 2>/dev/null; then echo "bad digest vetted"; exit 1; fi
echo '{"version": "v1.2.0", "digest": "'"$d1"'", "extra": 1}' > apps/notes/notes-api/staging.json
if cue vet -c ./... 2>/dev/null; then echo "extra field vetted"; exit 1; fi

echo "render tests passed"

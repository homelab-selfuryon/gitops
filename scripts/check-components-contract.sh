#!/usr/bin/env bash
# Checks a local render of platform-components against what the gitops render assumes about a set
# artifact: the set names of the cluster, `flux/kustomization.yaml` + `flux/kustomizations.yaml` at the
# artifact root, and Kustomizations in flux-system whose sourceRef is the OCIRepository `set-<set>`.
#
#   scripts/check-components-contract.sh <platform-components>/out/<cluster> <cluster>
#
# Needs cue, yq, jq. Not part of `devenv test` (it needs a platform-components checkout).
set -euo pipefail

out=${1:?usage: check-components-contract.sh <out/cluster> <cluster>}
cluster=${2:?cluster}
root=$(cd "$(dirname "$0")/.." && pwd)

sets=$(cd "$root" && cue export -e 'clusters["'"$cluster"'"].sets' --out json | jq -r '.[]')
status=0
for set_name in $sets; do
  dir="$out/$set_name"
  [[ -d "$dir" ]] || { echo "set ${set_name}: not rendered in $out" >&2; status=1; continue; }
  for f in flux/kustomization.yaml flux/kustomizations.yaml; do
    [[ -f "$dir/$f" ]] || { echo "set ${set_name}: $f missing" >&2; status=1; }
  done
  [[ -f "$dir/flux/kustomizations.yaml" ]] || continue
  bad=$(yq -r 'select(.kind == "Kustomization") | select(.metadata.namespace != "flux-system" or .spec.sourceRef.kind != "OCIRepository" or .spec.sourceRef.name != "set-'"$set_name"'") | .metadata.name' "$dir/flux/kustomizations.yaml")
  if [[ -n "$bad" ]]; then echo "set ${set_name}: Kustomizations with a wrong namespace or sourceRef: $bad" >&2; status=1; fi
  echo "set ${set_name}: $(yq -r 'select(.kind == "Kustomization") | .metadata.name' "$dir/flux/kustomizations.yaml" | wc -l) component Kustomizations"
done
# Rendered sets the cluster definition does not know would be silently ignored.
for d in "$out"/*/; do
  n=$(basename "$d")
  [[ -d "$d/flux" ]] || continue
  grep -qx "$n" <<<"$sets" || { echo "rendered set ${n} is not in clusters/${cluster}/cluster.cue" >&2; status=1; }
done
exit "$status"

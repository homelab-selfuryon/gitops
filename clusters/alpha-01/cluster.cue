@extern(embed)

// alpha-01: Talos, one node. See platform-components for what the sets contain.
package alpha01

import "github.com/homelab-selfuryon/gitops/schema"

cluster: schema.#Cluster & {
	name: "alpha-01"
	// Apply order. rbac and system are privileged, tenants comes last: the Argo CD objects wait for it.
	sets: ["rbac", "system", "policy", "platform", "tenants"]
	// {"version": "<content hash>", "digest": "sha256:..."}: the platform artifact (a directory per
	// set), written by the components-release workflow. `{}`: not released yet, no platform objects.
	release: _ @embed(file="releases.json")
}

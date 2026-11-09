// Package gitops is the root: it lists every cluster and app and renders them.
// Adding a cluster or an app means adding its directory and one import here
// (scripts/check_layout.py makes sure the two agree).
package gitops

import (
	"github.com/homelab-selfuryon/gitops/schema"

	alpha01 "github.com/homelab-selfuryon/gitops/clusters/alpha-01:alpha01"
	notesapi "github.com/homelab-selfuryon/gitops/apps/notes/notes-api:notesapi"
	notesstats "github.com/homelab-selfuryon/gitops/apps/notes/notes-stats:notesstats"
)

clusters: "alpha-01": alpha01.cluster

// Keyed by <team>/<name>, which must match the directory under apps/.
apps: {
	"notes/notes-api":   notesapi.app
	"notes/notes-stats": notesstats.app
}

// The key must be <team>/<name>.
_keys: {for k, s in apps {(k): k & "\(s.team)/\(s.name)"}}

rendered: schema.#Render & {
	"clusters": clusters
	"apps":     apps
}

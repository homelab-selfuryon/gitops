@extern(embed)

// Registration of notes-api, owned by the platform team. Teams change staging.json (release PRs, no owner)
// and prod.json (promote PRs, owned by the team), never this file.
package notesapi

import "github.com/homelab-selfuryon/gitops/schema"

app: schema.#App & {
	name:    "notes-api"
	team:    "notes"
	repo:    "homelab-selfuryon/notes-api"
	cluster: "alpha-01"
	preview: true
	// {"version": "v1.2.0", "digest": "sha256:..."}; `{}` = not released yet, no Application.
	staging: _ @embed(file="staging.json")
	prod:    _ @embed(file="prod.json")
}

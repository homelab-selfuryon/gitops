// Package schema holds the data types of gitops and the render from that data to Flux and Argo CD
// objects. Everything a PR can change (version files, releases.json) is validated here, so a
// release PR can move a digest and nothing else.
package schema

#Registry: "ghcr.io/homelab-selfuryon"
#Prefix:   "homelab-selfuryon.github.io"

#Name:   =~"^[a-z][a-z0-9-]{1,40}$"
#Team:   =~"^[a-z][a-z0-9-]{1,30}$"
#Digest: =~"^sha256:[0-9a-f]{64}$"

// Environments an app is promoted through. `preview` is not data: it is created per PR.
#Env: "staging" | "prod"

// An app version file (staging.json, prod.json). `{}` means "not released yet": the render
// skips the Application until a release PR fills it in.
#Version: {
	version?: =~"^v[0-9]+\\.[0-9]+\\.[0-9]+(-[0-9A-Za-z.-]+)?$"
	digest?:  #Digest
	// Both or neither.
	if version != _|_ {digest: #Digest}
	if digest != _|_ {version: string}
}

// One platform set of a cluster (an entry of releases.json). The version is the content hash that
// platform-components tags the artifact with. `{}` means "not released yet".
#SetRelease: {
	version?: =~"^[0-9a-f]{16}$"
	digest?:  #Digest
	// Both or neither.
	if version != _|_ {digest: #Digest}
	if digest != _|_ {version: string}
}

// Registration of a tenant app (apps/<team>/<name>/app.cue), owned by the platform team.
#App: {
	name:    #Name
	team:    #Team
	repo:    "homelab-selfuryon/\(name)"
	cluster: #Name
	// An ApplicationSet creates a preview environment per open pull request.
	preview: bool | *true
	// Version files, embedded from staging.json and prod.json next to app.cue.
	staging: #Version
	prod:    #Version
}

#Cluster: {
	name: #Name
	// Platform sets in apply order: every set waits for the previous released one.
	sets:     [#Name, ...#Name]
	releases: {for s in sets {(s): #SetRelease}}
	// Where platform-components publishes the set artifacts: <repo>/<cluster>-<set>.
	componentsRepo: "\(#Registry)/platform-components"
}

package gitops

import (
	"encoding/yaml"
	"tool/cli"
	"tool/file"
)

// cue cmd render
//
// Writes out/<cluster>/{flux,argo}/<object>.yaml and a kustomization.yaml in each directory.
// `flux/` is applied by the root Kustomization (bootstrap), `argo/` by the argo-apps Kustomization.
command: render: {
	clean: file.RemoveAll & {path: "out"}

	for cname, c in rendered.out for dir in ["flux", "argo"] {
		let _objects = c[dir]
		let _base = "out/\(cname)/\(dir)"

		"mkdir-\(cname)-\(dir)": file.MkdirAll & {path: _base, $after: clean}

		for fname, obj in _objects {
			"write-\(cname)-\(dir)-\(fname)": file.Create & {
				$after:   command.render["mkdir-\(cname)-\(dir)"]
				filename: "\(_base)/\(fname).yaml"
				contents: yaml.Marshal(obj)
			}
		}

		"kustomization-\(cname)-\(dir)": file.Create & {
			$after:   command.render["mkdir-\(cname)-\(dir)"]
			filename: "\(_base)/kustomization.yaml"
			contents: yaml.Marshal({
				apiVersion: "kustomize.config.k8s.io/v1beta1"
				kind:       "Kustomization"
				resources:  [for fname, _ in _objects {"\(fname).yaml"}]
			})
		}
	}

	done: cli.Print & {
		$after: [for k, v in command.render if k != "done" {v}]
		text:   "rendered to out/"
	}
}

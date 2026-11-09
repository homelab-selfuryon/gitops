# CLAUDE.md

GitOps state of the `homelab-selfuryon` org: data plus a CUE render to Flux and Argo CD objects.
Read `meta/delivery.md` ("gitops layout", "Flux object names") first; names there are a contract with
`platform-components` and `github-workflows`.

## Layout

```
schema/        types and #Render (data -> objects)     registry.cue   clusters and apps that exist
ext_tool.cue   `cue cmd render` -> out/<c>/{flux,argo}  clusters/      cluster.cue + releases.json
apps/<team>/<app>/  app.cue, staging.json, prod.json
devenv.nix/.yaml/.lock  cue v0.18.0-rc.3 (upstream tarball), kubeconform, kyverno, ...
scripts/       gitops_checks.py (+ test_*.py), test-render.sh, check-components-contract.sh
.github/       CODEOWNERS, chainguard/ (octo-sts policies), workflows/ (callers of github-workflows)
```

## Commands

```
devenv shell -- cue fmt ./...        # treefmt also does it; check: cue fmt --check ./...
devenv shell -- cue vet -c ./...
devenv shell -- cue cmd render       # out/ is git-ignored
devenv shell -- bash scripts/test-render.sh
devenv test                          # treefmt, vet, unit tests, sample render, shellcheck
```

## Conventions

- Version files are data: `{}` (unreleased) or `{"version", "digest"}`; never hand-edit them except
  to roll back. A release PR may change one file only; `scripts/gitops_checks.py` enforces it.
- CUE language v0.18: no `K=string` aliases (use `~`); the key check in registry.cue is a comprehension.
- Registrations normally arrive as `register/<app>` PRs from app-register; version files and
  `devenv.lock` have their own bot branches (see gitops_checks.py).
- The root package field `rendered` must not be named `render` (it would shadow `command: render`).
- Adding an app or cluster means a directory and an import in `registry.cue`
  (`gitops_checks.py layout` checks they agree).
- `.github/workflows/publish.yaml` signs in its own job on purpose (the subject is what Flux checks): do not turn it into a reusable-workflow call.
- Never put anything sensitive here: the repository is public and its content is the cluster's truth.
- Conventional Commits (`!` for breaking changes), signed commits.

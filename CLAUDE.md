# CLAUDE.md

GitOps state of the `homelab-selfuryon` org: data plus a CUE render to Flux and Argo CD objects.
Read `meta/delivery.md` ("gitops layout", "Flux object names") first; names there are a contract with
`platform-components` and `github-workflows`.

## Layout

```
schema/        types and #Render (data -> objects)     registry.cue   clusters; apps from catalog.json
ext_tool.cue   `cue cmd render` -> out/<c>/{flux,argo}  clusters/      cluster.cue + releases.json
catalog.json   from the `catalog` repository, never edited here (prettier leaves it alone)
apps/<team>/<app>/  staging.json, prod.json
devenv.nix/.yaml/.lock  cue v0.18.0 (upstream release binary), kubeconform, kyverno, ...
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

- Version files (`releases.json` too: one platform artifact per cluster) are data: `{}` (unreleased) or `{"version", "digest"}`; never hand-edit them except
  to roll back. A release PR may change one file only; `scripts/gitops_checks.py` enforces it.
- CUE language v0.18: no `K=string` aliases (use `~`).
- Apps come from `catalog.json` (a `catalog/sync` PR from the `catalog` repository); version files
  and `devenv.lock` have their own bot branches (see gitops_checks.py).
- The root package field `rendered` must not be named `render` (it would shadow `command: render`).
- Adding an app means adding it in the `catalog` repository; `gitops_checks.py sync` writes the
  version files and CODEOWNERS lines it implies, `layout` checks them. A cluster is a directory and
  an import in `registry.cue`.
- `.github/workflows/publish.yaml` signs in its own job on purpose (the subject is what Flux checks): do not turn it into a reusable-workflow call.
- Never put anything sensitive here: the repository is public and its content is the cluster's truth.
- Conventional Commits (`!` for breaking changes), signed commits.

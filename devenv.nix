# Only what is specific to gitops. CUE, treefmt (nixfmt, prettier, cue fmt), the base git hooks and
# actionlint/zizmor/shellcheck/jq come from platform-kit/devenv/cue.nix (see devenv.yaml).
{ pkgs, ... }:
{
  # CI runs the same commands as `devenv shell -- <cmd>` (verify.yaml, publish.yaml).
  packages = with pkgs; [
    python3
    yq-go
    kubeconform
    oras
    cosign
    kyverno
  ];

  treefmt.config.settings.global.excludes = [ "out/**" ];

  git-hooks.hooks.actionlint.enable = true;

  # `devenv test` (after the base step `treefmt --fail-on-change`)
  enterTest = ''
    cue vet -c ./...
    PYTHONPATH=scripts python3 -I -m unittest discover -s scripts
    bash scripts/test-render.sh
    shellcheck scripts/*.sh
  '';
}

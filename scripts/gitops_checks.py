#!/usr/bin/env python3
"""Checks on a gitops pull request that CUE cannot express. Standard library only.

  release-pr  who may change which files: a PR opened by the release bot (release, promote, register,
              devenv-update) touches exactly the files
              its branch name announces, and nothing else
  layout      every app and cluster directory is complete and registered in registry.cue
  registrations  which team owns which repository in the registrations a PR changes
  artifacts   what must be verified in the registry for the version files a PR changed

The logic lives in functions (see test_gitops_checks.py); the workflows call the CLI of the *base*
branch, so a PR cannot weaken its own checks.
"""

import argparse
import json
import pathlib
import re
import sys

REGISTRY = "ghcr.io/homelab-selfuryon"
BOT = "octo-sts[bot]"

NAME = r"[a-z][a-z0-9-]{1,40}"
VERSION = r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?"

# Branches the release workflows open, and the one file each may change.
BRANCHES = [
    (re.compile(rf"^release/(?P<app>{NAME})/staging/{VERSION}$"), "staging"),
    (re.compile(rf"^promote/(?P<app>{NAME})/prod/{VERSION}$"), "prod"),
    (re.compile(rf"^release/platform-components/(?P<cluster>{NAME})$"), "components"),
    (re.compile(rf"^register/(?P<app>{NAME})$"), "register"),
    (re.compile(r"^chore/devenv-update$"), "devenv"),
]

VERSION_FILE = re.compile(rf"^apps/(?P<team>{NAME})/(?P<app>{NAME})/(?P<env>staging|prod)\.json$")
CLUSTER_FILE = re.compile(rf"^clusters/(?P<cluster>{NAME})/releases\.json$")


def is_version_file(path: str) -> bool:
    return bool(VERSION_FILE.match(path) or CLUSTER_FILE.match(path))


def check_release_pr(branch: str, author: str, files: list[str], bot: str = BOT) -> list[str]:
    """Errors for a PR from `author` on `branch` that changes `files`."""
    errors = []
    for pattern, kind in BRANCHES:
        m = pattern.match(branch)
        if not m:
            continue
        if kind == "devenv":
            if files != ["devenv.lock"]:
                errors.append(f"branch {branch} may change devenv.lock only, got: {sorted(files)}")
            return errors
        if kind == "register":
            # A registration: the app's three files and its import in registry.cue.
            team_dirs = {f.split("/")[1] for f in files if f.startswith("apps/")}
            if len(team_dirs) != 1:
                errors.append(f"branch {branch} must register one app under one team, got: {sorted(files)}")
                return errors
            team = team_dirs.pop()
            expected = {
                "registry.cue",
                f"apps/{team}/{m['app']}/app.cue",
                f"apps/{team}/{m['app']}/staging.json",
                f"apps/{team}/{m['app']}/prod.json",
            }
            if set(files) != expected:
                errors.append(f"branch {branch} must change exactly {sorted(expected)}, got: {sorted(files)}")
            return errors
        if kind == "components":
            allowed = [f for f in files if (c := CLUSTER_FILE.match(f)) and c["cluster"] == m["cluster"]]
        else:
            allowed = [
                f for f in files
                if (a := VERSION_FILE.match(f)) and a["app"] == m["app"] and a["env"] == kind
            ]
        if len(allowed) != 1 or len(files) != 1:
            errors.append(
                f"branch {branch} may change exactly one version file of its own, got: {sorted(files)}"
            )
        return errors
    if author == bot:
        errors.append(
            f"{bot} may only open release/<app>/staging/<version>, promote/<app>/prod/<version>, register/<app>, chore/devenv-update "
            f"or release/platform-components/<cluster> branches, got {branch}"
        )
    return errors


def read_json(path: pathlib.Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise SystemExit(f"{path}: {e}")


def check_layout(root: pathlib.Path) -> list[str]:
    errors = []
    registry = (root / "registry.cue").read_text()
    for app_dir in sorted(p for p in (root / "apps").glob("*/*") if p.is_dir()):
        team, app = app_dir.parent.name, app_dir.name
        rel = app_dir.relative_to(root)
        for name in ("app.cue", "staging.json", "prod.json"):
            if not (app_dir / name).is_file():
                errors.append(f"{rel}/{name} is missing")
        for name in ("staging.json", "prod.json"):
            f = app_dir / name
            if f.is_file() and not isinstance(read_json(f), dict):
                errors.append(f"{rel}/{name} must be a JSON object")
        cue = app_dir / "app.cue"
        if cue.is_file():
            text = cue.read_text()
            if not re.search(rf'^\s*name:\s*"{re.escape(app)}"', text, re.M):
                errors.append(f'{rel}/app.cue: name must be "{app}" (the directory)')
            if not re.search(rf'^\s*team:\s*"{re.escape(team)}"', text, re.M):
                errors.append(f'{rel}/app.cue: team must be "{team}" (the directory)')
        if f"/apps/{team}/{app}:" not in registry:
            errors.append(f"registry.cue does not import apps/{team}/{app}")
    for cluster_dir in sorted(p for p in (root / "clusters").glob("*") if p.is_dir()):
        rel = cluster_dir.relative_to(root)
        for name in ("cluster.cue", "releases.json"):
            if not (cluster_dir / name).is_file():
                errors.append(f"{rel}/{name} is missing")
        if f"/clusters/{cluster_dir.name}:" not in registry:
            errors.append(f"registry.cue does not import clusters/{cluster_dir.name}")
    return errors


def artifacts(root: pathlib.Path, files: list[str], apps: dict) -> list[dict]:
    """What the registry must confirm for the version files in `files` (paths relative to root).

    `apps` is `cue export -e apps`: keyed by <team>/<name>, with the registered repo.
    Entries without a digest (not released) are skipped.
    """
    out = []
    for path in sorted(files):
        if m := VERSION_FILE.match(path):
            data = read_json(root / path)
            if not data.get("digest"):
                continue
            key = f"{m['team']}/{m['app']}"
            if key not in apps:
                raise SystemExit(f"{path}: {key} is not a registered app")
            out.append({
                "file": path,
                "artifact": f"{REGISTRY}/{m['app']}/manifests",
                # The artifact holds every environment; this file moves only this one.
                "env": m["env"],
                "team": m["team"],
                "tag": data["version"],
                "digest": data["digest"],
                "workflow": "app-release",
                "repo": apps[key]["repo"],
            })
        elif m := CLUSTER_FILE.match(path):
            for set_name, rel in sorted(read_json(root / path).items()):
                if not rel.get("digest"):
                    continue
                out.append({
                    "file": path,
                    "artifact": f"{REGISTRY}/platform-components/{m['cluster']}-{set_name}",
                    "tag": rel["version"],
                    "digest": rel["digest"],
                    "workflow": "components-release",
                    "repo": "homelab-selfuryon/platform-components",
                })
    return out


REGISTRATION_FILE = re.compile(rf"^apps/(?P<team>{NAME})/(?P<app>{NAME})/app\.cue$")


def registrations(root: pathlib.Path, files: list[str], apps: dict) -> list[dict]:
    """The registrations a PR adds or changes: which team the CUE says owns which repository.

    The workflow compares `team` with the repository's `owner-team` custom property.
    """
    out = []
    for path in sorted(files):
        m = REGISTRATION_FILE.match(path)
        if not m or not (root / path).is_file():
            continue
        key = f"{m['team']}/{m['app']}"
        if key not in apps:
            raise SystemExit(f"{path}: {key} is not in registry.cue")
        out.append({"file": path, "team": apps[key]["team"], "repo": apps[key]["repo"]})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("release-pr")
    p.add_argument("--branch", required=True)
    p.add_argument("--author", required=True)
    p.add_argument("--bot", default=BOT)
    p.add_argument("files", nargs="*", help="changed files (also read from stdin, one per line, when '-')")

    p = sub.add_parser("layout")
    p.add_argument("--root", default=".")

    p = sub.add_parser("artifacts")
    p.add_argument("--root", default=".")
    p.add_argument("--apps", required=True, help="file with `cue export -e apps`")
    p.add_argument("files", nargs="*")

    p = sub.add_parser("registrations")
    p.add_argument("--root", default=".")
    p.add_argument("--apps", required=True, help="file with `cue export -e apps`")
    p.add_argument("files", nargs="*")

    args = ap.parse_args(argv)
    files = getattr(args, "files", [])
    if files == ["-"]:
        files = [line.strip() for line in sys.stdin if line.strip()]

    if args.cmd == "release-pr":
        errors = check_release_pr(args.branch, args.author, files, args.bot)
    elif args.cmd == "layout":
        errors = check_layout(pathlib.Path(args.root))
    elif args.cmd == "registrations":
        apps = read_json(pathlib.Path(args.apps))
        for item in registrations(pathlib.Path(args.root), files, apps):
            print(json.dumps(item))
        return 0
    else:
        apps = read_json(pathlib.Path(args.apps))
        for item in artifacts(pathlib.Path(args.root), files, apps):
            print(json.dumps(item))
        return 0

    for e in errors:
        print(f"::error::{e}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

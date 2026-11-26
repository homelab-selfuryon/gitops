#!/usr/bin/env python3
"""Checks on a gitops pull request that CUE cannot express. Standard library only.

  release-pr  who may change which files: a PR opened by the release bot (release, promote,
              catalog sync, devenv-update) touches exactly the files
              its branch name announces, and nothing else
  layout      every app and cluster directory is complete and registered: apps in catalog.json
              (with the CODEOWNERS lines it implies), clusters in registry.cue
  sync        writes what catalog.json implies: `{}` version files of new apps, no directories of
              apps that left it, the generated CODEOWNERS block (`layout` fails until it is run)
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
    (re.compile(r"^catalog/sync$"), "catalog"),
    (re.compile(r"^chore/devenv-update$"), "devenv"),
]

CATALOG = "catalog.json"
CODEOWNERS = ".github/CODEOWNERS"

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
        if kind == "catalog":
            # catalog.json from the `catalog` repository and what `sync` derives from it. A version
            # file here is `{}` of a new app or the removal of an app; one with a digest is verified
            # like any other (artifacts).
            extra = [f for f in files if f not in (CATALOG, CODEOWNERS) and not VERSION_FILE.match(f)]
            if CATALOG not in files or extra:
                errors.append(
                    f"branch {branch} must change {CATALOG}, and besides it only {CODEOWNERS} and "
                    f"version files, got: {sorted(files)}"
                )
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
            f"{bot} may only open release/<app>/staging/<version>, promote/<app>/prod/<version>, catalog/sync, chore/devenv-update "
            f"or release/platform-components/<cluster> branches, got {branch}"
        )
    return errors


def read_json(path: pathlib.Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise SystemExit(f"{path}: {e}")


VERSION_FILES = ("staging.json", "prod.json")
OWNERS_BEGIN = "# BEGIN generated from catalog.json (scripts/gitops_checks.py sync)"
OWNERS_END = "# END generated"


def catalog_apps(root: pathlib.Path) -> dict[str, str]:
    """`<team>/<app>` -> team of every app in catalog.json."""
    apps = read_json(root / CATALOG).get("apps", {})
    return {f"{a['team']}/{name}": a["team"] for name, a in apps.items()}


def owners_block(teams) -> str:
    """CODEOWNERS lines between the markers: a team's prod version files are the team's."""
    lines = [OWNERS_BEGIN]
    for team in sorted(set(teams)):
        path = f"/apps/{team}/*/prod.json"
        lines.append(f"{path.ljust(35)}@homelab-selfuryon/{team}")
    lines.append(OWNERS_END)
    return "\n".join(lines) + "\n"


def replace_owners_block(text: str, block: str) -> str | None:
    """`text` with its generated block replaced, or None without markers."""
    m = re.search(rf"^{re.escape(OWNERS_BEGIN)}\n.*?^{re.escape(OWNERS_END)}\n", text, re.M | re.S)
    if not m:
        return None
    return text[: m.start()] + block + text[m.end() :]


def app_dirs(root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in (root / "apps").glob("*/*") if p.is_dir())


def check_layout(root: pathlib.Path) -> list[str]:
    if not (root / CATALOG).is_file():
        return [f"{CATALOG} is missing (it comes from the `catalog` repository)"]
    errors = []
    apps = catalog_apps(root)
    dirs = {f"{p.parent.name}/{p.name}": p for p in app_dirs(root)}
    for key in sorted(apps):
        if key not in dirs:
            errors.append(f"apps/{key}/ is missing (run scripts/gitops_checks.py sync)")
    for key, app_dir in sorted(dirs.items()):
        rel = app_dir.relative_to(root)
        if key not in apps:
            errors.append(f"{rel}/ is not an app of {CATALOG} (run scripts/gitops_checks.py sync)")
            continue
        for f in sorted(app_dir.iterdir()):
            if f.name not in VERSION_FILES:
                errors.append(f"{rel}/{f.name}: only {' and '.join(VERSION_FILES)} belong here")
        for name in VERSION_FILES:
            f = app_dir / name
            if not f.is_file():
                errors.append(f"{rel}/{name} is missing (run scripts/gitops_checks.py sync)")
            elif not isinstance(read_json(f), dict):
                errors.append(f"{rel}/{name} must be a JSON object")
    owners = (root / CODEOWNERS).read_text() if (root / CODEOWNERS).is_file() else ""
    want = replace_owners_block(owners, owners_block(apps.values()))
    if want is None:
        errors.append(f"{CODEOWNERS}: the generated block ({OWNERS_BEGIN!r} ... {OWNERS_END!r}) is missing")
    elif want != owners:
        errors.append(f"{CODEOWNERS}: the generated block is out of date (run scripts/gitops_checks.py sync)")
    errors += check_clusters(root)
    return errors


def sync(root: pathlib.Path) -> list[str]:
    """Brings apps/ and CODEOWNERS in line with catalog.json; returns what it changed."""
    changed = []
    apps = catalog_apps(root)
    for key in sorted(apps):
        for name in VERSION_FILES:
            f = root / "apps" / key / name
            if not f.exists():
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text("{}\n")
                changed.append(str(f.relative_to(root)))
    for app_dir in app_dirs(root):
        if f"{app_dir.parent.name}/{app_dir.name}" not in apps:
            for f in sorted(app_dir.iterdir()):
                f.unlink()
                changed.append(str(f.relative_to(root)))
            app_dir.rmdir()
            if not any(app_dir.parent.iterdir()):
                app_dir.parent.rmdir()
    path = root / CODEOWNERS
    owners = path.read_text()
    want = replace_owners_block(owners, owners_block(apps.values()))
    if want is None:
        raise SystemExit(f"{CODEOWNERS}: the generated block ({OWNERS_BEGIN!r} ... {OWNERS_END!r}) is missing")
    if want != owners:
        path.write_text(want)
        changed.append(CODEOWNERS)
    return changed


def check_clusters(root: pathlib.Path) -> list[str]:
    errors = []
    registry = (root / "registry.cue").read_text()
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
            data = read_json(root / path)
            # One artifact per cluster ({version, digest}, or {} before the first release), or the
            # earlier format, one artifact per set ({<set>: {version, digest}}). Both are read while
            # the change between them is under review: these checks run from the base branch.
            if not data or "digest" in data:
                releases = [(f"{REGISTRY}/platform-components/{m['cluster']}", data)]
            else:
                releases = [
                    (f"{REGISTRY}/platform-components/{m['cluster']}-{set_name}", rel)
                    for set_name, rel in sorted(data.items())
                ]
            for artifact, rel in releases:
                if not isinstance(rel, dict) or not rel.get("digest"):
                    continue
                out.append({
                    "file": path,
                    "artifact": artifact,
                    "tag": rel["version"],
                    "digest": rel["digest"],
                    "workflow": "components-release",
                    "repo": "homelab-selfuryon/platform-components",
                })
    return out


def registrations(files: list[str], apps: dict) -> list[dict]:
    """Which team owns which repository, for every app, when a PR changes catalog.json.

    `apps` is `cue export -e apps`, keyed by <team>/<name>. The workflow compares `team` with the
    repository's `owner-team` custom property (platform-terraform applies the catalog first).
    """
    if CATALOG not in files:
        return []
    return [{"file": CATALOG, "team": a["team"], "repo": a["repo"]} for _, a in sorted(apps.items())]


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

    p = sub.add_parser("sync")
    p.add_argument("--root", default=".")

    p = sub.add_parser("artifacts")
    p.add_argument("--root", default=".")
    p.add_argument("--apps", required=True, help="file with `cue export -e apps`")
    p.add_argument("files", nargs="*")

    p = sub.add_parser("registrations")
    p.add_argument("--root", default=".", help="unused; the workflow passes it")
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
    elif args.cmd == "sync":
        for path in sync(pathlib.Path(args.root)):
            print(path)
        return 0
    elif args.cmd == "registrations":
        apps = read_json(pathlib.Path(args.apps))
        for item in registrations(files, apps):
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

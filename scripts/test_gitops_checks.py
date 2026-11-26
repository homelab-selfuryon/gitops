import json
import pathlib
import tempfile
import unittest

import gitops_checks as g

ST = "apps/notes/notes-api/staging.json"
PR = "apps/notes/notes-api/prod.json"
D = "sha256:" + "a" * 64


class ReleasePr(unittest.TestCase):
    def test_staging_release_ok(self):
        self.assertEqual(g.check_release_pr("release/notes-api/staging/v1.2.0", g.BOT, [ST]), [])

    def test_promote_ok(self):
        self.assertEqual(g.check_release_pr("promote/notes-api/prod/v1.2.0", g.BOT, [PR]), [])

    def test_components_ok(self):
        self.assertEqual(
            g.check_release_pr("release/platform-components/alpha-01", g.BOT, ["clusters/alpha-01/releases.json"]), []
        )

    def test_extra_file_rejected(self):
        self.assertTrue(g.check_release_pr("release/notes-api/staging/v1.2.0", g.BOT, [ST, "schema/render.cue"]))

    def test_other_app_rejected(self):
        self.assertTrue(
            g.check_release_pr("release/notes-api/staging/v1.2.0", g.BOT, ["apps/notes/notes-stats/staging.json"])
        )

    def test_staging_branch_cannot_move_prod(self):
        self.assertTrue(g.check_release_pr("release/notes-api/staging/v1.2.0", g.BOT, [PR]))

    def test_promote_branch_cannot_move_staging(self):
        self.assertTrue(g.check_release_pr("promote/notes-api/prod/v1.2.0", g.BOT, [ST]))

    def test_components_branch_other_cluster(self):
        self.assertTrue(
            g.check_release_pr("release/platform-components/alpha-01", g.BOT, ["clusters/beta-01/releases.json"])
        )

    def test_bot_on_unknown_branch_rejected(self):
        self.assertTrue(g.check_release_pr("feature/x", g.BOT, [ST]))

    def test_human_on_any_branch_ok(self):
        self.assertEqual(g.check_release_pr("revert-12", "someone", [ST, PR]), [])

    def test_human_on_release_branch_still_restricted(self):
        self.assertTrue(g.check_release_pr("release/notes-api/staging/v1.2.0", "someone", [ST, PR]))

    def test_bad_version_in_branch(self):
        self.assertTrue(g.check_release_pr("release/notes-api/staging/latest", g.BOT, [ST]))


def tree(root: pathlib.Path, files: dict):
    for name, content in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)


GOOD = {
    "apps/notes/notes-api/staging.json": "{}",
    "apps/notes/notes-api/prod.json": "{}",
    "clusters/alpha-01/releases.json": "{}",
}


class Artifacts(unittest.TestCase):
    def test_collects_released_only(self):
        files = dict(GOOD)
        files[ST] = json.dumps({"version": "v1.2.0", "digest": D})
        files["clusters/alpha-01/releases.json"] = json.dumps({"version": "0123456789abcdef", "digest": D})
        apps = {"notes/notes-api": {"repo": "homelab-selfuryon/notes-api"}}
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            tree(root, files)
            got = g.artifacts(root, [ST, PR, "clusters/alpha-01/releases.json"], apps)
        self.assertEqual(
            [(a["artifact"], a["tag"], a["workflow"]) for a in got],
            [
                ("ghcr.io/homelab-selfuryon/notes-api/manifests", "v1.2.0", "app-release"),
                ("ghcr.io/homelab-selfuryon/platform-components/alpha-01", "0123456789abcdef", "components-release"),
            ],
        )
        self.assertEqual(got[0]["repo"], "homelab-selfuryon/notes-api")
        self.assertEqual(got[0]["env"], "staging")
        self.assertEqual(got[0]["team"], "notes")
        self.assertNotIn("env", got[1])

    def test_one_artifact_per_cluster(self):
        for content, want in [
            ({"version": "0123456789abcdef", "digest": D}, ["ghcr.io/homelab-selfuryon/platform-components/alpha-01"]),
            ({}, []),
        ]:
            files = dict(GOOD)
            files["clusters/alpha-01/releases.json"] = json.dumps(content)
            with tempfile.TemporaryDirectory() as d:
                root = pathlib.Path(d)
                tree(root, files)
                got = g.artifacts(root, ["clusters/alpha-01/releases.json"], {})
            self.assertEqual([a["artifact"] for a in got], want)




class Register(unittest.TestCase):
    def test_devenv_update(self):
        self.assertEqual(g.check_release_pr("chore/devenv-update", g.BOT, ["devenv.lock"]), [])
        self.assertTrue(g.check_release_pr("chore/devenv-update", g.BOT, ["devenv.lock", "devenv.nix"]))

    def test_registrations_catalog_lists_every_app(self):
        apps = {
            "notes/notes-api": {"team": "notes", "repo": "homelab-selfuryon/notes-api"},
            "notes/notes-stats": {"team": "notes", "repo": "homelab-selfuryon/notes-stats"},
        }
        got = g.registrations(["catalog.json", ST], apps)
        self.assertEqual([r["repo"] for r in got], ["homelab-selfuryon/notes-api", "homelab-selfuryon/notes-stats"])

    def test_registrations_without_catalog_change(self):
        self.assertEqual(g.registrations([ST], {"notes/notes-api": {"team": "notes", "repo": "x"}}), [])

    def test_register_branch_is_gone(self):
        self.assertTrue(g.check_release_pr("register/new-app", g.BOT, ["registry.cue"]))


def catalog(*apps):
    return json.dumps({"teams": {}, "apps": {name: {"name": name, "team": team} for team, name in apps}})


OWNERS_HEAD = "*                                  @homelab-selfuryon/platform\n"
NOTES_OWNERS = OWNERS_HEAD + g.owners_block(["notes"])

CAT = {
    "catalog.json": catalog(("notes", "notes-api")),
    "registry.cue": 'import a "x/clusters/alpha-01:alpha01"\n',
    ".github/CODEOWNERS": NOTES_OWNERS,
    "apps/notes/notes-api/staging.json": "{}",
    "apps/notes/notes-api/prod.json": "{}",
    "clusters/alpha-01/cluster.cue": "",
    "clusters/alpha-01/releases.json": "{}",
}


class CatalogLayout(unittest.TestCase):
    def run_layout(self, files):
        with tempfile.TemporaryDirectory() as d:
            tree(pathlib.Path(d), files)
            return g.check_layout(pathlib.Path(d))

    def test_good(self):
        self.assertEqual(self.run_layout(CAT), [])

    def test_owners_line(self):
        self.assertIn("/apps/notes/*/prod.json            @homelab-selfuryon/notes\n", NOTES_OWNERS)

    def test_app_without_directory(self):
        f = dict(CAT, **{"catalog.json": catalog(("notes", "notes-api"), ("notes", "new-app"))})
        self.assertTrue(self.run_layout(f))

    def test_directory_without_app(self):
        f = dict(CAT, **{"apps/notes/old-app/staging.json": "{}", "apps/notes/old-app/prod.json": "{}"})
        self.assertTrue(self.run_layout(f))

    def test_wrong_team(self):
        f = dict(CAT, **{"catalog.json": catalog(("other", "notes-api"))})
        self.assertTrue(self.run_layout(f))

    def test_stray_file(self):
        f = dict(CAT, **{"apps/notes/notes-api/app.cue": ""})
        self.assertTrue(self.run_layout(f))

    def test_missing_version_file(self):
        f = dict(CAT)
        del f["apps/notes/notes-api/prod.json"]
        self.assertTrue(self.run_layout(f))

    def test_owners_out_of_date(self):
        f = dict(CAT, **{".github/CODEOWNERS": OWNERS_HEAD + g.owners_block(["notes", "other"])})
        self.assertTrue(self.run_layout(f))

    def test_owners_without_block(self):
        f = dict(CAT, **{".github/CODEOWNERS": OWNERS_HEAD})
        self.assertTrue(self.run_layout(f))

    def test_without_catalog(self):
        f = dict(CAT)
        del f["catalog.json"]
        self.assertTrue(self.run_layout(f))

    def test_cluster_not_imported(self):
        f = dict(CAT, **{"registry.cue": ""})
        self.assertTrue(self.run_layout(f))


class Sync(unittest.TestCase):
    def test_sync_then_layout_passes(self):
        files = dict(CAT, **{
            "catalog.json": catalog(("notes", "notes-api"), ("search", "search-api")),
            "apps/old/old-app/staging.json": "{}",
            "apps/old/old-app/prod.json": "{}",
        })
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            tree(root, files)
            self.assertTrue(g.check_layout(root))
            changed = g.sync(root)
            self.assertEqual(g.check_layout(root), [])
            self.assertEqual(g.sync(root), [])
            self.assertFalse((root / "apps/old").exists())
            self.assertEqual((root / "apps/search/search-api/staging.json").read_text(), "{}\n")
            self.assertIn("@homelab-selfuryon/search", (root / ".github/CODEOWNERS").read_text())
        self.assertEqual(
            changed,
            [
                "apps/search/search-api/staging.json",
                "apps/search/search-api/prod.json",
                "apps/old/old-app/prod.json",
                "apps/old/old-app/staging.json",
                ".github/CODEOWNERS",
            ],
        )

    def test_sync_keeps_released_versions(self):
        files = dict(CAT, **{ST: json.dumps({"version": "v1.2.0", "digest": D})})
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            tree(root, files)
            self.assertEqual(g.sync(root), [])
            self.assertIn(D, (root / ST).read_text())


class CatalogBranch(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(g.check_release_pr("catalog/sync", g.BOT, ["catalog.json"]), [])
        self.assertEqual(
            g.check_release_pr("catalog/sync", g.BOT, ["catalog.json", ".github/CODEOWNERS", ST, PR]), []
        )

    def test_needs_catalog(self):
        self.assertTrue(g.check_release_pr("catalog/sync", g.BOT, [".github/CODEOWNERS"]))

    def test_other_files_rejected(self):
        self.assertTrue(g.check_release_pr("catalog/sync", g.BOT, ["catalog.json", "registry.cue"]))
        self.assertTrue(g.check_release_pr("catalog/sync", g.BOT, ["catalog.json", "schema/render.cue"]))


if __name__ == "__main__":
    unittest.main()

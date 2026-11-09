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
    "registry.cue": 'import notesapi "x/apps/notes/notes-api:notesapi"\nimport a "x/clusters/alpha-01:alpha01"\n',
    "apps/notes/notes-api/app.cue": 'app: {\n\tname: "notes-api"\n\tteam: "notes"\n}\n',
    "apps/notes/notes-api/staging.json": "{}",
    "apps/notes/notes-api/prod.json": "{}",
    "clusters/alpha-01/cluster.cue": "",
    "clusters/alpha-01/releases.json": "{}",
}


class Layout(unittest.TestCase):
    def run_layout(self, files):
        with tempfile.TemporaryDirectory() as d:
            tree(pathlib.Path(d), files)
            return g.check_layout(pathlib.Path(d))

    def test_good(self):
        self.assertEqual(self.run_layout(GOOD), [])

    def test_missing_file(self):
        f = dict(GOOD)
        del f["apps/notes/notes-api/prod.json"]
        self.assertTrue(self.run_layout(f))

    def test_not_registered(self):
        f = dict(GOOD, **{"registry.cue": "import a \"x/clusters/alpha-01:alpha01\"\n"})
        self.assertTrue(self.run_layout(f))

    def test_name_mismatch(self):
        f = dict(GOOD, **{"apps/notes/notes-api/app.cue": 'app: {name: "other", team: "notes"}\n'})
        self.assertTrue(self.run_layout(f))

    def test_json_must_be_object(self):
        f = dict(GOOD, **{"apps/notes/notes-api/staging.json": "[]"})
        self.assertTrue(self.run_layout(f))


class Artifacts(unittest.TestCase):
    def test_collects_released_only(self):
        files = dict(GOOD)
        files[ST] = json.dumps({"version": "v1.2.0", "digest": D})
        files["clusters/alpha-01/releases.json"] = json.dumps(
            {"rbac": {"version": "0123456789abcdef", "digest": D}, "system": {}}
        )
        apps = {"notes/notes-api": {"repo": "homelab-selfuryon/notes-api"}}
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            tree(root, files)
            got = g.artifacts(root, [ST, PR, "clusters/alpha-01/releases.json"], apps)
        self.assertEqual(
            [(a["artifact"], a["tag"], a["workflow"]) for a in got],
            [
                ("ghcr.io/homelab-selfuryon/notes-api/manifests", "v1.2.0", "app-release"),
                ("ghcr.io/homelab-selfuryon/platform-components/alpha-01-rbac", "0123456789abcdef", "components-release"),
            ],
        )
        self.assertEqual(got[0]["repo"], "homelab-selfuryon/notes-api")




REG = ["registry.cue", "apps/notes/new-app/app.cue", "apps/notes/new-app/staging.json", "apps/notes/new-app/prod.json"]


class Register(unittest.TestCase):
    def test_devenv_update(self):
        self.assertEqual(g.check_release_pr("chore/devenv-update", g.BOT, ["devenv.lock"]), [])
        self.assertTrue(g.check_release_pr("chore/devenv-update", g.BOT, ["devenv.lock", "devenv.nix"]))

    def test_register_ok(self):
        self.assertEqual(g.check_release_pr("register/new-app", g.BOT, REG), [])

    def test_register_extra_file(self):
        self.assertTrue(g.check_release_pr("register/new-app", g.BOT, REG + ["schema/render.cue"]))

    def test_register_missing_file(self):
        self.assertTrue(g.check_release_pr("register/new-app", g.BOT, REG[:-1]))

    def test_register_other_app(self):
        self.assertTrue(g.check_release_pr("register/other", g.BOT, REG))

    def test_register_two_teams(self):
        self.assertTrue(g.check_release_pr("register/new-app", g.BOT, REG + ["apps/other/new-app/app.cue"]))

    def test_registrations(self):
        files = dict(GOOD)
        apps = {"notes/notes-api": {"team": "notes", "repo": "homelab-selfuryon/notes-api"}}
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            tree(root, files)
            got = g.registrations(root, ["apps/notes/notes-api/app.cue", ST, "registry.cue"], apps)
        self.assertEqual(got, [{"file": "apps/notes/notes-api/app.cue", "team": "notes", "repo": "homelab-selfuryon/notes-api"}])


if __name__ == "__main__":
    unittest.main()

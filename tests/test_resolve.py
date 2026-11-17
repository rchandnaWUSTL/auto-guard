"""Offline tests for argument resolution: variables, ~, symlinks, globs and cd drift."""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoguard.guard import decide  # noqa: E402
from autoguard.policy import DEFAULTS  # noqa: E402
from autoguard.resolve import resolve  # noqa: E402


class ResolveTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.home = self.root / "home"
        (self.home / ".aws").mkdir(parents=True)
        self.proj = self.root / "proj"
        (self.proj / "src").mkdir(parents=True)
        (self.proj / "src" / "a.py").write_text("")
        (self.proj / "build").symlink_to(self.home / ".aws")
        self.env = {"HOME": str(self.home), "OUT_DIR": str(self.home / ".aws")}

    def tearDown(self):
        shutil.rmtree(self.root)

    def text(self, cmd):
        return resolve(cmd, cwd=str(self.proj), env=self.env).as_text()

    def test_symlink_is_followed(self):
        self.assertIn("build/ -> ~/.aws (symlink, outside the working directory)", self.text("rm -rf build/"))
        (self.home / ".aws" / "x").write_text("")
        self.assertIn("build/x -> ~/.aws/x (symlink, outside the working directory)", self.text("cat build/x"))

    def test_glob_reaches_through_symlink(self):
        (self.home / ".aws" / "credentials").write_text("k")
        (self.home / ".aws" / ".hidden").write_text("")
        text = self.text("rm -rf build/*")
        self.assertIn("build/* matches 1 path(s)", text)  # dotfiles aren't matched by *, as in the shell
        self.assertIn("credentials -> ~/.aws/credentials (symlink, outside the working directory)", text)

    def test_glob_with_trailing_slash_follows_links(self):
        (self.proj / "notes.txt").write_text("")
        text = self.text("rm -rf */")
        self.assertIn("*/ matches 2 path(s)", text)  # folders only: build and src, not notes.txt
        self.assertIn("build/ -> ~/.aws (symlink, outside the working directory)", text)
        self.assertIn("rm removes only the link", self.text("rm -rf *"))

    def test_rm_of_a_symlink_removes_only_the_link(self):
        res = resolve("rm -rf build", cwd=str(self.proj), env=self.env)
        self.assertEqual(res.as_text(), "Resolved on disk: build is a symlink to ~/.aws; rm removes only the link")
        t = res.targets[0]
        self.assertTrue(t.link_only)
        self.assertTrue(t.inside)
        self.assertEqual(t.files, [str(self.proj / "build")])

    def test_structured_output_lists_hops_and_files(self):
        (self.home / ".aws" / "credentials").write_text("k")
        t = resolve("rm -rf build/", cwd=str(self.proj), env=self.env).targets[0]
        self.assertEqual(t.lands, str(self.home / ".aws"))
        self.assertEqual(t.hops, [{"link": str(self.proj / "build"), "to": str(self.home / ".aws")}])
        self.assertFalse(t.inside)
        self.assertEqual(t.files, [str(self.home / ".aws" / "credentials")])

    def test_symlink_loop_stops(self):
        (self.proj / "a").symlink_to("b")
        (self.proj / "b").symlink_to("a")
        res = resolve("rm -rf a/", cwd=str(self.proj), env=self.env)
        self.assertTrue(res.targets[0].loop)
        self.assertIn("symlink loop", res.as_text())

    def test_variable_is_expanded(self):
        self.assertIn("$OUT_DIR -> ~/.aws (outside the working directory)", self.text('rm -rf "$OUT_DIR"'))

    def test_unknown_variable_is_reported(self):
        res = resolve('rm -rf "$MYSTERY"', cwd=str(self.proj), env=self.env)
        self.assertEqual(res.unresolved, ["$MYSTERY"])

    def test_command_substitution_is_reported(self):
        res = resolve('eval "$(echo x | base64 -d)"', cwd=str(self.proj), env=self.env)
        self.assertIn("command substitution ($(...) or backticks)", res.unresolved)

    def test_cd_changes_where_paths_resolve(self):
        text = self.text("cd .. && rm -rf *")
        self.assertIn("cd .. ->", text)
        self.assertIn("* matches 2 path(s)", text)

    def test_ordinary_paths_add_nothing(self):
        for cmd in ("rm -rf src/a.py", "ls -la src", "git status", "rm -rf ./dist"):
            self.assertEqual(self.text(cmd), "", cmd)

    def test_unparseable_command(self):
        self.assertIn("command could not be parsed", resolve("echo 'unterminated", cwd=str(self.proj), env=self.env).unresolved)

    def test_unresolved_destructive_call_escalates(self):
        answers = {
            "destructive": {"noul": 0.9}, "in_scope": {"noul": 0.9}, "sensitive": {"noul": 0.1},
            "action_class": {"choice": "destructive", "confidence": 1}, "risk": {"score": 1.5, "confidence": 0.9},
        }
        self.assertEqual(decide(answers, DEFAULTS)[0], "allow")
        action, reasons = decide(answers, DEFAULTS, ["$MYSTERY"])
        self.assertEqual(action, "escalate")
        self.assertIn("$MYSTERY", reasons[-1])


class ConfinedTest(unittest.TestCase):
    """With root=, the fixture folder acts as "/" and nothing outside it is read."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        (self.root / "home/dev/.aws").mkdir(parents=True)
        (self.root / "home/dev/.aws/credentials").write_text("k")
        self.repo = self.root / "home/dev/repo"
        self.repo.mkdir()
        (self.repo / "build").symlink_to("../.aws")
        (self.repo / "abs").symlink_to("/home/dev/.aws")  # absolute: means the fixture's /home, not the server's
        (self.repo / "etc").symlink_to("/etc")
        self.env = {"HOME": "/home/dev"}

    def tearDown(self):
        shutil.rmtree(self.root)

    def run_(self, cmd, env=None):
        return resolve(cmd, cwd="/home/dev/repo", env=self.env if env is None else env, root=str(self.root))

    def test_paths_are_shown_inside_the_fixture(self):
        res = self.run_("rm -rf build/*")
        self.assertIn("credentials -> ~/.aws/credentials (symlink, outside the working directory)", res.as_text())
        self.assertNotIn(str(self.root), repr(res.to_dict()))

    def test_absolute_symlink_stays_in_the_fixture(self):
        t = self.run_("rm -rf abs/").targets[0]
        self.assertEqual(t.lands, "/home/dev/.aws")
        self.assertEqual(t.files, ["/home/dev/.aws/credentials"])

    def test_server_paths_are_never_read(self):
        for cmd in ("ls /etc", "cat etc/hosts", "cat ../../../../../etc/hosts", "ls /*", "rm -rf /etc/"):
            res = self.run_(cmd)
            for t in res.targets:
                self.assertTrue(os.path.lexists(os.path.join(str(self.root), t.lands.lstrip("/"))), cmd)
            self.assertNotIn("hosts", res.as_text(), cmd)

    def test_dotdot_stops_at_the_fixture_root(self):
        t = self.run_("rm -rf ../../../../../home/").targets[0]
        self.assertEqual(t.lands, "/home")

    def test_process_environment_is_not_used(self):
        os.environ["AUTOGUARD_TEST_SECRET"] = "/home/dev/.aws"
        try:
            res = self.run_("rm -rf $AUTOGUARD_TEST_SECRET/", env={})
        finally:
            del os.environ["AUTOGUARD_TEST_SECRET"]
        self.assertEqual(res.unresolved, ["$AUTOGUARD_TEST_SECRET"])
        self.assertEqual(res.targets, [])

    def test_glob_scan_is_capped(self):
        many = self.root / "home/dev/repo/many"
        many.mkdir()
        for i in range(6000):
            (many / ("f%d" % i)).touch()
        res = self.run_("rm many/*")
        self.assertIn("matches at least", res.as_text())
        self.assertLessEqual(len(res.targets), 20)


if __name__ == "__main__":
    unittest.main()

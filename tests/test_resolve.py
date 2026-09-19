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
        self.assertIn("build -> ~/.aws (symlink, outside the working directory)", self.text("rm -rf build"))

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


if __name__ == "__main__":
    unittest.main()

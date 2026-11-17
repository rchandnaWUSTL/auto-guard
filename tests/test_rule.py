"""Offline tests for the outside-the-folder rule and its wiring into guard()."""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoguard import jev  # noqa: E402
from autoguard.guard import guard  # noqa: E402
from autoguard.resolve import resolve  # noqa: E402
from autoguard.rule import check, sensitive  # noqa: E402

HOME = "/home/dev"


class SensitiveTest(unittest.TestCase):
    def test_listed_paths_and_their_parents(self):
        for p in ("/home/dev/.aws", "/home/dev/.aws/credentials", "/home/dev/.ssh/id_ed25519",
                  "/home/dev/.config", "/home/dev/.config/gcloud/x.json", "/home/dev/.docker/config.json",
                  "/home/dev/.docker", "/home/dev/Library/Keychains/login.keychain-db"):
            self.assertIsNotNone(sensitive(p, HOME), p)

    def test_home_and_above(self):
        for p in ("/home/dev", "/home/dev/", "/home", "/"):
            self.assertIsNotNone(sensitive(p, HOME), p)

    def test_env_files_anywhere(self):
        for p in ("/home/dev/other-app/.env", "/srv/app/.env.production", "/home/dev/x/.envrc"):
            self.assertEqual(sensitive(p, HOME), "an .env file", p)

    def test_paths_added_after_round_2(self):
        for p in ("/home/dev/.terraform.d/credentials.tfrc.json", "/home/dev/.terraform.d",
                  "/home/dev/.cargo/credentials.toml", "/home/dev/.local/share/mkcert/rootCA-key.pem",
                  "/home/dev/.password-store/work/github.gpg", "/home/dev/.secrets/webapp.env",
                  "/srv/app/production.env"):
            self.assertIsNotNone(sensitive(p, HOME), p)

    def test_ordinary_paths(self):
        for p in ("/home/dev/other-app/build", "/home/dev/.cache/pip", "/home/dev/Documents/notes.txt",
                  "/tmp/x", "/home/dev/.config/nvim/init.lua", "/home/dev/.docker/buildx",
                  "/home/dev/.cargo/registry", "/home/dev/.terraform.d/plugin-cache/x"):
            self.assertIsNone(sensitive(p, HOME), p)

    def test_extra_paths(self):
        self.assertIsNotNone(sensitive("/home/dev/.config/stripe/config.toml", HOME, [".config/stripe"]))


class RuleTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        r = Path(self.root)
        (r / "home/dev/.aws").mkdir(parents=True)
        (r / "home/dev/.aws/credentials").write_text("k")
        (r / "home/dev/other-app/build").mkdir(parents=True)
        (r / "home/dev/repo/out").mkdir(parents=True)
        (r / "home/dev/repo/config.example").write_text("x")
        (r / "tmp").mkdir()
        (r / "home/dev/repo/build").symlink_to("../.aws")
        (r / "home/dev/repo/dist").symlink_to("out")
        (r / "home/dev/repo/other").symlink_to("../other-app")
        (r / "home/dev/.pypirc").write_text("token")
        (r / "home/dev/repo/.pypirc").symlink_to("../.pypirc")

    def tearDown(self):
        shutil.rmtree(self.root)

    def rule(self, cmd):
        return check(resolve(cmd, cwd="/home/dev/repo", env={"HOME": HOME}, root=self.root))

    def test_blocks_writes_that_reach_secrets(self):
        for cmd in ("rm -rf build/*", "rm -rf build/", "cp config.example build/config", "echo x > build/new",
                    "touch build/.keep", "find build/ -delete", "cd .. && rm -rf .aws", "rm -rf ~/.aws",
                    "cd ../.. && rm -rf dev", "chmod -R 777 build/", "find -L build -delete",
                    "sed -i --follow-symlinks s/a/b/ build/credentials", "mv config.example build"):
            self.assertEqual((self.rule(cmd) or ("none",))[0], "block", cmd)

    def test_escalates_other_writes_outside(self):
        for cmd in ("rm -rf other/build", "rm -rf ../other-app/build", "touch /tmp/x", "mv out ../moved"):
            self.assertEqual((self.rule(cmd) or ("none",))[0], "escalate", cmd)

    def test_leaves_the_rest_to_the_model(self):
        for cmd in ("rm -rf build", "rm -rf dist/", "rm -rf out", "ls build/", "cat build/credentials",
                    "cp build/credentials backup", "find build/ -name x", "rm -rf $OUT/", "ls 2>/dev/null",
                    "find build -mindepth 1 -delete", "sed -i s/a/b/ build", "mv .pypirc .pypirc.bak",
                    "rm -rf ../does-not-exist"):
            self.assertIsNone(self.rule(cmd), cmd)


class GuardRuleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(self.home, ".aws"))
        Path(self.home, ".aws", "credentials").write_text("k")
        self.repo = os.path.join(self.home, "repo")
        os.makedirs(self.repo)
        os.symlink("../.aws", os.path.join(self.repo, "build"))
        self.env = mock.patch.dict(os.environ, {"AUTOGUARD_LOG": self.tmp + "/log.jsonl", "HOME": self.home})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp)

    def test_rule_decides_without_calling_jev(self):
        with mock.patch.object(jev, "ask") as ask:
            d = guard("Bash", "rm -rf build/*", cwd=self.repo, explain=False)
        ask.assert_not_called()
        self.assertEqual((d.action, d.decided_by, d.cost), ("block", "rule", 0.0))
        self.assertLess(d.latency_ms, 50)

    def test_rule_can_be_turned_off(self):
        fake = {"answers": {}, "latency_ms": 1, "cost": 0, "model": "m", "provider": "p"}
        with mock.patch.object(jev, "ask", return_value=fake) as ask, \
                mock.patch.object(sys.modules["autoguard.guard"], "decide", return_value=("allow", [])):
            d = guard("Bash", "rm -rf build/*", cwd=self.repo, explain=False, policy={"outside_rule": False})
        ask.assert_called_once()
        self.assertEqual(d.decided_by, "jev")


if __name__ == "__main__":
    unittest.main()

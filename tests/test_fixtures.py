"""Offline tests for the fixture builder and the indirection case file."""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autoguard.fixtures import FixtureError, build, load_library  # noqa: E402

CASES = ROOT / "evals" / "indirection" / "cases.jsonl"


def _split_module():
    spec = importlib.util.spec_from_file_location("split", ROOT / "evals" / "indirection" / "split.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class BuilderTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_builds_files_dirs_and_links(self):
        lib = {"f": {"ops": [{"file": "/home/dev/.aws/credentials", "text": "k"},
                             {"dir": "/home/dev/repo"},
                             {"link": "/home/dev/repo/build", "to": "../.aws"}]}}
        self.assertEqual(build("f", self.root, lib), ["/home"])
        link = os.path.join(self.root, "home/dev/repo/build")
        self.assertEqual(os.readlink(link), "../.aws")
        self.assertEqual(Path(link, "credentials").read_text(), "k")

    def test_extends_applies_the_base_first(self):
        lib = {"base": {"ops": [{"file": "/a/x", "text": "1"}]},
               "child": {"extends": "base", "ops": [{"file": "/a/x", "text": "2"}]}}
        build("child", self.root, lib)
        self.assertEqual(Path(self.root, "a/x").read_text(), "2")

    def test_refuses_paths_that_could_leave_the_root(self):
        for op in ({"file": "relative/x"}, {"file": "/a/../../x"}, {"dir": "/a/.."}, {"link": "x", "to": "/"}):
            with self.assertRaises(FixtureError, msg=op):
                build({"ops": [op]}, self.root, {})

    def test_refuses_to_write_through_a_symlink(self):
        outside = tempfile.mkdtemp()
        try:
            lib = {"f": {"ops": [{"link": "/escape", "to": outside}, {"file": "/escape/x", "text": "pwned"}]}}
            with self.assertRaises(FixtureError):
                build("f", self.root, lib)
            self.assertEqual(os.listdir(outside), [])
        finally:
            shutil.rmtree(outside)

    def test_extends_loop_is_an_error(self):
        with self.assertRaises(FixtureError):
            build("a", self.root, {"a": {"extends": "b"}, "b": {"extends": "a"}})

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_git_clone_keeps_symlinks(self):
        lib = {"f": {"ops": [{"git_clone": {"to": "/home/dev/tool", "files": {"README.md": "hi"},
                                            "links": {"build": "../.aws"}}}]}}
        self.assertEqual(build("f", self.root, lib), ["/home", "/srv"])
        clone = Path(self.root, "home/dev/tool")
        self.assertEqual(os.readlink(clone / "build"), "../.aws")
        self.assertTrue((clone / ".git").is_dir())
        self.assertTrue(Path(self.root, "srv/git/tool.git").is_dir())


class CaseFileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = [json.loads(l) for l in CASES.read_text().splitlines() if l.strip()]
        cls.library = load_library()
        cls.tmp = tempfile.mkdtemp()
        cls.built = {}
        for name in {c["fixture"] for c in cls.cases}:
            path = os.path.join(cls.tmp, name)
            os.mkdir(path)
            build(name, path, cls.library)
            cls.built[name] = path

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_fields_are_valid(self):
        ids = [c["id"] for c in self.cases]
        self.assertEqual(len(ids), len(set(ids)), "duplicate ids")
        for c in self.cases:
            self.assertIn(c["family"], {"symlink", "glob", "variable", "cd", "other"}, c["id"])
            self.assertIn(c["label"], {"dangerous", "safe"}, c["id"])
            self.assertIn(c["split"], {"dev", "holdout", "external"}, c["id"])
            self.assertIn(c["fixture"], self.library, c["id"])
            self.assertTrue(c["task"] and c["command"] and c["why"], c["id"])
            self.assertNotIn("HOME", c["env"], c["id"])  # HOME is always /home/dev

    def test_working_folders_exist(self):
        for c in self.cases:
            cwd = os.path.join(self.built[c["fixture"]], c["cwd"].lstrip("/"))
            self.assertTrue(os.path.isdir(cwd) and not os.path.islink(cwd), c["id"])

    def test_split_follows_the_hash_rule(self):
        splits = _split_module().assign(self.cases)
        for c in self.cases:
            self.assertEqual(c["split"], splits[c["id"]], c["id"])
        mine = [c for c in self.cases if c["split"] != "external"]
        held = sum(c["split"] == "holdout" for c in mine)
        self.assertAlmostEqual(held / len(mine), 0.3, delta=0.05)


if __name__ == "__main__":
    unittest.main()

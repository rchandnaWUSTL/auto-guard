"""Build a pretend computer ("fixture") from a written description, for evals and the playground.

A fixture is a list of operations on absolute paths. They're applied under `root`, which acts
as "/": the eval builds fixtures in a temp folder and checks them with the confined resolver
(`resolve(..., root=)`), and the ground-truth run builds them at the real "/" inside a throwaway
container. Symlinks are written exactly as given, so an absolute target means the fixture's "/".

Operations:
    {"dir": "/home/dev/repo/src"}
    {"file": "/home/dev/.aws/credentials", "text": "fake-key"}
    {"link": "/home/dev/repo/build", "to": "../.aws"}
    {"git_clone": {"to": "/home/dev/repo", "files": {"README.md": "hi"}, "links": {"build": "../.aws"}}}

A fixture can start from another with "extends". Nothing here ever writes through a symlink,
so a fixture can't reach outside `root`.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_LIBRARY = Path(__file__).resolve().parent.parent / "evals" / "indirection" / "fixtures.json"


class FixtureError(ValueError):
    pass


def load_library(path=None):
    return json.loads(Path(path or DEFAULT_LIBRARY).read_text())


def ops_for(spec, library):
    """The full operation list for a fixture name or spec, with `extends` applied first."""
    seen = []
    ops = []

    def add(s):
        if isinstance(s, str):
            if s in seen:
                raise FixtureError("fixture extends itself: " + " -> ".join(seen + [s]))
            if s not in library:
                raise FixtureError("unknown fixture: " + s)
            seen.append(s)
            s = library[s]
        if s.get("extends"):
            add(s["extends"])
        ops.extend(s.get("ops", []))

    add(spec)
    return ops


def _check(vpath):
    if not isinstance(vpath, str) or not vpath.startswith("/") or ".." in vpath.split("/"):
        raise FixtureError("fixture paths must be absolute and can't contain '..': %r" % (vpath,))
    return vpath


def _real(root, vpath):
    return os.path.join(root, _check(vpath).lstrip("/"))


def _safe_parent(root, vpath):
    """Create vpath's parent folders, refusing to go through any symlink on the way."""
    cur = root
    for part in [p for p in vpath.split("/") if p][:-1]:
        cur = os.path.join(cur, part)
        if os.path.islink(cur):
            raise FixtureError("won't write through the symlink at %s" % cur[len(root):] or "/")
        if not os.path.isdir(cur):
            os.mkdir(cur)


def _clear(path):
    if os.path.islink(path) or os.path.isfile(path):
        os.unlink(path)
    elif os.path.isdir(path):
        raise FixtureError("%s already exists as a folder" % path)


def _git(args, cwd, home):
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": home,
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
    }
    subprocess.run(["git"] + args, cwd=cwd, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _git_clone(root, op):
    """Commit files and symlinks to a local bare repo under /srv/git, then clone it. No network."""
    to = _check(op["to"])
    name = op.get("name") or to.rstrip("/").rsplit("/", 1)[-1]
    bare_v = "/srv/git/%s.git" % name
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "src")
        os.mkdir(src)
        for rel, text in sorted(op.get("files", {}).items()):
            _check("/" + rel)
            _safe_parent(src, "/" + rel)
            Path(src, rel).write_text(text)
        for rel, target in sorted(op.get("links", {}).items()):
            _check("/" + rel)
            _safe_parent(src, "/" + rel)
            os.symlink(target, os.path.join(src, rel))
        _git(["init", "-q", "-b", "main"], src, tmp)
        _git(["add", "-A"], src, tmp)
        _git(["commit", "-q", "-m", "fixture"], src, tmp)
        _safe_parent(root, bare_v)
        _git(["clone", "-q", "--bare", src, _real(root, bare_v)], tmp, tmp)
    _safe_parent(root, to)
    _git(["clone", "-q", _real(root, bare_v), _real(root, to)], root, root)


def build(spec, root, library=None):
    """Create the fixture under `root` (an existing folder). Returns the top-level folders it used."""
    library = load_library() if library is None else library
    root = os.path.realpath(root)
    if not os.path.isdir(root):
        raise FixtureError("root folder doesn't exist: " + root)
    tops = set()
    for op in ops_for(spec, library):
        kind = next((k for k in ("dir", "file", "link", "git_clone") if k in op), None)
        vpath = op["git_clone"]["to"] if kind == "git_clone" else op.get(kind)
        _check(vpath)
        tops.add("/" + vpath.strip("/").split("/")[0])
        real = _real(root, vpath)
        _safe_parent(root, vpath)
        if kind == "dir":
            if os.path.islink(real):
                raise FixtureError("won't write through the symlink at " + vpath)
            os.makedirs(real, exist_ok=True)
        elif kind == "file":
            _clear(real)
            Path(real).write_text(op.get("text", ""))
        elif kind == "link":
            _clear(real)
            os.symlink(op["to"], real)
        elif kind == "git_clone":
            _git_clone(root, op["git_clone"])
            tops.add("/srv")
        else:
            raise FixtureError("unknown fixture operation: %r" % (op,))
    return sorted(tops)


if __name__ == "__main__":
    # python3 fixtures.py build NAME ROOT [--library PATH]   (used inside the ground-truth containers)
    args = sys.argv[1:]
    lib = None
    if "--library" in args:
        i = args.index("--library")
        lib = load_library(args[i + 1])
        del args[i:i + 2]
    if len(args) != 3 or args[0] != "build":
        sys.exit("usage: fixtures.py build NAME ROOT [--library PATH]")
    print(" ".join(build(args[1], args[2], lib)))

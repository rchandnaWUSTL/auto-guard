"""Resolve what a shell command will actually touch before Jev judges it.

The model proposes a string, but the shell runs something derived from it: variables
expand, ~ becomes a home directory, relative paths resolve against the working
directory, globs expand, and symlinks lead elsewhere. This module does those steps
read-only (nothing is executed) and reports what it found, plus anything it can't see.

Paths are walked one component at a time, the way the kernel does it, so every symlink
on the way is recorded. Pass `root` to confine the walk to a fixture folder: the folder
is then treated as "/" (like a chroot), absolute symlinks and `..` can't leave it, and
the environment comes only from `env`, never from this process.
"""

import fnmatch
import os
import re
import shlex
from dataclasses import asdict, dataclass, field

_VAR = re.compile(r"\$(\{([A-Za-z_][A-Za-z0-9_]*)[^}]*\}|([A-Za-z_][A-Za-z0-9_]*))")
_SUBST = re.compile(r"\$\(|`")
_MAGIC = re.compile(r"[*?\[]")
_OPS = {"&&", "||", ";", "|", "&", "(", ")", ";;"}
# rm and unlink act on a symlink itself unless the path ends in "/" (or a glob reaches through it).
_LINK_ONLY = {"rm", "unlink"}

# Which arguments a command writes to or deletes. Everything else is treated as read-only.
WRITE_ALL = {"rm", "unlink", "rmdir", "shred", "mv", "touch", "truncate", "chmod", "chown", "chgrp", "tee", "mkdir"}
WRITE_LAST = {"cp", "install", "ln"}          # only the destination (the last path) is written
CREATES = {"touch", "mkdir", "tee", "truncate"}   # can create a path that doesn't exist yet (plus cp/install/ln/mv targets)
_WRAPPERS = {"sudo", "command", "nice", "nohup", "time", "env"}   # the real program is the next word
_REDIRECTS = {">", ">>", ">|", "&>", "&>>"}
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

MAX_NOTES = 12
MAX_HOPS = 40          # symlinks followed for one path before calling it a loop (Linux uses 40)
MAX_SCAN = 5000        # directory entries read across all globs in one command
MAX_MATCHES = 20       # glob matches reported per argument
MAX_FILES = 10         # files listed under a directory an rm would delete
MAX_WALK = 2000        # entries visited while listing those files


@dataclass
class Target:
    arg: str            # the argument as typed
    path: str           # where it points before symlinks, as an absolute path
    lands: str          # where it really lands
    hops: list = field(default_factory=list)   # [{"link": path, "to": readlink text}, ...]
    inside: bool = True                         # lands inside the working directory
    link_only: bool = False                     # rm removes the symlink itself, not its target
    points_to: str = ""                         # for link_only: where that link leads (left untouched)
    files: list = field(default_factory=list)  # what an rm would delete (capped at MAX_FILES)
    more_files: bool = False                    # there were more than MAX_FILES
    loop: bool = False                          # symlink chain too long to follow
    prog: str = ""                              # the program this argument belongs to ("" for a redirect)
    write: bool = False                         # the command writes to or deletes this path (see WRITERS)
    new: bool = False                           # doesn't exist yet; resolved through its parent folder


@dataclass
class Resolution:
    notes: list = field(default_factory=list)       # what the command really points at
    unresolved: list = field(default_factory=list)  # things Auto-Guard can't see
    targets: list = field(default_factory=list)     # structured version, one Target per path argument
    cwd: str = ""                                   # the working folder, resolved
    home: str = ""                                  # the home folder, resolved

    def as_text(self):
        lines = []
        if self.notes:
            lines.append("Resolved on disk: " + "; ".join(self.notes[:MAX_NOTES]))
        if self.unresolved:
            lines.append("Can't be resolved before running: " + "; ".join(self.unresolved[:MAX_NOTES]))
        return "\n".join(lines)

    def to_dict(self):
        return asdict(self)


def _join(base, part):
    return part if part.startswith("/") else base.rstrip("/") + "/" + part


class _FS:
    """Read-only path walking under `root`. Every path handled here is virtual (absolute, "/"-rooted)."""

    def __init__(self, root):
        self.root = os.path.realpath(root)
        self.scanned = 0

    def real(self, vpath):
        # Only ever called with walked paths, which contain no ".." or symlinks.
        return os.path.join(self.root, vpath.lstrip("/")) if self.root != "/" else vpath

    def walk(self, vpath, follow_last=True):
        """Resolve symlinks along vpath. Returns (resolved, hops, loop)."""
        todo = [p for p in vpath.split("/") if p][::-1]
        cur, hops, loop = "/", [], False
        while todo:
            part = todo.pop()
            if part == ".":
                continue
            if part == "..":
                cur = cur.rsplit("/", 1)[0] or "/"
                continue
            nxt = _join(cur, part)
            real = self.real(nxt)
            if (todo or follow_last) and os.path.islink(real):
                if len(hops) >= MAX_HOPS:
                    loop = True
                    cur = nxt
                    continue
                target = os.readlink(real)
                hops.append({"link": nxt, "to": target})
                if target.startswith("/"):
                    cur = "/"
                todo.extend([p for p in target.split("/") if p][::-1])
                continue
            cur = nxt
        return cur, hops, loop

    def lexists(self, vpath):
        resolved, _, _ = self.walk(vpath, follow_last=False)
        return os.path.lexists(self.real(resolved))

    def isdir(self, vpath):
        resolved, _, loop = self.walk(vpath)
        return not loop and os.path.isdir(self.real(resolved))

    def glob(self, pattern):
        """Shell-style glob of an absolute virtual pattern. Returns (matches, truncated)."""
        parts = [p for p in pattern.split("/") if p]
        paths, truncated = ["/"], False
        for part in parts:
            if not _MAGIC.search(part):
                paths = [_join(p, part) for p in paths]
                continue
            found = []
            for p in paths:
                if not self.isdir(p):
                    continue
                resolved, _, _ = self.walk(p)
                try:
                    with os.scandir(self.real(resolved)) as entries:
                        for entry in entries:
                            self.scanned += 1
                            if self.scanned > MAX_SCAN:
                                truncated = True
                                break
                            if entry.name.startswith(".") and not part.startswith("."):
                                continue
                            if fnmatch.fnmatchcase(entry.name, part):
                                found.append(_join(p, entry.name))
                except OSError:
                    continue
            paths = sorted(found)
        paths = [p for p in paths if self.lexists(p)]
        if pattern.endswith("/"):  # a trailing slash only matches folders (or links to them)
            paths = [p for p in paths if self.isdir(p)]
        return paths, truncated

    def files_under(self, vpath):
        """Up to MAX_FILES paths an `rm -r` of this resolved path would delete. rm never follows links inside."""
        real = self.real(vpath)
        if not os.path.isdir(real) or os.path.islink(real):
            return ([vpath] if os.path.lexists(real) else []), False
        files, seen = [], 0
        for dirpath, dirnames, filenames in os.walk(real):
            dirnames.sort()
            for name in sorted(filenames) + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]:
                seen += 1
                if seen > MAX_WALK or len(files) >= MAX_FILES:
                    return files, True
                rel = os.path.relpath(os.path.join(dirpath, name), real)
                files.append(_join(vpath, rel))
        return files, False


def _expand_vars(token, env, res):
    def sub(m):
        name = m.group(2) or m.group(3)
        if name in env:
            return env[name]
        if ("$" + name) not in res.unresolved:
            res.unresolved.append("$" + name)
        return m.group(0)
    return _VAR.sub(sub, token)


def _looks_like_path(token):
    return token in (".", "..", "*") or "/" in token or token.startswith("~") or bool(_MAGIC.search(token))


def resolve(command, cwd=None, env=None, root=None):
    """Read-only resolution of a shell command's arguments. Returns a Resolution.

    With `root`, `cwd` and every path are inside that folder (it acts as "/"), and only
    `env` is used for variables.
    """
    res = Resolution()
    if root is None:
        fs = _FS("/")
        env = dict(os.environ if env is None else env)
        home = env.get("HOME", os.path.expanduser("~"))
        cwd = os.path.abspath(cwd or os.getcwd())
    else:
        fs = _FS(root)
        env = dict(env or {})
        home = env.get("HOME", "/")
        cwd = "/" + (cwd or "/").strip("/")
    cwd, _, _ = fs.walk(cwd)
    home, _, _ = fs.walk(home.rstrip("/") or "/")
    res.cwd, res.home = cwd, home

    def shown(vpath):
        if home != "/" and (vpath == home or vpath.startswith(home + "/")):
            return "~" + vpath[len(home):]
        return vpath

    def inside(vpath):
        return vpath == cwd or vpath.startswith(cwd.rstrip("/") + "/")

    def describe(label, t, expanded, verb=""):
        """A note for this target, or None if it's an ordinary path inside the working directory."""
        if t.link_only:
            return "%s is a symlink to %s; %s removes only the link%s" % (
                label, shown(t.points_to), verb, "" if t.inside else " (outside the working directory)")
        bits = []
        if t.hops:
            bits.append("symlink")
        if t.loop:
            bits.append("symlink loop")
        if not t.inside:
            bits.append("outside the working directory")
        if not bits and not expanded:
            return None
        return "%s -> %s%s" % (label, shown(t.lands), " (%s)" % ", ".join(bits) if bits else "")

    def target(raw, vpath, prog, link_only=None):
        if link_only is None:
            link_only = prog in _LINK_ONLY and not raw.endswith("/")
        lands, hops, loop = fs.walk(vpath, follow_last=not link_only)
        t = Target(arg=raw, path=vpath, lands=lands, hops=hops, loop=loop)
        t.inside = inside(lands)
        if link_only and os.path.islink(fs.real(lands)):
            t.link_only = True
            t.points_to, t.hops, t.loop = fs.walk(lands)
            t.files = [lands]
        elif prog in _LINK_ONLY and not loop:
            t.files, t.more_files = fs.files_under(lands)
        return t

    if _SUBST.search(command):
        res.unresolved.append("command substitution ($(...) or backticks)")

    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        res.unresolved.append("command could not be parsed")
        return res

    def writes(prog, words, idx):
        """Is the path at position idx (in this command's words, program excluded) written to?"""
        if prog in WRITE_ALL:
            return True
        if prog in WRITE_LAST:
            paths = [i for i, w in enumerate(words) if not w.startswith("-")]
            return bool(paths) and idx == paths[-1]
        if prog == "sed":
            return any(w == "-i" or w.startswith("-i") or w.startswith("--in-place") for w in words)
        if prog == "find" and any(w in ("-delete", "-exec", "-execdir", "-ok", "-okdir") for w in words):
            first_expr = next((i for i, w in enumerate(words) if (w.startswith("-") and w not in ("-H", "-L", "-P"))
                               or w in ("(", "!")), len(words))
            return idx < first_expr
        return False

    def add(raw, token, here, expanded, prog, write, may_create=False, acts_on_link=False):
        """Resolve one argument (expanding globs) and record what it points at."""
        pattern = _join(here, token)
        is_glob = bool(_MAGIC.search(token))
        if is_glob:
            matches, truncated = fs.glob(pattern)
            if matches:
                res.notes.append("%s matches %s%d path(s) in %s" % (
                    raw, "at least " if truncated or len(matches) > MAX_MATCHES else "", len(matches), shown(here)))
            matches = matches[:MAX_MATCHES]
        else:
            matches = [pattern]
        for path in matches:
            if (path, write) in seen:
                continue
            # The shell keeps a pattern's trailing slash on each match (*/ gives logs/), and rm follows it.
            label = raw if not is_glob else path.rsplit("/", 1)[-1] + ("/" if token.endswith("/") else "")
            if fs.lexists(path):
                t = target(label, path, prog, (acts_on_link and not label.endswith("/")) or None)
            elif write and may_create and not is_glob:
                # A file the command will create: where it lands depends on its parent folder.
                parent, name = (path.rstrip("/").rsplit("/", 1) + [""])[:2]
                if not name or not fs.isdir(parent or "/"):
                    continue
                lands, hops, loop = fs.walk(parent or "/")
                t = Target(arg=label, path=path, lands=_join(lands, name), hops=hops, loop=loop, new=True)
                t.inside = inside(t.lands)
            else:
                continue
            seen.add((path, write))
            t.prog, t.write = prog, write
            res.targets.append(t)
            note = describe(label, t, expanded, prog)
            if note:
                res.notes.append(note + (" (new file)" if t.new and "(" not in note else ""))

    def finish(prog, words, args, redirects):
        paths = [i for i, w in enumerate(words) if not w.startswith("-")]
        # Like rm, these act on a symlink itself unless told to follow it: sed -i replaces the link
        # with a plain file (no --follow-symlinks), and find doesn't descend into a starting-point
        # link (no -L/-H) unless it ends in "/".
        on_link = (prog == "sed" and not any(w.startswith("--follow-symlinks") for w in words)) or \
                  (prog == "find" and not any(w in ("-L", "-H") for w in words))
        for idx, raw, token, here_, expanded in args:
            w = writes(prog, words, idx)
            last = bool(paths) and idx == paths[-1]
            link_itself = on_link and w
            if prog == "mv":
                # mv renames a symlink itself. Only a destination that leads to a folder is followed
                # (the source moves into that folder).
                link_itself = not (last and fs.isdir(_join(here_, token)))
            add(raw, token, here_, expanded, prog, w, w and (prog in CREATES or (prog in WRITE_LAST | {"mv"} and last)),
                acts_on_link=link_itself)
        for raw, token, here_, expanded in redirects:
            add(raw, token, here_, expanded, "", True, True)

    here = cwd
    prog = ""
    words, args, redirects = [], [], []
    expect_cd_target = False
    expect_redirect = False
    at_command_start = True  # the first word of each command is the program, not an argument
    seen = set()
    for raw in tokens + [";"]:
        if raw in _OPS:
            finish(prog, words, args, redirects)
            prog, words, args, redirects = "", [], [], []
            expect_cd_target = expect_redirect = False
            at_command_start = True
            continue
        if raw in _REDIRECTS or raw == ">&":
            expect_redirect = raw != ">&"
            continue
        if at_command_start:
            if _ASSIGN.match(raw) or os.path.basename(raw) in _WRAPPERS:
                continue  # FOO=bar cmd / sudo cmd: the program is still to come
            at_command_start = False
            prog = os.path.basename(raw)
            if raw == "cd":
                expect_cd_target = True
            continue
        token = _expand_vars(raw, env, res)
        if token.startswith("~"):
            token = home + token[1:]
        expanded = token != raw
        if expect_redirect:
            expect_redirect = False
            if "$" not in token and not token.isdigit() and not token.startswith("/dev/"):
                redirects.append((raw, token, here, expanded))
            continue
        if expect_cd_target:
            expect_cd_target = False
            dest = _join(here, token)
            if fs.isdir(dest):
                t = target(raw, dest, "cd")
                here = t.lands
                note = describe(raw, t, expanded)
                if note:
                    res.notes.append("cd " + note)
                    res.targets.append(t)
            continue
        idx = len(words)
        words.append(raw)
        on_disk = not token.startswith("/") and fs.lexists(_join(here, token))
        if token.startswith("-") or "$" in token:
            continue
        if not (_looks_like_path(token) or expanded or on_disk) and not (writes(prog, words, idx) and prog in WRITE_ALL | WRITE_LAST):
            continue
        args.append((idx, raw, token, here, expanded))
    return res

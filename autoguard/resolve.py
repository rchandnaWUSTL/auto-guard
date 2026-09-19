"""Resolve what a shell command will actually touch before Jev judges it.

The model proposes a string, but the shell runs something derived from it: variables
expand, ~ becomes a home directory, relative paths resolve against the working
directory, globs expand, and symlinks lead elsewhere. This module does those steps
read-only (nothing is executed) and reports what it found, plus anything it can't see.
"""

import glob
import os
import re
import shlex
from dataclasses import dataclass, field

_VAR = re.compile(r"\$(\{([A-Za-z_][A-Za-z0-9_]*)[^}]*\}|([A-Za-z_][A-Za-z0-9_]*))")
_SUBST = re.compile(r"\$\(|`")
_OPS = {"&&", "||", ";", "|", "&", "(", ")", ";;"}
MAX_NOTES = 12


@dataclass
class Resolution:
    notes: list = field(default_factory=list)       # what the command really points at
    unresolved: list = field(default_factory=list)  # things Auto-Guard can't see

    def as_text(self):
        lines = []
        if self.notes:
            lines.append("Resolved on disk: " + "; ".join(self.notes[:MAX_NOTES]))
        if self.unresolved:
            lines.append("Can't be resolved before running: " + "; ".join(self.unresolved[:MAX_NOTES]))
        return "\n".join(lines)


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
    return token in (".", "..", "*") or "/" in token or token.startswith("~") or any(c in token for c in "*?[")


def _describe(label, path, cwd, home, expanded):
    """A note for this path, or None if it's an ordinary path inside the working directory."""
    real = os.path.realpath(path)
    literal = os.path.normpath(os.path.abspath(path))
    inside = real == cwd or real.startswith(cwd.rstrip("/") + "/")
    bits = []
    if real != literal:
        bits.append("symlink")
    if not inside:
        bits.append("outside the working directory")
    if not bits and not expanded:
        return None
    shown = real.replace(home, "~", 1) if home and real.startswith(home) else real
    return "%s -> %s%s" % (label, shown, " (%s)" % ", ".join(bits) if bits else "")


def resolve(command, cwd=None, env=None):
    """Read-only resolution of a shell command's arguments. Returns a Resolution."""
    res = Resolution()
    env = dict(os.environ if env is None else env)
    cwd = os.path.realpath(cwd or os.getcwd())
    home = env.get("HOME", os.path.expanduser("~"))

    if _SUBST.search(command):
        res.unresolved.append("command substitution ($(...) or backticks)")

    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        res.unresolved.append("command could not be parsed")
        return res

    here = cwd
    expect_cd_target = False
    at_command_start = True  # the first word of each command is the program, not an argument
    seen = set()
    for raw in tokens:
        if raw in _OPS:
            expect_cd_target = False
            at_command_start = True
            continue
        if at_command_start:
            at_command_start = False
            if raw == "cd":
                expect_cd_target = True
            continue
        token = _expand_vars(raw, env, res)
        if token.startswith("~"):
            token = home + token[1:]
        expanded = token != raw
        if expect_cd_target:
            expect_cd_target = False
            target = os.path.realpath(os.path.join(here, token))
            if os.path.isdir(target):
                here = target
                note = _describe(raw, target, cwd, home, expanded)
                if note:
                    res.notes.append("cd " + note)
            continue
        on_disk = not os.path.isabs(token) and os.path.lexists(os.path.join(here, token))
        if token.startswith("-") or "$" in token or not (_looks_like_path(token) or expanded or on_disk):
            continue
        pattern = token if os.path.isabs(token) else os.path.join(here, token)
        matches = sorted(glob.glob(pattern))[:20] if any(c in token for c in "*?[") else [pattern]
        if any(c in token for c in "*?[") and matches:
            res.notes.append("%s matches %d path(s) in %s" % (raw, len(matches), here.replace(home, "~", 1)))
        for path in matches:
            if not os.path.lexists(path) or path in seen:
                continue
            seen.add(path)
            note = _describe(raw if len(matches) == 1 else os.path.basename(path), path, cwd, home, expanded)
            if note:
                res.notes.append(note)
    return res

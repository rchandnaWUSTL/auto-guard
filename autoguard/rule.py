"""The outside-the-folder rule: decide without the model when a command writes outside the working folder.

The resolver already knows where every argument really lands. When a command writes to,
deletes or creates something outside the working folder, there's nothing for a model to
weigh, so Auto-Guard decides on the spot:

    block     if any such path is sensitive (see SENSITIVE below)
    escalate  if all of them are outside the folder but not sensitive (ask the user)

Everything else (writes that stay inside, reads, anything the resolver can't see) goes to Jev
as before.

Definitions, exactly:

* "Working folder" is the agent's working directory with every symlink in it resolved.
* A path's real location is where the shell would act on it: `~` and visible variables
  expanded, relative paths joined to the folder the command runs in (after any `cd` earlier
  in the same command line), globs expanded, `..` applied after resolving the symlinks before
  it (as the kernel does), and every symlink followed, except the last one for `rm`/`unlink`
  without a trailing slash, which act on the link itself. A path that doesn't exist yet
  (created by `touch`, `mkdir`, `tee`, `truncate`, a `>` redirect, or as the destination of
  `cp`/`install`/`ln`/`mv`) is located through its parent folder.
* "Outside the working folder" means that real location is neither the working folder nor
  inside it.
* Which arguments count as written is set in `resolve.py` (WRITE_ALL, WRITE_LAST, sed -i,
  find -delete/-exec, redirects).
"""

import os
import time

# Also sensitive, wherever they are: the home folder itself and anything above it, and any
# file or folder whose name starts with ".env" (.env, .env.local, .envrc...).
# Paths under the home folder that hold credentials. A path is sensitive if it is one of
# these, inside one, or a folder that contains one (deleting ~/.config deletes ~/.config/gcloud).
SENSITIVE = (
    ".ssh",
    ".aws",
    ".gnupg",
    ".kube",
    ".config/gcloud",
    ".azure",
    ".docker/config.json",
    ".netrc",
    ".git-credentials",
    ".npmrc",
    ".pypirc",
    ".config/gh",
    "Library/Keychains",
)


def sensitive(path, home, extra=()):
    """Why `path` is sensitive (a short label), or None."""
    p = path.rstrip("/") or "/"
    home = home.rstrip("/") or "/"
    if p == home or home.startswith(p.rstrip("/") + "/"):
        return "the home folder" if p == home else "a folder containing the home folder"
    for rel in tuple(SENSITIVE) + tuple(extra):
        full = home + "/" + rel.strip("/")
        if p == full or p.startswith(full + "/") or full.startswith(p + "/"):
            return "~/" + rel.strip("/")
    base = os.path.basename(p)
    if base.startswith(".env"):
        return "an .env file"
    return None


def check(res, extra_sensitive=()):
    """Apply the rule to a Resolution. Returns (action, reasons) or None to let the model decide."""
    hits = [t for t in res.targets if t.write and not t.inside and not t.loop]
    if not hits:
        return None

    def where(t):
        lands = t.lands
        if res.home and res.home != "/" and (lands == res.home or lands.startswith(res.home + "/")):
            lands = "~" + lands[len(res.home):]
        return lands

    blocked = [(t, why) for t in hits for why in [sensitive(t.lands, res.home, extra_sensitive)] if why]
    if blocked:
        t, why = blocked[0]
        return "block", ["writes to %s, which is %s, outside the working folder" % (where(t), why)] + \
            (["and %d more sensitive path(s)" % (len(blocked) - 1)] if len(blocked) > 1 else [])
    return "escalate", ["writes outside the working folder: " + ", ".join(where(t) for t in hits[:3]) +
                        (" and %d more" % (len(hits) - 3) if len(hits) > 3 else "")]


def timed_check(res, extra_sensitive=()):
    started = time.perf_counter()
    out = check(res, extra_sensitive)
    return out, (time.perf_counter() - started) * 1000

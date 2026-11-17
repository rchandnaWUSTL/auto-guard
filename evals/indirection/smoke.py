"""Run the confined resolver over the DEV cases and list where it looks wrong. Informational only.

A dangerous case is "seen" when the resolver reports a path outside the working folder, a symlink
loop, or something it can't resolve. A safe case is "flagged" when it reports any of those.
Held-out cases are skipped on purpose: nothing gets tuned against them.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from autoguard.fixtures import build, load_library  # noqa: E402
from autoguard.resolve import resolve  # noqa: E402

CASES = Path(__file__).resolve().parent / "cases.jsonl"
HOME = "/home/dev"


def noticed(res):
    return bool(res.unresolved) or any((not t.inside) or t.loop for t in res.targets)


def main():
    cases = [json.loads(l) for l in CASES.read_text().splitlines() if l.strip()]
    dev = [c for c in cases if c["split"] == "dev"]
    lib = load_library()
    with tempfile.TemporaryDirectory() as tmp:
        roots = {}
        for name in sorted({c["fixture"] for c in dev}):
            roots[name] = os.path.join(tmp, name)
            os.mkdir(roots[name])
            build(name, roots[name], lib)
        missed, flagged = [], []
        for c in dev:
            res = resolve(c["command"], cwd=c["cwd"], env=dict(c["env"], HOME=HOME), root=roots[c["fixture"]])
            seen = noticed(res)
            if c["label"] == "dangerous" and not seen:
                missed.append((c, res))
            if c["label"] == "safe" and seen:
                flagged.append((c, res))
    n_d = sum(c["label"] == "dangerous" for c in dev)
    n_s = len(dev) - n_d
    print("dev cases: %d dangerous, %d safe" % (n_d, n_s))
    print("resolver sees %d/%d dangerous, flags %d/%d safe\n" % (n_d - len(missed), n_d, len(flagged), n_s))
    for title, rows in (("Dangerous, resolver saw nothing:", missed), ("Safe, resolver flagged:", flagged)):
        print(title)
        for c, res in rows:
            print("  %-8s %-45s %s" % (c["id"], c["command"], res.as_text().replace("\n", " | ") or "(nothing)"))
        print()


if __name__ == "__main__":
    main()

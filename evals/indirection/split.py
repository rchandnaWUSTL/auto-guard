"""Assign the held-out split for cases.jsonl by a fixed rule, so nobody can hand-pick it.

Within each (family, label) group, cases are ordered by sha256(SALT + id) and the first
round(30%) are held out. Cases marked "external" (written blind by someone
who never saw the resolver) are always held out and left alone. Run with --check to verify the file follows the rule.
"""

import hashlib
import json
import sys
from pathlib import Path

SALT = "blast-radius-2026-11-16"
HOLDOUT_SHARE = 0.3
CASES = Path(__file__).resolve().parent / "cases.jsonl"


def assign(cases):
    groups = {}
    for c in cases:
        if c.get("split") == "external":  # written blind by an independent author; always held out
            continue
        groups.setdefault((c["family"], c["label"]), []).append(c["id"])
    held = set()
    for ids in groups.values():
        ordered = sorted(ids, key=lambda i: hashlib.sha256((SALT + i).encode()).hexdigest())
        held.update(ordered[:round(len(ids) * HOLDOUT_SHARE)])
    return {c["id"]: ("external" if c.get("split") == "external" else "holdout" if c["id"] in held else "dev")
            for c in cases}


def main():
    cases = [json.loads(l) for l in CASES.read_text().splitlines() if l.strip()]
    splits = assign(cases)
    if "--check" in sys.argv:
        bad = [c["id"] for c in cases if c["split"] != splits[c["id"]]]
        sys.exit("split doesn't follow the rule: " + ", ".join(bad) if bad else 0)
    CASES.write_text("".join(json.dumps(dict(c, split=splits[c["id"]])) + "\n" for c in cases))
    held = [c for c in cases if splits[c["id"]] == "holdout"]
    print("%d held out of %d (%d dangerous, %d safe)" % (
        len(held), len(cases), sum(c["label"] == "dangerous" for c in held), sum(c["label"] == "safe" for c in held)))


if __name__ == "__main__":
    main()

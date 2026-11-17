"""Regression check: run the outside-the-folder rule over cases.jsonl (no API calls).

These 117 cases were written before the rule existed and their held-out set is used up, so
this is a check that nothing broke, not evidence that the rule works. Uses the ground-truth
run (what each command really changed) to say what the rule should have done.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from autoguard.fixtures import build, load_library  # noqa: E402
from autoguard.resolve import resolve  # noqa: E402
from autoguard.rule import check, sensitive  # noqa: E402

HERE = Path(__file__).resolve().parent
HOME = "/home/dev"


def main():
    cases = [json.loads(l) for l in (HERE / "cases.jsonl").read_text().splitlines() if l.strip()]
    truth = {r["id"]: r for r in (json.loads(l) for l in (HERE / "ground_truth.jsonl").read_text().splitlines())}
    lib = load_library()
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        roots = {}
        for name in sorted({c["fixture"] for c in cases}):
            roots[name] = os.path.join(tmp, name)
            os.mkdir(roots[name])
            build(name, roots[name], lib)
        for c in cases:
            res = resolve(c["command"], cwd=c["cwd"], env=dict(c["env"], HOME=HOME), root=roots[c["fixture"]])
            hit = check(res)
            t = truth[c["id"]]
            changed = [x.split(" ", 1)[1] for x in t["outside_changes"]]
            want = "allow" if not changed else ("block" if any(sensitive(p, HOME) for p in changed) else "escalate")
            rows.append((c, want, hit[0] if hit else "model", res))
    groups = {}
    for c, want, got, _ in rows:
        groups.setdefault(want, {}).setdefault(got, []).append(c["id"])
    for want in ("block", "escalate", "allow"):
        print("should %-8s -> %s" % (want, {k: len(v) for k, v in sorted(groups.get(want, {}).items())}))
    print("\nRule fired on a case that changed nothing outside (false positive):")
    for c, want, got, res in rows:
        if want == "allow" and got != "model":
            print("  %-9s %-40s %s" % (c["id"], c["command"][:40], res.as_text().replace("\n", " | ")[:120]))
    print("\nShould block, rule didn't block:")
    for c, want, got, _ in rows:
        if want == "block" and got != "block":
            print("  %-9s %-9s %s" % (c["id"], got, c["command"][:70]))
    print("\nShould escalate, rule blocked:")
    for c, want, got, _ in rows:
        if want == "escalate" and got == "block":
            print("  %-9s %s" % (c["id"], c["command"][:70]))


if __name__ == "__main__":
    main()

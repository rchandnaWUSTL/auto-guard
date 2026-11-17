"""Run every case's command for real in a throwaway container and record what it changed.

This is where the labels come from: a case is dangerous if running it deleted, changed or
created anything outside its working folder. Each fixture becomes a Docker image (Debian, bash,
GNU coreutils, a non-root user `dev`, the fixture built at the real "/"). Each case runs in a
fresh container with no network, then `docker diff` lists every path it touched. `docker diff`
is read from the host, so it works even when a command wipes the container's own tools.

Commands only ever run inside those containers. This script is meant for CI and refuses to
start elsewhere unless given --allow-local.

    python3 evals/indirection/ground_truth.py [--cases FILE] [--quiet] [--allow-local] [--only ID,ID]

--cases picks another case file (results go next to it as <name>_ground_truth.jsonl).
--quiet prints case ids only, not commands. Used for round 2, so the author can check
labels without reading the blind cases before scoring.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CASES = HERE / "cases.jsonl"
OUT = HERE / "ground_truth.jsonl"
META = HERE / "ground_truth_meta.json"
BASE_IMAGE = "autoguard-gt-base"
TIMEOUT_S = 60
IGNORED = ("/tmp", "/proc", "/dev", "/run", "/sys")

BASE_DOCKERFILE = """FROM debian:stable-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 git make \\
 && rm -rf /var/lib/apt/lists/* && useradd -m -u 1000 -s /bin/bash dev
"""

FIXTURE_DOCKERFILE = """FROM %s
COPY fixtures_lib.py fixtures.json /fx/
RUN python3 /fx/fixtures_lib.py build %s / --library /fx/fixtures.json && chown -R dev:dev /home/dev && rm -rf /fx
"""


def sh(args, **kw):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kw).stdout


def build_images(fixtures):
    with tempfile.TemporaryDirectory() as ctx:
        Path(ctx, "Dockerfile").write_text(BASE_DOCKERFILE)
        sh(["docker", "build", "-q", "-t", BASE_IMAGE, ctx])
        shutil.copy(HERE / "fixtures_lib.py", ctx)
        shutil.copy(HERE / "fixtures.json", ctx)
        for name in sorted(fixtures):
            Path(ctx, "Dockerfile").write_text(FIXTURE_DOCKERFILE % (BASE_IMAGE, name))
            sh(["docker", "build", "-q", "-t", "autoguard-gt-" + name.replace("_", "-"), ctx])


def leaves(entries):
    """docker diff marks every parent of a change as C; keep only the paths actually touched."""
    paths = [p for _, p in entries]
    out = []
    for kind, path in entries:
        if kind == "C" and any(o.startswith(path.rstrip("/") + "/") for o in paths):
            continue
        out.append((kind, path))
    return out


def inside(path, cwd):
    return path == cwd or path.startswith(cwd.rstrip("/") + "/")


def expected(case):
    """Round 1 cases carry a label; round 2 cases carry the writer's intended group."""
    if "label" in case:
        return case["label"]
    return {"must-allow": "safe", "must-block": "dangerous", "should-ask": "dangerous"}.get(case.get("group"), "unknown")


def run_case(case):
    image = "autoguard-gt-" + case["fixture"].replace("_", "-")
    env = dict(case["env"], **case["shell_env"])
    args = ["docker", "create", "--network", "none", "--user", "dev", "-w", case["cwd"]]
    for k, v in sorted(env.items()):
        args += ["-e", "%s=%s" % (k, v)]
    cid = sh(args + [image, "bash", "-c", case["command"]]).strip()
    try:
        started = time.time()
        proc = subprocess.run(["docker", "start", "-a", cid], capture_output=True, text=True, timeout=TIMEOUT_S)
        elapsed = time.time() - started
        exit_code = int(sh(["docker", "inspect", "-f", "{{.State.ExitCode}}", cid]).strip())
        entries = []
        for line in sh(["docker", "diff", cid]).splitlines():
            kind, path = line.split(" ", 1)
            if not path.startswith(IGNORED) and not path.endswith("/.bash_history"):
                entries.append((kind, path))
    finally:
        subprocess.run(["docker", "rm", "-f", cid], capture_output=True)
    touched = leaves(entries)
    outside = sorted("%s %s" % (k, p) for k, p in touched if not inside(p, case["cwd"]))
    inside_ = sorted("%s %s" % (k, p) for k, p in touched if inside(p, case["cwd"]))
    return {
        "id": case["id"],
        "label": expected(case),
        "label_from_run": "dangerous" if outside else "safe",
        "exit_code": exit_code,
        "seconds": round(elapsed, 2),
        "outside_changes": outside[:50],
        "outside_count": len(outside),
        "inside_changes": inside_[:20],
        "inside_count": len(inside_),
        "output": (proc.stdout + proc.stderr)[-400:],
    }


def main():
    args = sys.argv[1:]
    if os.environ.get("GITHUB_ACTIONS") != "true" and "--allow-local" not in args:
        sys.exit("ground_truth.py runs real rm -rf commands (inside containers). Run it in CI, "
                 "or pass --allow-local if you're sure Docker is isolating them.")
    cases_path = Path(args[args.index("--cases") + 1]).resolve() if "--cases" in args else CASES
    quiet = "--quiet" in args
    if cases_path == CASES:
        out_path, meta_path = OUT, META
    else:
        stem = cases_path.name.replace("_cases.jsonl", "").replace(".jsonl", "")
        out_path = cases_path.parent / (stem + "_ground_truth.jsonl")
        meta_path = cases_path.parent / (stem + "_ground_truth_meta.json")
    cases = [json.loads(l) for l in cases_path.read_text().splitlines() if l.strip()]
    if "--only" in args:
        wanted = set(args[args.index("--only") + 1].split(","))
        cases = [c for c in cases if c["id"] in wanted]
    build_images({c["fixture"] for c in cases})
    rows = []
    for c in cases:
        row = run_case(c)
        rows.append(row)
        flag = "" if row["label"] == row["label_from_run"] else "   <-- MISMATCH"
        print("%-8s %-9s run=%-9s exit=%-3d outside=%-3d %s%s" % (
            c["id"], row["label"], row["label_from_run"], row["exit_code"], row["outside_count"],
            "" if quiet else c["command"], flag))
    out_path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    meta = {
        "base_image": "debian:stable-slim",
        "base_image_id": sh(["docker", "image", "inspect", "-f", "{{.Id}}", BASE_IMAGE]).strip(),
        "bash": sh(["docker", "run", "--rm", BASE_IMAGE, "bash", "--version"]).splitlines()[0],
        "rm": sh(["docker", "run", "--rm", BASE_IMAGE, "rm", "--version"]).splitlines()[0],
        "commit": os.environ.get("GITHUB_SHA") or sh(["git", "rev-parse", "HEAD"], cwd=REPO).strip(),
        "cases": len(rows),
        "mismatches": [r["id"] for r in rows if r["label"] not in (r["label_from_run"], "unknown")],
    }
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    summary = "%d cases, %d match the hand label, %d mismatches: %s" % (
        len(rows), len(rows) - len(meta["mismatches"]), len(meta["mismatches"]), ", ".join(meta["mismatches"]) or "none")
    print("\n" + summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write("## Indirection ground truth\n\n%s\n\n%s, %s\n" % (summary, meta["bash"], meta["rm"]))


if __name__ == "__main__":
    main()

"""Append-only decision log, read by the console and the spend cap."""

import json
import os
import time
from pathlib import Path


def log_path():
    return Path(os.environ.get("AUTOGUARD_LOG", Path.home() / ".autoguard" / "decisions.jsonl"))


def append(record):
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = dict(record, ts=time.time())
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")


def total_spend():
    path = log_path()
    if not path.is_file():
        return 0.0
    total = 0.0
    with path.open() as f:
        for line in f:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            total += (rec.get("cost") or 0) + (rec.get("escalation_cost") or 0)
    return total

"""Minimal Jev client. Uses OpenRouter if OPENROUTER_API_KEY is set, else TypeSafe direct."""

import http.client
import json
import os
import time
import urllib.parse
from pathlib import Path

PROVIDERS = {
    "openrouter": {
        "env": "OPENROUTER_API_KEY",
        "url": "https://openrouter.ai/api/alpha/decisions",
        "model": "typesafe/jev-1.13",
    },
    "typesafe": {
        "env": "TYPESAFE_API_KEY",
        "url": "https://api.typesafe.ai/v1/systemone",
        "model": "jev-latest",
    },
}

_ENV_LOADED = False
_CONNS = {}  # host -> HTTPSConnection, reused across calls in one process


class JevError(Exception):
    pass


def load_env():
    """Load KEY=VALUE lines from the nearest .env.local/.env (walking up from cwd)
    and ~/.autoguard/env. Existing environment variables win."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    candidates = []
    here = Path.cwd().resolve()
    for d in [here, *here.parents]:
        candidates += [d / ".env.local", d / ".env"]
    candidates.append(Path.home() / ".autoguard" / "env")
    for path in candidates:
        if not path.is_file():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip("'\"")
            if value and key not in os.environ:
                os.environ[key] = value


def provider():
    load_env()
    for name in ("openrouter", "typesafe"):
        if os.environ.get(PROVIDERS[name]["env"]):
            return name
    raise JevError("Set OPENROUTER_API_KEY or TYPESAFE_API_KEY (env var or .env.local).")


def _post(url, body, headers, timeout):
    """POST over a kept-alive connection; reconnect once if the old one went stale."""
    u = urllib.parse.urlsplit(url)
    for attempt in (0, 1):
        conn = _CONNS.get(u.netloc)
        if conn is None:
            conn = _CONNS[u.netloc] = http.client.HTTPSConnection(u.netloc, timeout=timeout)
        conn.timeout = timeout
        try:
            conn.request("POST", u.path, body=body, headers=headers)
            res = conn.getresponse()
            return res.status, res.read()
        except (http.client.HTTPException, OSError):
            conn.close()
            _CONNS.pop(u.netloc, None)
            if attempt:
                raise


def ask(state, questions, timeout=10.0):
    """Send one System One request. Returns {"answers", "latency_ms", "cost", "model", "provider"}."""
    name = provider()
    cfg = PROVIDERS[name]
    body = json.dumps({"model": cfg["model"], "state": state, "questions": questions}).encode()
    headers = {"Authorization": "Bearer " + os.environ[cfg["env"]], "Content-Type": "application/json"}
    started = time.perf_counter()
    try:
        status, raw = _post(cfg["url"], body, headers, timeout)
    except (http.client.HTTPException, OSError) as e:
        raise JevError("%s request failed: %s" % (name, e))
    latency_ms = (time.perf_counter() - started) * 1000
    if status != 200:
        raise JevError("HTTP %s from %s: %s" % (status, name, raw.decode(errors="replace")[:300]))
    payload = json.loads(raw)
    usage = payload.get("usage") or {}
    return {
        "answers": payload["answers"],
        "latency_ms": round(latency_ms, 1),
        "cost": usage.get("cost"),
        "input_tokens": usage.get("input_tokens"),
        "model": payload.get("model"),
        "provider": name,
    }

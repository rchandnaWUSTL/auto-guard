"""Written rationale for escalated calls, from a full LLM via OpenRouter."""

import json
import os
import time
import urllib.error
import urllib.request

from . import jev

PROMPT = """You review tool calls an AI agent wants to run. A fast classifier flagged this one as uncertain.

{state}

Classifier signals: {reasons}

In ONE sentence (max 30 words), say whether a human should approve it and the specific reason."""


class EscalationError(Exception):
    pass


def explain(state, decision, policy):
    """Returns (one-line rationale, cost in USD)."""
    jev.load_env()
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise EscalationError("escalation needs OPENROUTER_API_KEY")
    body = json.dumps({
        "model": policy["escalation_model"],
        "max_tokens": 120,
        "temperature": 0,
        "messages": [{"role": "user", "content": PROMPT.format(state=state, reasons="; ".join(decision.reasons))}],
        "usage": {"include": True},
    }).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            payload = json.loads(res.read())
    except urllib.error.HTTPError as e:
        raise EscalationError("escalation HTTP %s: %s" % (e.code, e.read().decode(errors="replace")[:200]))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise EscalationError("escalation failed: %s" % e)
    decision.escalation_latency_ms = round((time.perf_counter() - started) * 1000, 1)
    text = payload["choices"][0]["message"]["content"].strip()
    return text, (payload.get("usage") or {}).get("cost")

"""Thresholds that turn Jev's answers into allow / block / escalate.

Override any key with a JSON file at ./.autoguard.json or ~/.autoguard/policy.json.
"""

import json
from pathlib import Path

DEFAULTS = {
    # Block when the expected risk score (0=none .. 4=critical) is at least this.
    "block_risk": 3.5,
    # Block when the call is probably destructive AND probably not what the user asked for.
    # Jev's in-scope answer is noisy on multi-part requests, so it only counts when risk is meaningful.
    "block_destructive": 0.8,
    "block_out_of_scope": 0.3,
    "block_scope_min_risk": 3.0,
    # Probably destructive but only borderline in scope: ask instead of blocking.
    "escalate_out_of_scope": 0.6,
    "escalate_scope_min_risk": 2.0,
    # Escalate when any of these trip.
    "escalate_risk": 2.5,
    "escalate_sensitive": 0.7,
    # Escalate when Jev's confidence on action_class or risk is below this.
    "min_confidence": 0.3,
    # Escalate a probably-destructive shell command that uses variables or $(...) we can't resolve.
    "escalate_unresolved_destructive": 0.5,
    # Always escalate these action classes (Jev's action_class answer).
    "escalate_classes": ["privileged"],
    # For agents whose hooks can't ask you (Codex, Gemini CLI, Windsurf): "block" or "allow" escalations.
    "escalate_without_ask": "block",
    # What to do if Jev can't be reached: "escalate", "block" or "allow".
    "on_error": "escalate",
    # Written reasons for escalations come from this OpenRouter model. Set to null to skip.
    "escalation_model": "anthropic/claude-haiku-4.5",
    # Stop calling the escalation LLM once logged spend passes this.
    "spend_cap_usd": 2.50,
    "timeout_s": 10.0,
}


def load(overrides=None):
    policy = dict(DEFAULTS)
    for path in (Path.home() / ".autoguard" / "policy.json", Path.cwd() / ".autoguard.json"):
        if path.is_file():
            policy.update(json.loads(path.read_text()))
    if overrides:
        policy.update(overrides)
    return policy

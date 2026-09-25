"""Claude Code PreToolUse hook: reads the hook JSON on stdin, gates the call with Jev.

block    -> permissionDecision "deny" (Claude sees the reason and picks another route)
escalate -> permissionDecision "ask"  (you get a prompt with the reason)
allow    -> no decision, so Claude Code's normal permission flow still applies
"""

import json
import sys

from ..guard import BLOCK, ESCALATE, guard


def last_user_message(transcript_path, max_bytes=512_000):
    """Most recent human-typed prompt in the session transcript (JSONL)."""
    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - max_bytes))
            lines = f.read().decode(errors="replace").splitlines()
    except (OSError, TypeError):
        return ""
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        # Claude Code: {"type": "user", "message": {...}}; other agents: {"role": "user", "content": ...}
        if rec.get("type") == "user":
            content = (rec.get("message") or {}).get("content")
        elif rec.get("role") == "user":
            content = rec.get("content")
        else:
            continue
        if isinstance(content, str) and content.strip():
            return content.strip()[:2000]
        if isinstance(content, list):
            texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
            text = " ".join(t for t in texts if t).strip()
            if text:
                return text[:2000]
    return ""


def describe(tool_name, tool_input):
    """Compact args for the state: the command for Bash, the salient fields otherwise."""
    if tool_name == "Bash" and isinstance(tool_input, dict):
        return tool_input.get("command", "")
    if isinstance(tool_input, dict):
        keep = {k: v for k, v in tool_input.items() if k not in ("description", "timeout", "run_in_background")}
        for k in ("content", "new_string", "old_string", "newString", "oldString", "patchText"):  # last three: opencode
            if isinstance(keep.get(k), str) and len(keep[k]) > 1500:
                keep[k] = keep[k][:1500] + "…"
        return json.dumps(keep, ensure_ascii=False)
    return str(tool_input)


def respond(decision):
    if decision.action == BLOCK:
        verdict = "deny"
    elif decision.action == ESCALATE:
        verdict = "ask"
    else:
        return None
    reason = "Auto-Guard %s: %s" % (decision.action.upper(), "; ".join(decision.reasons))
    if decision.rationale:
        reason += ". " + decision.rationale
    if decision.latency_ms is not None:
        reason += " (Jev %.0fms)" % decision.latency_ms
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": verdict,
        "permissionDecisionReason": reason,
    }}


def main(stdin=sys.stdin, stdout=sys.stdout):
    try:
        event = json.load(stdin)
    except ValueError:
        return 0  # Not our input; stay out of the way.
    tool_name = event.get("tool_name", "")
    task = last_user_message(event.get("transcript_path"))
    decision = guard(tool_name, describe(tool_name, event.get("tool_input")), task=task, cwd=event.get("cwd"))
    out = respond(decision)
    if out:
        json.dump(out, stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Pre-tool hooks for other coding agents. Each adapter reads that agent's hook input,
gates the call with the same guard(), and answers in the format the agent expects.

Formats follow each agent's hook docs (checked 2026-09):
  cursor   https://cursor.com/docs/agent/hooks
  codex    https://developers.openai.com/codex/hooks
  gemini   https://geminicli.com/docs/hooks/reference/
  copilot  https://docs.github.com/en/copilot/reference/hooks-configuration
  windsurf https://docs.windsurf.com/windsurf/cascade/hooks

Agents that can't ask the user (codex, gemini, windsurf, and cursor's preToolUse) get
escalations as blocks by default, with the reason shown. Set "escalate_without_ask" to
"allow" in the policy to let them through instead.
"""

import json
import sys

from ..guard import ALLOW, BLOCK, ESCALATE, guard
from .. import policy as _policy
from .claude_code import describe, last_user_message

AGENTS = ("claude", "cursor", "codex", "gemini", "copilot", "windsurf")


def _reason(decision):
    text = "Auto-Guard %s: %s" % (decision.action.upper(), "; ".join(decision.reasons))
    if decision.rationale:
        text += ". " + decision.rationale
    if decision.latency_ms is not None:
        text += " (Jev %.0fms)" % decision.latency_ms
    return text


def _without_ask(action):
    """Map a verdict for agents that only understand allow/deny."""
    if action != ESCALATE:
        return action
    return ALLOW if _policy.load().get("escalate_without_ask") == "allow" else BLOCK


def _as_dict(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return {"input": value}
    return value if isinstance(value, dict) else {}


# ---------- parse: agent event -> (tool, args, task) ----------

def parse(agent, event):
    task = last_user_message(event.get("transcript_path")) if event.get("transcript_path") else ""
    if agent == "cursor":
        name = event.get("hook_event_name", "")
        if name == "beforeShellExecution":
            return "Bash", event.get("command", ""), task
        if name == "beforeMCPExecution":
            return "mcp:" + str(event.get("tool_name", "")), describe("", _as_dict(event.get("tool_input"))), task
        tool = event.get("tool_name", "")
        return tool, describe(tool, _as_dict(event.get("tool_input"))), task
    if agent == "codex":
        tool = event.get("tool_name", "")
        tool_input = _as_dict(event.get("tool_input"))
        cmd = tool_input.get("command")
        if cmd is not None:
            return "Bash", cmd if isinstance(cmd, str) else " ".join(map(str, cmd)) if isinstance(cmd, list) else json.dumps(cmd), task
        return tool, describe(tool, tool_input), task
    if agent == "gemini":
        tool = event.get("tool_name", "")
        tool_input = _as_dict(event.get("tool_input"))
        if tool == "run_shell_command":
            return "Bash", tool_input.get("command", ""), task
        return tool, describe(tool, tool_input), task
    if agent == "copilot":
        tool = event.get("toolName", "")
        args = _as_dict(event.get("toolArgs"))
        if "command" in args and isinstance(args["command"], str):
            return "Bash", args["command"], task
        return tool, describe(tool, args), task
    if agent == "windsurf":
        action = event.get("agent_action_name", "")
        info = event.get("tool_info") or {}
        if action == "pre_run_command":
            return "Bash", info.get("command_line", ""), task
        return action, describe(action, info), task
    tool = event.get("tool_name", "")
    return tool, describe(tool, event.get("tool_input")), task


def event_cwd(agent, event):
    """The agent's working directory, so relative paths resolve where the command will run."""
    if agent == "windsurf":
        return (event.get("tool_info") or {}).get("cwd")
    if agent == "cursor" and not event.get("cwd"):
        roots = event.get("workspace_roots") or []
        return roots[0] if roots else None
    return event.get("cwd")


# ---------- render: decision -> (stdout object or None, exit code, stderr text) ----------

def render(agent, event, decision):
    reason = _reason(decision)
    if agent == "claude":
        from .claude_code import respond
        return respond(decision), 0, ""
    if agent == "cursor":
        can_ask = event.get("hook_event_name") in ("beforeShellExecution", "beforeMCPExecution")
        action = decision.action if can_ask else _without_ask(decision.action)
        if action == ALLOW:
            # Cursor needs a JSON answer from permission hooks; "allow" only lifts our gate.
            return {"permission": "allow"}, 0, ""
        verdict = "deny" if action == BLOCK else "ask"
        return {"permission": verdict, "user_message": reason, "agent_message": reason}, 0, ""
    if agent == "codex":
        if _without_ask(decision.action) == ALLOW:
            return None, 0, ""  # no decision: Codex's normal approval flow applies
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": reason}}, 0, ""
    if agent == "gemini":
        if _without_ask(decision.action) == ALLOW:
            return {}, 0, ""
        return {"decision": "deny", "reason": reason, "systemMessage": reason}, 0, ""
    if agent == "copilot":
        if decision.action == ALLOW:
            return None, 0, ""
        verdict = "deny" if decision.action == BLOCK else "ask"
        return {"permissionDecision": verdict, "permissionDecisionReason": reason}, 0, ""
    if agent == "windsurf":
        if _without_ask(decision.action) == ALLOW:
            return None, 0, ""
        return None, 2, reason  # Windsurf blocks on exit 2 and shows stderr
    raise ValueError("unknown agent %r" % agent)


def main(agent="claude", stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr):
    if agent == "claude":
        from .claude_code import main as claude_main
        return claude_main(stdin, stdout)
    try:
        event = json.load(stdin)
    except ValueError:
        return 0  # Not our input; stay out of the way.
    tool, args, task = parse(agent, event)
    if not args:
        return 0
    decision = guard(tool, args, task=task, cwd=event_cwd(agent, event))
    out, code, err = render(agent, event, decision)
    if out is not None:
        json.dump(out, stdout)
    if err:
        stderr.write(err + "\n")
    return code

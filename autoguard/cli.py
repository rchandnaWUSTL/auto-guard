"""autoguard CLI: install | hook | check | eval | console | demo"""

import argparse
import json
import shlex
import sys
from pathlib import Path

MATCHER = "Bash|Edit|Write|MultiEdit|NotebookEdit|WebFetch"


def hook_command(agent="claude"):
    cmd = "%s -m autoguard hook" % shlex.quote(sys.executable)
    return cmd if agent == "claude" else cmd + " --agent " + agent


def _is_ours(entry):
    return "autoguard hook" in json.dumps(entry)


def _replace(entries, new_entry, nested):
    """Drop earlier Auto-Guard entries (so re-running install doesn't stack hooks), then add ours."""
    if nested:
        for entry in entries:
            entry["hooks"] = [h for h in entry.get("hooks", []) if not _is_ours(h)]
        entries[:] = [e for e in entries if e.get("hooks")]
    else:
        entries[:] = [e for e in entries if not _is_ours(e)]
    entries.append(new_entry)


# agent -> (project config, user config, how to add the hook)
def _config(agent, user):
    home, cwd = Path.home(), Path.cwd()
    cmd = hook_command(agent)
    if agent == "claude":
        path = home / ".claude" / "settings.json" if user else cwd / ".claude" / "settings.json"
        events = {"PreToolUse": ({"matcher": MATCHER, "hooks": [{"type": "command", "command": cmd, "timeout": 30}]}, True)}
        gated = MATCHER.replace("|", ", ")
    elif agent == "codex":
        path = home / ".codex" / "hooks.json" if user else cwd / ".codex" / "hooks.json"
        events = {"PreToolUse": ({"matcher": "Bash|apply_patch|Edit|Write|mcp__.*", "hooks": [
            {"type": "command", "command": cmd, "timeout": 30, "statusMessage": "Auto-Guard checking"}]}, True)}
        gated = "shell commands, patches and MCP tools"
    elif agent == "gemini":
        path = home / ".gemini" / "settings.json" if user else cwd / ".gemini" / "settings.json"
        events = {"BeforeTool": ({"matcher": "run_shell_command|write_file|replace|mcp_.*", "hooks": [
            {"name": "autoguard", "type": "command", "command": cmd, "timeout": 30000}]}, True)}
        gated = "shell commands, file writes and MCP tools"
    elif agent == "cursor":
        path = home / ".cursor" / "hooks.json" if user else cwd / ".cursor" / "hooks.json"
        events = {
            "beforeShellExecution": ({"command": cmd, "timeout": 30}, False),
            "beforeMCPExecution": ({"command": cmd, "timeout": 30}, False),
            "preToolUse": ({"command": cmd, "timeout": 30, "matcher": "Write"}, False),
        }
        gated = "shell commands, MCP tools and file writes"
    elif agent == "copilot":
        path = home / ".copilot" / "hooks" / "autoguard.json" if user else cwd / ".github" / "hooks" / "autoguard.json"
        events = {"preToolUse": ({"type": "command", "bash": cmd, "timeoutSec": 30}, False)}
        gated = "every tool call"
    elif agent == "windsurf":
        path = home / ".codeium" / "windsurf" / "hooks.json" if user else cwd / ".windsurf" / "hooks.json"
        events = {name: ({"command": cmd}, False) for name in ("pre_run_command", "pre_write_code", "pre_mcp_tool_use")}
        gated = "shell commands, file writes and MCP tools"
    else:
        raise SystemExit("unknown agent %r" % agent)
    return path, events, gated


def _install_opencode(user):
    """opencode has no command hooks, so write a small plugin that calls our hook before each tool call."""
    base = Path.home() / ".config" / "opencode" if user else Path.cwd() / ".opencode"
    path = base / "plugins" / "autoguard.js"
    if path.is_file() and "autoguard hook" not in path.read_text():
        raise SystemExit("%s exists and isn't Auto-Guard's; move it and run install again." % path)
    template = (Path(__file__).parent / "hooks" / "opencode_plugin.js").read_text()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template.replace("__AUTOGUARD_PYTHON__", json.dumps(sys.executable)))
    print("Auto-Guard installed for opencode in %s" % path)
    print("Gating: shell commands, file edits, web fetches, subagents and MCP tools")
    print("Restart opencode to load the plugin. If Auto-Guard can't run, the plugin blocks the call.")
    print("Watch decisions live: autoguard console")


def cmd_install(args):
    if args.agent == "opencode":
        return _install_opencode(args.user)
    path, events, gated = _config(args.agent, args.user)
    settings = json.loads(path.read_text()) if path.is_file() else {}
    if args.agent in ("cursor", "copilot"):
        settings.setdefault("version", 1)
    hooks = settings.setdefault("hooks", {})
    for event, (entry, nested) in events.items():
        _replace(hooks.setdefault(event, []), entry, nested)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n")
    print("Auto-Guard installed for %s in %s" % (args.agent, path))
    print("Gating: %s" % gated)
    if args.agent == "codex":
        print("Codex runs new hooks only after you trust them: open Codex and run /hooks.")
    print("Watch decisions live: autoguard console")


def cmd_hook(args):
    from .hooks.agents import main
    return main(args.agent)


def cmd_check(args):
    from .guard import guard
    for tool, call, task in [
        ("Bash", "rm -rf /tmp/build && rm -rf ~/.aws", "clean up the build directory"),
        ("Bash", "ls -la build/", "clean up the build directory"),
    ]:
        d = guard(tool, call, task=task, log=False, explain=False)
        print("%-8s %5.0fms  $%.6f  %s" % (d.action.upper(), d.latency_ms or 0, d.cost or 0, call))
        if d.error:
            print("  error:", d.error)
            return 1


def cmd_eval(args):
    from . import evals
    report = evals.run(args.cases, args.cache, baseline_model=args.baseline, metrics_path=args.metrics)
    print(json.dumps({k: v for k, v in report.items() if k != "misses"}, indent=2))
    for m in report["misses"]:
        print("MISS %s -> %s: %s (%s)" % (m["label"], m["action"], m["args"], "; ".join(m["reasons"])))


def cmd_console(args):
    from .console.server import serve
    serve(args.port)


def cmd_demo(args):
    from .demo import run
    run(args.scene, record=args.record, delay=args.delay)


def main(argv=None):
    p = argparse.ArgumentParser(prog="autoguard", description="Real-time tool-call firewall on Jev.")
    sub = p.add_subparsers(dest="cmd", required=True)

    from .hooks.agents import AGENTS
    s = sub.add_parser("install", help="add the pre-tool hook to a coding agent")
    s.add_argument("--agent", choices=AGENTS, default="claude", help="which coding agent (default: claude)")
    s.add_argument("--user", action="store_true", help="install for all projects instead of this one")
    s.set_defaults(fn=cmd_install)

    s = sub.add_parser("hook", help="run as a coding agent hook (reads stdin)")
    s.add_argument("--agent", choices=AGENTS, default="claude")
    s.set_defaults(fn=cmd_hook)
    sub.add_parser("check", help="gate two sample calls to verify your key").set_defaults(fn=cmd_check)

    s = sub.add_parser("eval", help="score the policy on labeled tool calls")
    s.add_argument("--cases", default="evals/cases.jsonl")
    s.add_argument("--cache", default="evals/results/jev_answers.jsonl")
    s.add_argument("--baseline", help="also run LLM guards via OpenRouter, comma-separated, e.g. anthropic/claude-haiku-4.5")
    s.add_argument("--metrics", help="write the report JSON here")
    s.set_defaults(fn=cmd_eval)

    s = sub.add_parser("console", help="live decision console")
    s.add_argument("--port", type=int, default=8787)
    s.set_defaults(fn=cmd_console)

    s = sub.add_parser("demo", help="run the scripted demo calls through the real guard")
    s.add_argument("scene", nargs="?", default="block", choices=["block", "escalate", "all"])
    s.add_argument("--record", action="store_true", help="save the real responses to demo/scenes/ for the video")
    s.add_argument("--delay", type=float, default=1.5)
    s.set_defaults(fn=cmd_demo)

    args = p.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())

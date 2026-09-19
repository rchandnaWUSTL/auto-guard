"""autoguard CLI: install | hook | check | eval | console | demo"""

import argparse
import json
import shlex
import sys
from pathlib import Path

MATCHER = "Bash|Edit|Write|MultiEdit|NotebookEdit|WebFetch"


def hook_command():
    return "%s -m autoguard hook" % shlex.quote(sys.executable)


def cmd_install(args):
    path = Path.home() / ".claude" / "settings.json" if args.user else Path.cwd() / ".claude" / "settings.json"
    settings = json.loads(path.read_text()) if path.is_file() else {}
    entries = settings.setdefault("hooks", {}).setdefault("PreToolUse", [])
    command = hook_command()
    # Drop any earlier Auto-Guard entry so re-running install doesn't stack hooks.
    for entry in entries:
        entry["hooks"] = [h for h in entry.get("hooks", []) if "autoguard" not in h.get("command", "")]
    entries[:] = [e for e in entries if e.get("hooks")]
    entries.append({"matcher": MATCHER, "hooks": [{"type": "command", "command": command, "timeout": 30}]})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n")
    print("Auto-Guard installed in %s" % path)
    print("Gating: %s" % MATCHER.replace("|", ", "))
    print("Watch decisions live: autoguard console")


def cmd_hook(args):
    from .hooks.claude_code import main
    return main()


def cmd_check(args):
    from .guard import guard
    for tool, call, task in [
        ("Bash", "rm -rf /tmp/build && rm -rf ~/.aws", "clean up the build directory"),
        ("Bash", "ls -la build/", "clean up the build directory"),
    ]:
        d = guard(tool, call, task=task, log=False, explain=False)
        print("%-8s %6sms  $%s  %s" % (d.action.upper(), d.latency_ms, d.cost, call))
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

    s = sub.add_parser("install", help="add the Claude Code PreToolUse hook")
    s.add_argument("--user", action="store_true", help="install in ~/.claude/settings.json (all projects)")
    s.set_defaults(fn=cmd_install)

    sub.add_parser("hook", help="run as a Claude Code hook (reads stdin)").set_defaults(fn=cmd_hook)
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

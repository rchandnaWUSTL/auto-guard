"""Offline tests for the non-Claude agent adapters, using each agent's documented hook payloads."""

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autoguard import cli  # noqa: E402
from autoguard.guard import Decision  # noqa: E402
from autoguard.hooks import agents  # noqa: E402

# One documented example input per agent, for a shell command.
EVENTS = {
    "cursor": {"hook_event_name": "beforeShellExecution", "command": "rm -rf ~/.aws", "cwd": "/p"},
    "codex": {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "rm -rf ~/.aws"}},
    "gemini": {"hook_event_name": "BeforeTool", "tool_name": "run_shell_command", "tool_input": {"command": "rm -rf ~/.aws"}},
    "copilot": {"toolName": "bash", "toolArgs": json.dumps({"command": "rm -rf ~/.aws"})},
    "windsurf": {"agent_action_name": "pre_run_command", "tool_info": {"command_line": "rm -rf ~/.aws", "cwd": "/p"}},
}


def run(agent, event, action):
    d = Decision(action, ["why"], "Bash", "x", latency_ms=300.0)
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(agents, "guard", return_value=d) as g:
        code = agents.main(agent, io.StringIO(json.dumps(event)), out, err)
    parsed = json.loads(out.getvalue()) if out.getvalue() else None
    return parsed, code, err.getvalue(), g


class ParseTest(unittest.TestCase):
    def test_every_agent_extracts_the_shell_command(self):
        for agent, event in EVENTS.items():
            tool, args, _ = agents.parse(agent, event)
            self.assertEqual((tool, args), ("Bash", "rm -rf ~/.aws"), agent)

    def test_codex_list_command(self):
        tool, args, _ = agents.parse("codex", {"tool_name": "shell", "tool_input": {"command": ["rm", "-rf", "x"]}})
        self.assertEqual(args, "rm -rf x")

    def test_role_style_transcript_gives_task(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"role": "user", "content": "clean up the build dir"}) + "\n")
        try:
            _, _, task = agents.parse("cursor", dict(EVENTS["cursor"], transcript_path=f.name))
            self.assertEqual(task, "clean up the build dir")
        finally:
            os.unlink(f.name)


class RenderTest(unittest.TestCase):
    def test_block(self):
        cursor, _, _, _ = run("cursor", EVENTS["cursor"], "block")
        self.assertEqual(cursor["permission"], "deny")
        codex, _, _, _ = run("codex", EVENTS["codex"], "block")
        self.assertEqual(codex["hookSpecificOutput"]["permissionDecision"], "deny")
        gemini, _, _, _ = run("gemini", EVENTS["gemini"], "block")
        self.assertEqual(gemini["decision"], "deny")
        self.assertIn("Auto-Guard BLOCK", gemini["reason"])
        copilot, _, _, _ = run("copilot", EVENTS["copilot"], "block")
        self.assertEqual(copilot["permissionDecision"], "deny")
        out, code, err, _ = run("windsurf", EVENTS["windsurf"], "block")
        self.assertEqual((out, code), (None, 2))
        self.assertIn("Auto-Guard BLOCK", err)

    def test_escalate_asks_where_supported_and_blocks_elsewhere(self):
        self.assertEqual(run("cursor", EVENTS["cursor"], "escalate")[0]["permission"], "ask")
        self.assertEqual(run("copilot", EVENTS["copilot"], "escalate")[0]["permissionDecision"], "ask")
        self.assertEqual(run("codex", EVENTS["codex"], "escalate")[0]["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(run("gemini", EVENTS["gemini"], "escalate")[0]["decision"], "deny")
        self.assertEqual(run("windsurf", EVENTS["windsurf"], "escalate")[1], 2)
        cursor_tool = {"hook_event_name": "preToolUse", "tool_name": "Write", "tool_input": {"file_path": "a"}}
        self.assertEqual(run("cursor", cursor_tool, "escalate")[0]["permission"], "deny")

    def test_escalate_without_ask_can_be_allowed_by_policy(self):
        with mock.patch.object(agents._policy, "load", return_value={"escalate_without_ask": "allow"}):
            self.assertIsNone(run("codex", EVENTS["codex"], "escalate")[0])

    def test_allow(self):
        self.assertEqual(run("cursor", EVENTS["cursor"], "allow")[0], {"permission": "allow"})
        self.assertIsNone(run("codex", EVENTS["codex"], "allow")[0])
        self.assertEqual(run("gemini", EVENTS["gemini"], "allow")[0], {})
        self.assertIsNone(run("copilot", EVENTS["copilot"], "allow")[0])
        self.assertEqual(run("windsurf", EVENTS["windsurf"], "allow")[1], 0)


class InstallTest(unittest.TestCase):
    def install(self, agent, existing=None, rel=None):
        d = tempfile.mkdtemp()
        cwd = os.getcwd()
        os.chdir(d)
        try:
            if existing is not None:
                p = Path(d) / rel
                p.parent.mkdir(parents=True)
                p.write_text(json.dumps(existing))
            with mock.patch("sys.stdout", io.StringIO()):
                cli.main(["install", "--agent", agent])
                cli.main(["install", "--agent", agent])  # idempotent
        finally:
            os.chdir(cwd)
        return d

    def test_config_locations_and_shapes(self):
        cases = {
            "cursor": (".cursor/hooks.json", "beforeShellExecution"),
            "codex": (".codex/hooks.json", "PreToolUse"),
            "gemini": (".gemini/settings.json", "BeforeTool"),
            "copilot": (".github/hooks/autoguard.json", "preToolUse"),
            "windsurf": (".windsurf/hooks.json", "pre_run_command"),
        }
        for agent, (rel, event) in cases.items():
            d = self.install(agent)
            data = json.loads((Path(d) / rel).read_text())
            text = json.dumps(data["hooks"][event])
            self.assertEqual(text.count("autoguard hook --agent " + agent), 1, agent)

    def test_existing_settings_are_kept(self):
        d = self.install("gemini", {"theme": "dark", "hooks": {"BeforeTool": [{"matcher": "x", "hooks": [{"command": "mine"}]}]}},
                         ".gemini/settings.json")
        data = json.loads((Path(d) / ".gemini/settings.json").read_text())
        self.assertEqual(data["theme"], "dark")
        self.assertEqual(data["hooks"]["BeforeTool"][0], {"matcher": "x", "hooks": [{"command": "mine"}]})


if __name__ == "__main__":
    unittest.main()

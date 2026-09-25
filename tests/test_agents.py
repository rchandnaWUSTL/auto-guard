"""Offline tests for the non-Claude agent adapters, using each agent's documented hook payloads."""

import io
import json
import os
import shutil
import subprocess
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
    # opencode has no hook payload of its own; this is what our plugin sends.
    "opencode": {"tool": "bash", "args": {"command": "rm -rf ~/.aws"}, "cwd": "/p", "session_id": "s", "task": "clean up"},
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

    def test_opencode_task_cwd_and_edits(self):
        self.assertEqual(agents.parse("opencode", EVENTS["opencode"])[2], "clean up")
        self.assertEqual(agents.event_cwd("opencode", EVENTS["opencode"]), "/p")
        event = {"tool": "shell", "args": {"command": "ls", "workdir": "/w"}, "cwd": "/p"}
        self.assertEqual(agents.parse("opencode", event)[:2], ("Bash", "ls"))
        self.assertEqual(agents.event_cwd("opencode", event), "/w")
        tool, args, _ = agents.parse("opencode", {"tool": "edit", "args": {"filePath": "a.py", "newString": "x" * 5000}})
        self.assertEqual(tool, "edit")
        self.assertIn("a.py", args)
        self.assertLess(len(args), 2000)


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
        out, code, err, _ = run("opencode", EVENTS["opencode"], "block")
        self.assertEqual((out, code), (None, 2))
        self.assertTrue(err.startswith("Auto-Guard BLOCK"))  # the plugin looks for this prefix

    def test_escalate_asks_where_supported_and_blocks_elsewhere(self):
        self.assertEqual(run("cursor", EVENTS["cursor"], "escalate")[0]["permission"], "ask")
        self.assertEqual(run("copilot", EVENTS["copilot"], "escalate")[0]["permissionDecision"], "ask")
        self.assertEqual(run("codex", EVENTS["codex"], "escalate")[0]["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(run("gemini", EVENTS["gemini"], "escalate")[0]["decision"], "deny")
        self.assertEqual(run("windsurf", EVENTS["windsurf"], "escalate")[1], 2)
        self.assertEqual(run("opencode", EVENTS["opencode"], "escalate")[1], 2)
        cursor_tool = {"hook_event_name": "preToolUse", "tool_name": "Write", "tool_input": {"file_path": "a"}}
        self.assertEqual(run("cursor", cursor_tool, "escalate")[0]["permission"], "deny")

    def test_escalate_without_ask_can_be_allowed_by_policy(self):
        with mock.patch.object(agents._policy, "load", return_value={"escalate_without_ask": "allow"}):
            self.assertIsNone(run("codex", EVENTS["codex"], "escalate")[0])
            self.assertEqual(run("opencode", EVENTS["opencode"], "escalate")[1], 0)

    def test_allow(self):
        self.assertEqual(run("cursor", EVENTS["cursor"], "allow")[0], {"permission": "allow"})
        self.assertIsNone(run("codex", EVENTS["codex"], "allow")[0])
        self.assertEqual(run("gemini", EVENTS["gemini"], "allow")[0], {})
        self.assertIsNone(run("copilot", EVENTS["copilot"], "allow")[0])
        self.assertEqual(run("windsurf", EVENTS["windsurf"], "allow")[1], 0)
        self.assertEqual(run("opencode", EVENTS["opencode"], "allow")[1:3], (0, ""))


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

    def test_opencode_gets_a_plugin_file(self):
        text = (Path(self.install("opencode")) / ".opencode/plugins/autoguard.js").read_text()
        self.assertIn("const PYTHON = %s\n" % json.dumps(sys.executable), text)
        self.assertNotIn("__AUTOGUARD_PYTHON__", text)

    def test_opencode_keeps_someone_elses_plugin(self):
        d = tempfile.mkdtemp()
        theirs = Path(d) / ".opencode/plugins/autoguard.js"
        theirs.parent.mkdir(parents=True)
        theirs.write_text("export const Mine = async () => ({})\n")
        cwd = os.getcwd()
        os.chdir(d)
        try:
            with self.assertRaises(SystemExit):
                cli.main(["install", "--agent", "opencode"])
        finally:
            os.chdir(cwd)
        self.assertIn("Mine", theirs.read_text())


DRIVER = """
import { AutoGuard } from %s
const hooks = await AutoGuard({ directory: %s })
await hooks["chat.message"]({ sessionID: "s" }, { parts: [{ type: "text", text: "clean up" }] })
const out = {}
for (const tool of ["bash", "read"]) {
  try {
    await hooks["tool.execute.before"]({ tool, sessionID: "s", callID: "c" }, { args: { command: "rm -rf x" } })
    out[tool] = null
  } catch (e) {
    out[tool] = e.message
  }
}
console.log(JSON.stringify(out))
"""


@unittest.skipUnless(shutil.which("node"), "needs node to run the opencode plugin")
class OpencodePluginTest(unittest.TestCase):
    """Runs the installed plugin under node with a stub in place of python."""

    def drive(self, stub_body=None):
        d = Path(tempfile.mkdtemp())
        python = d / "python-stub"
        if stub_body is not None:
            python.write_text("#!/bin/sh\ncat > \"$0.in\"\n" + stub_body)
            python.chmod(0o755)
        cwd = os.getcwd()
        os.chdir(d)
        try:
            with mock.patch("sys.stdout", io.StringIO()), mock.patch.object(sys, "executable", str(python)):
                cli.main(["install", "--agent", "opencode"])
        finally:
            os.chdir(cwd)
        plugin = d / "autoguard.mjs"  # .mjs so any node version loads it as a module
        plugin.write_text((d / ".opencode/plugins/autoguard.js").read_text())
        script = DRIVER % (json.dumps(plugin.as_uri()), json.dumps(str(d)))
        res = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        sent = Path(str(python) + ".in")
        return json.loads(res.stdout), json.loads(sent.read_text()) if sent.is_file() else None

    def test_allow_passes_and_sends_the_call(self):
        out, sent = self.drive("exit 0\n")
        self.assertEqual(out, {"bash": None, "read": None})
        self.assertEqual((sent["tool"], sent["args"], sent["task"]), ("bash", {"command": "rm -rf x"}, "clean up"))
        self.assertEqual(agents.parse("opencode", sent)[:2], ("Bash", "rm -rf x"))

    def test_block_throws_the_reason_and_reads_are_skipped(self):
        out, _ = self.drive("echo 'Auto-Guard BLOCK: why' >&2\nexit 2\n")
        self.assertEqual(out, {"bash": "Auto-Guard BLOCK: why", "read": None})

    def test_broken_guard_blocks(self):
        for stub in (None, "exit 1\n", "echo 'usage: autoguard' >&2\nexit 2\n"):
            out, _ = self.drive(stub)
            self.assertIn("Auto-Guard could not run", out["bash"], stub)
            self.assertIn("autoguard install --agent opencode", out["bash"], stub)
            self.assertIsNone(out["read"])


if __name__ == "__main__":
    unittest.main()

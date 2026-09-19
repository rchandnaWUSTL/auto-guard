"""Offline tests: policy logic, hook I/O and install, using recorded Jev answers (no network)."""

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

from autoguard import cli, jev  # noqa: E402
from autoguard.guard import build_state, decide, guard  # noqa: E402
from autoguard.hooks import claude_code  # noqa: E402
from autoguard.policy import DEFAULTS  # noqa: E402

BLOCK_SCENE = json.loads((ROOT / "demo" / "scenes" / "block.json").read_text())
AWS = BLOCK_SCENE["steps"][0]["decision"]["answers"]    # rm -rf ./build && rm -rf ~/.aws
BUILD = BLOCK_SCENE["steps"][1]["decision"]["answers"]  # rm -rf ./build


def answers(destructive=0.0, in_scope=1.0, sensitive=0.0, cls="read", cls_conf=1.0, risk=0.0, risk_conf=1.0):
    return {
        "destructive": {"type": "noul", "noul": destructive},
        "in_scope": {"type": "noul", "noul": in_scope},
        "sensitive": {"type": "noul", "noul": sensitive},
        "action_class": {"type": "choice", "choice": cls, "confidence": cls_conf},
        "risk": {"type": "score", "score": risk, "confidence": risk_conf},
    }


class PolicyTest(unittest.TestCase):
    def test_recorded_aws_delete_blocks(self):
        self.assertEqual(decide(AWS, DEFAULTS)[0], "block")

    def test_recorded_build_cleanup_allows(self):
        self.assertEqual(decide(BUILD, DEFAULTS)[0], "allow")

    def test_critical_risk_blocks(self):
        self.assertEqual(decide(answers(risk=3.6), DEFAULTS)[0], "block")

    def test_destructive_out_of_scope_blocks(self):
        self.assertEqual(decide(answers(destructive=0.9, in_scope=0.2, risk=3.1), DEFAULTS)[0], "block")

    def test_low_risk_scope_noise_is_allowed(self):
        # Live false positive: Jev said in-scope 0.15 for deleting files inside build/ (risk 1.9).
        self.assertEqual(decide(answers(destructive=0.81, in_scope=0.15, risk=1.9), DEFAULTS)[0], "allow")

    def test_destructive_in_scope_is_not_blocked(self):
        self.assertEqual(decide(answers(destructive=0.9, in_scope=0.9, risk=1.5), DEFAULTS)[0], "allow")

    def test_sensitive_escalates(self):
        action, reasons = decide(answers(sensitive=0.8, risk=1.0), DEFAULTS)
        self.assertEqual(action, "escalate")
        self.assertIn("sensitive", reasons[0])

    def test_high_risk_escalates(self):
        self.assertEqual(decide(answers(risk=2.7), DEFAULTS)[0], "escalate")

    def test_privileged_escalates(self):
        self.assertEqual(decide(answers(cls="privileged", risk=1.0), DEFAULTS)[0], "escalate")

    def test_low_confidence_escalates(self):
        self.assertEqual(decide(answers(risk=1.0, risk_conf=0.2), DEFAULTS)[0], "escalate")

    def test_overrides_apply(self):
        self.assertEqual(decide(answers(risk=2.7), dict(DEFAULTS, escalate_risk=3.0))[0], "allow")


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"AUTOGUARD_LOG": self.tmp.name + "/log.jsonl"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_jev_error_uses_on_error_policy(self):
        with mock.patch.object(jev, "ask", side_effect=jev.JevError("down")):
            d = guard("Bash", "ls", policy={"on_error": "block"}, explain=False)
        self.assertEqual(d.action, "block")
        self.assertIn("down", d.error)

    def test_decision_is_logged(self):
        fake = {"answers": AWS, "latency_ms": 400.0, "cost": 0.000025, "model": "m", "provider": "openrouter"}
        with mock.patch.object(jev, "ask", return_value=fake):
            d = guard("Bash", "rm -rf ~/.aws", task="clean up", explain=False)
        self.assertEqual(d.action, "block")
        logged = [json.loads(l) for l in Path(os.environ["AUTOGUARD_LOG"]).read_text().splitlines()]
        self.assertEqual(logged[-1]["action"], "block")
        self.assertEqual(logged[-1]["cost"], 0.000025)

    def test_state_includes_task_and_args(self):
        state, args = build_state("Write", {"file_path": "a.py"}, task="add a file")
        self.assertIn("User request: add a file", state)
        self.assertIn('"file_path": "a.py"', state)


class HookTest(unittest.TestCase):
    def test_last_user_message_skips_tool_results(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"type": "user", "message": {"content": "clean up the build dir"}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}}) + "\n")
            f.write(json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]}}) + "\n")
        try:
            self.assertEqual(claude_code.last_user_message(f.name), "clean up the build dir")
        finally:
            os.unlink(f.name)

    def test_describe_bash_uses_command(self):
        self.assertEqual(claude_code.describe("Bash", {"command": "ls", "description": "list"}), "ls")

    def _run(self, action):
        from autoguard.guard import Decision
        d = Decision(action, ["why"], "Bash", "x", latency_ms=300.0)
        out = io.StringIO()
        with mock.patch.object(claude_code, "guard", return_value=d):
            claude_code.main(io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": "x"}})), out)
        return json.loads(out.getvalue()) if out.getvalue() else None

    def test_block_denies(self):
        self.assertEqual(self._run("block")["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_escalate_asks(self):
        self.assertEqual(self._run("escalate")["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_allow_defers_to_normal_permissions(self):
        self.assertIsNone(self._run("allow"))


class InstallTest(unittest.TestCase):
    def test_install_merges_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            settings = Path(d) / ".claude" / "settings.json"
            settings.parent.mkdir()
            other = {"matcher": "Bash", "hooks": [{"type": "command", "command": "./mine.sh"}]}
            settings.write_text(json.dumps({"model": "opus", "hooks": {"PreToolUse": [other]}}))
            cwd = os.getcwd()
            os.chdir(d)
            try:
                with mock.patch("sys.stdout", io.StringIO()):
                    cli.main(["install"])
                    cli.main(["install"])
            finally:
                os.chdir(cwd)
            data = json.loads(settings.read_text())
            self.assertEqual(data["model"], "opus")
            entries = data["hooks"]["PreToolUse"]
            self.assertEqual(entries[0], other)
            ours = [h for e in entries for h in e["hooks"] if "autoguard" in h["command"]]
            self.assertEqual(len(ours), 1)


if __name__ == "__main__":
    unittest.main()

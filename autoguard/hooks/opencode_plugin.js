// Auto-Guard plugin for opencode. Written by `autoguard install --agent opencode`; re-run that to update it.
// Before each tool call it runs `python -m autoguard hook --agent opencode` and blocks the call if told to.
// opencode plugins can only allow or throw, so a block is a thrown error: the model sees the reason.
import { spawn } from "node:child_process"

const PYTHON = __AUTOGUARD_PYTHON__
const ARGS = ["-m", "autoguard", "hook", "--agent", "opencode"]
const TIMEOUT_MS = 30000
const REINSTALL = "Re-run: autoguard install --agent opencode"

// Read-only and internal tools go straight through. Everything else, MCP tools included, is checked.
const SKIP = new Set(["read", "glob", "grep", "list", "todowrite", "todoread", "question", "skill", "invalid", "lsp", "plan"])

const tasks = new Map() // sessionID -> latest user message, so the guard knows what was asked

function check(payload, cwd) {
  return new Promise((resolve) => {
    let stderr = ""
    let timedOut = false
    let child
    try {
      child = spawn(PYTHON, ARGS, { cwd, stdio: ["pipe", "ignore", "pipe"] })
    } catch (e) {
      return resolve({ failed: e.message })
    }
    const timer = setTimeout(() => {
      timedOut = true
      child.kill()
    }, TIMEOUT_MS)
    child.stderr.on("data", (d) => (stderr += d))
    child.stdin.on("error", () => {})
    child.on("error", (e) => {
      clearTimeout(timer)
      resolve({ failed: e.message })
    })
    child.on("close", (code) => {
      clearTimeout(timer)
      // Exit 2 alone isn't enough: argparse also exits 2, e.g. when an older autoguard doesn't know this agent.
      const reason = stderr.split("\n").find((line) => line.startsWith("Auto-Guard "))
      if (timedOut) resolve({ failed: "timed out" })
      else if (code === 0) resolve({})
      else if (code === 2 && reason) resolve({ blocked: reason.trim() })
      else resolve({ failed: "exit " + code + (stderr.trim() ? ": " + stderr.trim().slice(-300) : "") })
    })
    child.stdin.end(JSON.stringify(payload))
  })
}

export const AutoGuard = async ({ directory }) => ({
  "chat.message": async (input, output) => {
    try {
      const text = (output.parts || []).filter((p) => p.type === "text" && p.text).map((p) => p.text).join(" ").trim()
      if (!text) return
      if (tasks.size >= 200) tasks.delete(tasks.keys().next().value)
      tasks.set(input.sessionID, text.slice(0, 2000))
    } catch {}
  },
  "tool.execute.before": async (input, output) => {
    if (SKIP.has(input.tool)) return
    const result = await check(
      { tool: input.tool, args: output.args, cwd: directory, session_id: input.sessionID, task: tasks.get(input.sessionID) || "" },
      directory,
    )
    if (result.blocked) throw new Error(result.blocked)
    // A guard that can't run blocks the call rather than silently letting it through.
    if (result.failed) throw new Error("Auto-Guard could not run (" + result.failed + "). " + REINSTALL)
  },
})

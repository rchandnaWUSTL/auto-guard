# Auto-Guard

Auto-Guard checks every tool call your coding agent makes before it runs. It sends the proposed call and your request to [Jev](https://typesafe.ai), TypeSafe's decision model, and gets back one of three verdicts:

| Verdict | What happens |
|---|---|
| 🟢 **allow** | The call runs normally. |
| 🟡 **escalate** | You're asked to approve it, with a one-line reason written by an LLM. |
| 🔴 **block** | The call doesn't run. The agent is told why and tries something else. |

A check takes about 0.4s and costs about $0.000025.

[![Jev answers five safety questions in one request, in 419ms, while the same check with Claude Sonnet 5 takes 1,992ms](https://raw.githubusercontent.com/rchandnaWUSTL/auto-guard/main/demo/out/auto-guard-under-the-hood.gif)](https://github.com/rchandnaWUSTL/auto-guard/blob/main/demo/out/auto-guard-under-the-hood.mp4)

## Quick start

Install it (Python 3.9+, no other dependencies):

```bash
pip install agent-autoguard
```

Add an API key. An [OpenRouter key](https://openrouter.ai/keys) is the easiest option:

```bash
mkdir -p ~/.autoguard && echo 'OPENROUTER_API_KEY=sk-or-...' >> ~/.autoguard/env
```

Turn it on in your project for your agent:

```bash
autoguard install                   # Claude Code
autoguard install --agent cursor    # or codex, gemini, copilot, windsurf
```

Add `--user` to turn it on for every project. To confirm your key works:

```bash
autoguard check
# BLOCK      402ms  $0.000025  rm -rf /tmp/build && rm -rf ~/.aws
# ALLOW      402ms  $0.000025  ls -la build/
```

To watch decisions as they happen, run `autoguard console` and open http://127.0.0.1:8787.

## Supported agents

| Agent | Install | What gets checked | When Jev is unsure |
|---|---|---|---|
| Claude Code | `autoguard install` | Bash, file edits and writes, WebFetch | asks you |
| Cursor | `--agent cursor` | shell commands, MCP tools, file writes | asks you (shell and MCP), blocks (file writes) |
| GitHub Copilot CLI | `--agent copilot` | every tool call | asks you |
| OpenAI Codex CLI | `--agent codex` | shell commands, patches, MCP tools | blocks |
| Gemini CLI | `--agent gemini` | shell commands, file writes, MCP tools | blocks |
| Windsurf | `--agent windsurf` | shell commands, file writes, MCP tools | blocks |

Codex, Gemini CLI and Windsurf hooks can only allow or block, so an unsure call gets blocked with the reason shown. To let those calls through instead, set `"escalate_without_ask": "allow"` in your policy file.

Codex only runs a new hook after you approve it, so open Codex and run `/hooks` once after installing.

Claude Code has been tested end to end in real sessions. The other five adapters are built from each agent's hook documentation and tested against the documented inputs and outputs, but haven't been run inside those agents yet. If one misbehaves, please [open an issue](https://github.com/rchandnaWUSTL/auto-guard/issues).

Auto-Guard never approves anything on its own in Claude Code, Codex, Copilot or Windsurf. When it allows a call, the agent's normal permission rules still apply. Cursor needs every hook to answer, so there an allowed call gets an explicit `allow`.

## Use it in your own agent

```python
from autoguard import guard

decision = guard("bash", "rm -rf ./build && rm -rf ~/.aws", task="clean up the build directory")

decision.action      # "block"
decision.reasons     # ["risk 3.8/4 is critical", "destructive (0.95) and outside the task (in-scope 0.18)"]
decision.rationale   # LLM-written reason (escalations only)
decision.latency_ms  # 419.1
decision.cost        # 0.0000252
```

Call `guard(tool, args, task="", plan="")` after your agent picks a tool and before the tool runs. `args` can be a string or a dict.

## How it decides

Each check is one Jev request that asks five questions at once:

| Question | Answer type | Asks |
|---|---|---|
| `destructive` | probability | Does it irreversibly delete, overwrite or leak data? |
| `in_scope` | probability | Is it what the user asked for? |
| `sensitive` | probability | Does it touch credentials, secrets, production or payments? |
| `action_class` | choice | read, local-write, network, destructive or privileged |
| `risk` | 0–4 scale | none, low, medium, high or critical |

A call is blocked when its risk is critical, or when it's destructive, out of scope and high-risk. It's escalated when the risk is high, it touches sensitive systems, the action is privileged, or Jev isn't confident. Everything else is allowed. If Jev can't be reached, the call is escalated, and you can change that.

## Configuration

Auto-Guard reads API keys from environment variables first, then from `.env.local` or `.env` in the current folder or any parent, then from `~/.autoguard/env`.

| Variable | Get one | Used for |
|---|---|---|
| `OPENROUTER_API_KEY` | [openrouter.ai/keys](https://openrouter.ai/keys) | Jev checks and the written escalation reasons |
| `TYPESAFE_API_KEY` | [console.typesafe.ai](https://console.typesafe.ai/keys) (early access) | Jev checks, direct from TypeSafe |

If both are set, OpenRouter is used. With only a TypeSafe key, escalations work but come without a written reason.

To change a threshold, put a JSON file at `.autoguard.json` (one project) or `~/.autoguard/policy.json` (all projects):

```json
{
  "block_risk": 3.5,
  "escalate_risk": 2.5,
  "escalate_sensitive": 0.7,
  "on_error": "escalate",
  "escalate_without_ask": "block",
  "escalation_model": "anthropic/claude-haiku-4.5",
  "spend_cap_usd": 2.5
}
```

Every setting and its default is in [`autoguard/policy.py`](https://github.com/rchandnaWUSTL/auto-guard/blob/main/autoguard/policy.py).

Every decision is appended to `~/.autoguard/decisions.jsonl`, or to the path in `AUTOGUARD_LOG`. Once the logged spend reaches `spend_cap_usd`, escalations stop calling the LLM.

## Commands

| Command | Does |
|---|---|
| `autoguard install [--agent NAME] [--user]` | Adds the hook to your agent's config. Existing settings are kept, and running it twice is safe. |
| `autoguard check` | Runs two sample calls to check your key |
| `autoguard console` | Opens the live decision dashboard |
| `autoguard demo [block\|escalate\|all]` | Runs the demo calls through the real guard |
| `autoguard eval` | Scores the policy on the labeled test calls (run it from a clone of this repo) |

## Results

On a held-out set of 20 calls that was never used for tuning ([`evals/holdout.jsonl`](https://github.com/rchandnaWUSTL/auto-guard/blob/main/evals/holdout.jsonl)):

| | Safe allowed | Dangerous caught | Ambiguous escalated | Median latency | Cost per check |
|---|---|---|---|---|---|
| **Auto-Guard (Jev)** | **8/8** | **8/8** | **4/4** | **428ms** | **$0.000025** |
| Claude Haiku 4.5 as the guard | 8/8 | 8/8 | 3/4 | 823ms | $0.00012 |
| Claude Sonnet 5 as the guard | 7/8 | 5/8 | 1/4 | 1,992ms | $0.00032 |

On the 61-call set the thresholds were tuned on, it allowed 26/26 safe calls and caught 25/25 dangerous ones.

Latency was measured from a laptop through OpenRouter with a new connection per call, which is how the hooks run. Calling `guard()` repeatedly in one process reuses the connection and brings the median down to about 310–360ms.

## Limits

Auto-Guard is a filter and will sometimes miss things, so keep backups, scoped credentials and sandboxing.

Jev's "in scope" answer is its weakest signal and sometimes misjudges requests with several parts. Scope only counts toward a block when the risk is also high.

It can block something you asked for. "Delete my old AWS config" gets blocked because deleting credentials is high-risk, so run commands like that yourself.

Each check adds about 0.3–0.6s. Next to an agent's own model calls that's hard to notice.

## Development

```bash
python3 -m unittest discover tests      # offline tests, no API calls
python3 -m autoguard eval               # re-score with cached Jev answers (free)
cd demo && npm install && npm run video # rebuild the demo videos from recorded Jev responses
```

```
autoguard/   guard(), policy, Jev client, agent hooks, CLI, live console
evals/       labeled test calls and cached Jev answers
tests/       unit tests
demo/        demo scenes and the video pipeline (Playwright and Remotion)
```

## License

MIT. See [LICENSE](https://github.com/rchandnaWUSTL/auto-guard/blob/main/LICENSE).

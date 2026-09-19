# Auto-Guard launch kit

Nothing here has been posted. A human posts it.

**Assets** (in `demo/out/`)
- `auto-guard-landscape-1920x1080.mp4`: primary video for X (13.0s, loops)
- `auto-guard-square-1080x1080.mp4`: square version (13.0s, loops)
- `auto-guard-escalate.mp4`: reply clip for tweet 3 (10.0s)

To regenerate all three: `cd demo && npm run video`.

## Read first: what I changed from the draft and why

Every number below comes from `demo/metrics.json` (held-out eval) or the recorded demo scene. The draft's placeholder numbers didn't hold up.

| Draft said | Measured | Changed to |
|---|---|---|
| "150ms" | Demo call: **419ms**. p50 **428ms**, p95 524ms (held-out, cold connection per call) | "under half a second" / "419ms" |
| "$0.0003" per check | **$0.000025** per check (**12x cheaper** than the draft said) | "$0.000025" |
| "~400x cheaper than an LLM" / "LLM guard takes 3–30s" | vs **Claude Sonnet 5** as a one-word guard: **4.7x faster, 12.6x cheaper** (1,992ms p50, 3.9s p95). vs **Claude Haiku 4.5**: **1.9x faster, 4.8x cheaper** (823ms p50) | "~5x faster and ~13x cheaper than asking Sonnet" |
| "Jev handles the obvious 95%" | Every safe call in both test sets went straight through (34/34). On a test set that's mostly dangerous on purpose, 65–74% of calls were settled without escalation. | Say what's true; see tweet 3 |
| "I told my coding agent to clean up a repo. It tried to run `rm -rf ~/.aws`." | **Didn't happen.** In live Claude Code tests, Claude refused a planted instruction to delete credentials. The video is a scripted scenario with real Jev decisions. | Rewritten as a scenario; disclosure added in tweet 3 |
| "locked inside Claude Code and Cursor" | LangChain already ships an open `AutoModeMiddleware` on Jev | Softened to "mostly lives inside closed harnesses" |
| `guard(tool_call, context)` | The real signature is `guard(tool, args, task=...)` | Fixed |
| "@typesafeai" | Confirmed: [x.com/typesafeai](https://x.com/typesafeai) | Kept |

If you'd rather post the draft's numbers, don't: people will run it, measure about 400ms, and reply with that.

---

## Primary tweet (post with the landscape video)

> Your coding agent is one bad instruction away from `rm -rf ~/.aws`.
>
> Auto-Guard checks every tool call before it runs. This one got blocked in 419ms, for $0.000025.
>
> Every agent should have this. The "is this dangerous?" check mostly lives inside closed harnesses. This one is open, and it's 2 lines in yours.
>
> install 👇 https://github.com/rchandnaWUSTL/auto-guard

## Thread (reply to your own tweet, in order)

**2/**
> It's not an LLM babysitter. That's too slow and too pricey to run on every call.
>
> It's a System One model (Jev, @typesafeai): 5 typed safety questions answered in one request, with calibrated confidence.
>
> Measured: ~5x faster and ~13x cheaper than asking Claude Sonnet the same thing. Small enough to run on every call.

**3/** (attach `auto-guard-escalate.mp4`)
> "so it's just a classifier"
>
> Here's an ambiguous call: delete old DB rows. Jev isn't sure, so it escalates, and a full LLM writes the reason you see before approving.
>
> The fast gate settles the obvious calls. The expensive model only comes in when it's actually unclear.
>
> (Scripted demo, real Jev + Claude responses. Evals in the repo.)

**4/**
> 2 lines to add it to Claude Code:
> `pip install git+https://github.com/rchandnaWUSTL/auto-guard`
> `autoguard install`
>
> Or wrap any agent:
> `from autoguard import guard`
> `guard("bash", cmd, task=user_request).action  # allow / block / escalate`
>
> Built on @typesafeai Jev.

## Alternate opening hooks (A/B, pick one for tweet 1)

- **Stat-led:**
  > A safety check on every tool call your agent makes. ~0.4s. $0.000025. ~13x cheaper than asking an LLM "is this safe?", so you can actually run it on every call. [video]
- **Hot take, invites replies:**
  > Your coding agent will eventually run a command that nukes something. The guardrail that stops it shouldn't be locked inside a closed harness. Here's an open one, 2 lines to install: [video]

## Posting notes (for the human)

- **When:** Tuesday about 9am ET (next one: Sep 22, 2026). Check that no major model launch is happening that day.
- **Replies:** answer the first 10–15 comments within the first hour. Reply chains are the highest-ranked signal.
- **"2 lines" is literally true now:** `pip install` + `autoguard install` writes the Claude Code hook for you. The `guard()` library call is also two lines.
- **Before posting:**
  - Repo link is filled in: https://github.com/rchandnaWUSTL/auto-guard
  - The repo is already **public** but empty. Push the code (merge the `auto-guard` branch to `main`) before posting.
  - Run the 2-line install from a clean machine.
- **Have the limits section ready to link** (README → "Limits"). Expect "false negatives?" and "why not just a sandbox?" replies, and answer with it rather than arguing.
- **Likely pushback, with honest answers:**
  - *"400ms isn't real-time."* It's per tool call, and next to the agent's own multi-second model turns it's invisible.
  - *"Haiku gets the same accuracy."* On our small held-out set, Haiku matched Jev on dangerous calls. Jev's edge is speed, price and typed, calibrated outputs, not higher accuracy. Don't claim otherwise.

# Auto-Guard launch kit

Nothing here has been posted. A human posts it.

**Assets** (in `demo/out/`)
- `auto-guard.mp4`: main tweet video (14s, loops, no captions)
- `auto-guard-under-the-hood.mp4`: reply video with Jev's five answers and the timing race against Claude Sonnet 5 (17.6s, loops)

To regenerate them: `cd demo && npm run render` (or `node edit/render.mjs Hero HeroTech`).

**Install:** `pip install agent-autoguard` ([PyPI](https://pypi.org/project/agent-autoguard/)), MIT licensed.

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

## The thread

The repo link stays out of tweet 1 (X shows posts with links to fewer people). It goes in tweet 3.

**Tweet 1** (attach `auto-guard.mp4`)
> Your coding agent is one bad instruction away from running rm -rf ~/.aws.
>
> I built Auto-Guard to check every tool call before it runs. Here it stops the credentials delete and lets the build cleanup through.
>
> It's open source. Install is in the replies.

**Tweet 2** (reply, attach `auto-guard-under-the-hood.mp4`)
> Each check is one request to Jev (@typesafeai). It answers five questions at once: is it destructive, did you ask for it, does it touch secrets, what kind of action is it, how risky is it.
>
> It took 419ms and cost $0.000025. Claude Sonnet 5 takes about 2 seconds and 13x the cost.

**Tweet 3** (reply)
> If Jev isn't confident, Auto-Guard asks you to approve the call and shows a one-line reason from a larger model.
>
> Adding it to Claude Code takes two commands:
> pip install agent-autoguard
> autoguard install
>
> Code, evals and known limits: https://github.com/rchandnaWUSTL/auto-guard

Lengths: 253, 279 and 259 characters. Tweet 2 is close to the limit.

## Alternate opening hooks (A/B, pick one for tweet 1)

- **Stat-led:**
  > Every tool call your agent makes can get a safety check that takes about 0.4s and costs $0.000025, which is cheap enough to leave on for every call. [video]
- **Hot take, invites replies:**
  > Sooner or later your coding agent will run a command that deletes something it shouldn't. The check that stops it shouldn't only exist inside closed tools, so I built an open one. [video]

## Posting notes (for the human)

- **When:** Tuesday about 9am ET (next one: Sep 22, 2026). Check that no major model launch is happening that day.
- **Replies:** answer the first 10–15 comments within the first hour. Reply chains are the highest-ranked signal.
- **Two commands is literally true:** `pip install agent-autoguard` + `autoguard install` writes the Claude Code hook for you.
- **Before posting:** run `pip install agent-autoguard` and `autoguard install` on a machine that has never had it, and open the repo link logged out to check it looks right.
- **Have the limits section ready to link** (README → "Limits"). Expect "false negatives?" and "why not just a sandbox?" replies, and answer with it rather than arguing.
- **Likely pushback, with honest answers:**
  - *"400ms isn't real-time."* It's per tool call, and next to the agent's own multi-second model turns it's invisible.
  - *"Haiku gets the same accuracy."* On our small held-out set, Haiku matched Jev on dangerous calls. Jev's edge is speed, price and typed, calibrated outputs, not higher accuracy. Don't claim otherwise.

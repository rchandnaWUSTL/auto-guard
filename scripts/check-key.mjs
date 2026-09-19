// Verifies Jev access with one fantasy start/sit call.
// Uses OpenRouter if OPENROUTER_API_KEY is set, otherwise TypeSafe direct (TYPESAFE_API_KEY).
// Usage: node --env-file=.env.local scripts/check-key.mjs
const providers = {
  openrouter: {
    key: process.env.OPENROUTER_API_KEY,
    url: "https://openrouter.ai/api/alpha/decisions",
    model: "typesafe/jev-1.13",
  },
  typesafe: {
    key: process.env.TYPESAFE_API_KEY,
    url: "https://api.typesafe.ai/v1/systemone",
    model: "jev-latest",
  },
};
const name = providers.openrouter.key ? "openrouter" : "typesafe";
const { key, url, model } = providers[name];
if (!key) {
  console.error("Set OPENROUTER_API_KEY or TYPESAFE_API_KEY in .env.local (see .env.example).");
  process.exit(1);
}

const started = performance.now();
const res = await fetch(url, {
  method: "POST",
  headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
  body: JSON.stringify({
    model,
    state:
      "PPR league, Week 3 flex spot. Options: WR A faces the league's worst pass defense but is questionable (hamstring). " +
      "RB B is a healthy workhorse facing a top-3 run defense. TE C has 9+ targets in both games so far.",
    questions: {
      flex: {
        type: "choice",
        instructions: "Who should start in the flex?",
        criteria: { wr_a: "WR A", rb_b: "RB B", te_c: "TE C" },
      },
      injury_risk: {
        type: "noul",
        instructions: "WR A's injury status meaningfully threatens his fantasy output this week",
      },
    },
  }),
});
const ms = Math.round(performance.now() - started);

const body = await res.text();
if (!res.ok) {
  console.error(`[${name}] HTTP ${res.status} after ${ms}ms: ${body}`);
  process.exit(1);
}
console.log(`[${name}] Key works (${ms}ms). Jev says:\n` + JSON.stringify(JSON.parse(body), null, 2));

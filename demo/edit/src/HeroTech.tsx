// Reply-tweet video: the same story as Hero, plus what's under the hood. The shield is Jev,
// five questions are answered in one request, and a timer race against an LLM guard.
// All numbers come from the recorded scene (demo/scenes/block.json) and measured evals (demo/metrics.json).
import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { BG, Folder, GREEN, INK, MONO, MUTED, RED, Shield, T } from "./Hero";

type Answers = {
  destructive: { noul: number };
  in_scope: { noul: number };
  sensitive: { noul: number };
  action_class: { choice: string };
  risk: { score: number };
};
type Step = { args: string; decision: { action: string; latency_ms: number; cost: number; answers: Answers } };
export type TechProps = {
  steps: Step[];
  llm: { name: string; latency_ms: number; cost: number };
};

const SANS = '-apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif';
const SOFT = "#8b909c";
const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

// Layout (1920x1080): story on top, the Jev panel below.
const TERM = { x: 80, y: 70, w: 900, h: 360 };
const LINE_Y = [TERM.y + 150, TERM.y + 260];
const SHIELD = { x: 1170, y: 235, size: 1.05 };
const AWS = { x: 1640, y: 140 };
const BUILD = { x: 1640, y: 370 };
const FOLDER_SIZE = 0.9;
const PANEL = { x: 80, y: 530, w: 1760, h: 480 };

const GAP_AFTER_TIMERS = 2.0; // after the timers stop: before the next command, and before the loop resets
const ORIENT = 2.0;
const RISK_NAMES = ["none", "low", "medium", "high", "critical"];

// Typing speed matches the ~120 wpm budget for shell commands: about 0.45s per token.
const typeSeconds = (cmd: string) => Math.max(T.type, cmd.split(/\s+/).length * 0.45);

function schedule(steps: Step[], llmMs: number) {
  const beats: { typeAt: number; typeDur: number; enterAt: number; reach: number; verdict: number; llmDone: number; hit: number }[] = [];
  let typeAt = ORIENT;
  steps.forEach((s) => {
    const typeDur = typeSeconds(s.args);
    const enterAt = typeAt + typeDur + T.pauseBeforeEnter;
    const reach = enterAt + T.beam;
    const verdict = reach + s.decision.latency_ms / 1000;
    const llmDone = reach + llmMs / 1000;
    beats.push({ typeAt, typeDur, enterAt, reach, verdict, llmDone, hit: verdict + T.beam });
    typeAt = llmDone + GAP_AFTER_TIMERS;
  });
  return { beats, resetAt: typeAt, end: typeAt + T.reset + 0.4 };
}

export function techSeconds(p: TechProps) {
  return schedule(p.steps, p.llm.latency_ms).end;
}

const fmtMs = (ms: number) => `${Math.round(ms).toLocaleString("en-US")}ms`;
const fmtCost = (c: number) => (c < 0.0001 ? `$${c.toFixed(6)}` : `$${c.toFixed(5)}`);

export const HeroTech: React.FC<TechProps> = ({ steps, llm }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const sched = schedule(steps, llm.latency_ms);
  const reset = interpolate(t, [sched.resetAt, sched.resetAt + T.reset], [0, 1], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  const live = 1 - reset;

  // The beat currently on the shield (the later one once its command is entered).
  let idx = 0;
  sched.beats.forEach((b, i) => { if (t >= b.enterAt) idx = i; });
  const b = sched.beats[idx];
  const step = steps[idx];
  const d = step.decision;
  const blocked = d.action === "block";
  const verdictColor = blocked ? RED : GREEN;

  const onShield = t >= b.enterAt;
  const scanning = t >= b.reach && t < b.verdict;
  const decided = t >= b.verdict;
  const shieldColor = !onShield || !decided || reset > 0.5 || (idx === 0 && t >= sched.beats[1].typeAt) ? MUTED : verdictColor;
  const since = t - b.verdict;
  const pulse = decided ? interpolate(since, [0, 0.12, 0.45], [0, 1, 0], clamp) : 0;
  const shake = decided && blocked && onShield ? Math.sin(since * 70) * 12 * Math.max(0, 1 - since / 0.4) : 0;

  // Terminal
  const line = (i: number) => {
    const bi = sched.beats[i];
    const s = steps[i];
    if (t < bi.typeAt) return null;
    const cmd = s.args;
    const typed = Math.floor(cmd.length * interpolate(t, [bi.typeAt, bi.typeAt + bi.typeDur], [0, 1], clamp));
    const done = t >= bi.verdict;
    const isBlock = s.decision.action === "block";
    const c = done ? (isBlock ? RED : GREEN) : INK;
    const caret = !done && Math.floor(t * 2.5) % 2 === 0 && t < bi.enterAt;
    return (
      <div key={i} style={{ position: "absolute", left: 44, top: LINE_Y[i] - TERM.y - 36, display: "flex", alignItems: "center", gap: 20, opacity: live }}>
        <span style={{ color: MUTED }}>$</span>
        <span style={{ color: c, textDecoration: done && isBlock ? "line-through" : "none", textDecorationThickness: 4 }}>{cmd.slice(0, typed)}</span>
        {caret && <span style={{ width: 22, height: 42, background: INK, display: "inline-block" }} />}
        {done && <span style={{ color: c, fontWeight: 800 }}>{isBlock ? "✕" : "✓"}</span>}
      </div>
    );
  };
  const idleCaret = t < sched.beats[0].typeAt || reset > 0.99;

  // Beam from terminal to shield, and through to the folder when allowed.
  const beam = (i: number) => {
    const bi = sched.beats[i];
    const isBlock = steps[i].decision.action === "block";
    if (t < bi.enterAt || t > bi.hit + 0.5) return null;
    const from = { x: TERM.x + TERM.w + 16, y: LINE_Y[i] };
    const toShield = { x: SHIELD.x - 95 * SHIELD.size, y: SHIELD.y };
    const out = { x: SHIELD.x + 95 * SHIELD.size, y: SHIELD.y };
    const target = isBlock ? AWS : BUILD;
    const tgt = { x: target.x - 135 * FOLDER_SIZE, y: target.y };
    const k1 = interpolate(t, [bi.enterAt, bi.reach], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
    const k2 = isBlock ? 0 : interpolate(t, [bi.verdict, bi.hit], [0, 1], { ...clamp, easing: Easing.in(Easing.cubic) });
    const col = t >= bi.verdict ? (isBlock ? RED : GREEN) : INK;
    const fade = interpolate(t, [bi.verdict + (isBlock ? 0.2 : 0.35), bi.hit + 0.5], [1, 0], clamp);
    return (
      <g key={i} opacity={fade * live}>
        <path d={`M${from.x} ${from.y} L${toShield.x} ${toShield.y} M${out.x} ${out.y} L${tgt.x} ${tgt.y}`} stroke={col} strokeOpacity={0.25} strokeWidth={4} strokeDasharray="12 12" fill="none" />
        <line x1={from.x} y1={from.y} x2={from.x + (toShield.x - from.x) * k1} y2={from.y + (toShield.y - from.y) * k1} stroke={col} strokeWidth={8} strokeLinecap="round" />
        {k2 > 0 && <line x1={out.x} y1={out.y} x2={out.x + (tgt.x - out.x) * k2} y2={out.y + (tgt.y - out.y) * k2} stroke={col} strokeWidth={8} strokeLinecap="round" />}
      </g>
    );
  };

  const bBuild = sched.beats[1];
  const gone = interpolate(t, [bBuild.hit, bBuild.hit + 0.5], [0, 1], { ...clamp, easing: Easing.in(Easing.cubic) });
  const buildScale = Math.max((1 - gone), reset);
  const awsGlow = t >= sched.beats[0].verdict ? interpolate(t - sched.beats[0].verdict, [0, 0.2, 1.6], [0, 1, 0], clamp) : 0;

  // ---------- Panel: five questions in one request + timer race ----------
  const panelOn = onShield && t >= b.reach && reset < 0.5; // empties during the loop reset, like the opening frame
  const sinceReach = t - b.reach;
  const jevMs = panelOn ? Math.min(sinceReach * 1000, d.latency_ms) : 0;
  const llmMs = panelOn ? Math.min(sinceReach * 1000, llm.latency_ms) : 0;
  const fillK = panelOn ? easeOut(Math.min(1, jevMs / d.latency_ms)) : 0; // all five fill together, over Jev's real latency
  const showValues = panelOn && decided;
  const a = d.answers;
  const rows: { label: string; frac: number; value: string; color: string }[] = [
    { label: "destructive", frac: a.destructive.noul, value: a.destructive.noul.toFixed(2), color: a.destructive.noul > 0.5 ? RED : SOFT },
    { label: "in scope", frac: a.in_scope.noul, value: a.in_scope.noul.toFixed(2), color: a.in_scope.noul < 0.5 ? RED : GREEN },
    { label: "sensitive", frac: a.sensitive.noul, value: a.sensitive.noul.toFixed(2), color: a.sensitive.noul > 0.7 ? RED : SOFT },
    { label: "action", frac: 1, value: a.action_class.choice, color: ["destructive", "privileged"].includes(a.action_class.choice) ? RED : SOFT },
    { label: "risk", frac: a.risk.score / 4, value: RISK_NAMES[Math.round(a.risk.score)], color: a.risk.score >= 3.5 ? RED : a.risk.score >= 2.5 ? "#ffb340" : SOFT },
  ];
  const SCALE_MS = Math.max(llm.latency_ms, d.latency_ms) * 1.02;
  const race = [
    { name: "Jev", sub: "by TypeSafe", ms: jevMs, total: d.latency_ms, cost: d.cost, color: decided ? verdictColor : INK, bold: true },
    { name: llm.name, sub: "median", ms: llmMs, total: llm.latency_ms, cost: llm.cost, color: SOFT, bold: false },
  ];

  return (
    <AbsoluteFill style={{ background: BG }}>
      {/* Terminal */}
      <div style={{ position: "absolute", left: TERM.x, top: TERM.y, width: TERM.w, height: TERM.h, background: "#12141a", borderRadius: 24,
        border: "2px solid #23262e", overflow: "hidden", fontFamily: MONO, fontSize: 38 }}>
        <div style={{ height: 54, background: "#191c23", display: "flex", gap: 12, alignItems: "center", paddingLeft: 24 }}>
          {[0, 1, 2].map((i) => <span key={i} style={{ width: 16, height: 16, borderRadius: 8, background: "#3a3e47" }} />)}
        </div>
        {line(0)}
        {line(1)}
        {idleCaret && (
          <div style={{ position: "absolute", left: 44, top: LINE_Y[0] - TERM.y - 36, display: "flex", alignItems: "center", gap: 20 }}>
            <span style={{ color: MUTED }}>$</span>
            {Math.floor(t * 2.5) % 2 === 0 && <span style={{ width: 22, height: 42, background: INK, display: "inline-block" }} />}
          </div>
        )}
      </div>

      <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
        {beam(0)}
        {beam(1)}
        <Shield x={SHIELD.x} y={SHIELD.y} size={SHIELD.size} color={shieldColor} scan={scanning ? (t - b.reach) / 0.5 : 0} pulse={pulse} shake={shake} />
        <Folder x={AWS.x} y={AWS.y} size={FOLDER_SIZE} icon="key" label="~/.aws" scale={1} opacity={1} glow={awsGlow} glowColor={RED} />
        <Folder x={BUILD.x} y={BUILD.y} size={FOLDER_SIZE} icon="box" label="./build" scale={buildScale} opacity={Math.max(1 - gone, reset)} glow={0} glowColor={GREEN} />
      </svg>

      {/* Panel */}
      <div style={{ position: "absolute", left: PANEL.x, top: PANEL.y, width: PANEL.w, height: PANEL.h, background: "#12141a", borderRadius: 24,
        border: "2px solid #23262e", display: "grid", gridTemplateColumns: "1fr 1fr", fontFamily: SANS, color: INK }}>
        <div style={{ padding: "40px 48px", borderRight: "2px solid #23262e" }}>
          <div style={{ fontSize: 30, color: SOFT, marginBottom: 30 }}>1 request · 5 questions answered at once</div>
          {rows.map((r) => (
            <div key={r.label} style={{ display: "grid", gridTemplateColumns: "190px 1fr 240px", alignItems: "center", gap: 24, height: 64 }}>
              <div style={{ fontSize: 34, color: SOFT }}>{r.label}</div>
              <div style={{ height: 18, background: "#22252d", borderRadius: 9, overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${r.frac * fillK * 100}%`, background: showValues ? r.color : INK, borderRadius: 9 }} />
              </div>
              <div style={{ fontFamily: MONO, fontSize: 34, textAlign: "right", color: showValues ? r.color : "transparent" }}>{r.value}</div>
            </div>
          ))}
        </div>
        <div style={{ padding: "40px 48px", display: "flex", flexDirection: "column", gap: 40 }}>
          <div style={{ fontSize: 30, color: SOFT, marginBottom: -6 }}>same safety check, timed</div>
          {race.map((r) => {
            const finished = panelOn && r.ms >= r.total;
            return (
              <div key={r.name}>
                <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
                  <div style={{ whiteSpace: "nowrap" }}>
                    <span style={{ fontSize: 40, fontWeight: r.bold ? 800 : 600, color: r.bold ? INK : SOFT }}>{r.name}</span>
                    <span style={{ fontSize: 26, color: SOFT, marginLeft: 14 }}>{r.sub}</span>
                  </div>
                  <span style={{ fontFamily: MONO, fontSize: 64, fontWeight: 700, color: finished ? r.color : panelOn ? INK : MUTED }}>
                    {fmtMs(r.ms)}
                  </span>
                </div>
                <div style={{ height: 22, background: "#22252d", borderRadius: 11, overflow: "hidden", marginTop: 14 }}>
                  <div style={{ height: "100%", width: `${(r.ms / SCALE_MS) * 100}%`, background: finished ? r.color : INK, borderRadius: 11 }} />
                </div>
                <div style={{ fontFamily: MONO, fontSize: 30, color: finished ? SOFT : "transparent", marginTop: 12 }}>{fmtCost(r.cost)} per check</div>
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};

function easeOut(x: number) {
  return 1 - Math.pow(1 - x, 3);
}

// One-shot launch video that reads without captions: an agent tries to delete two folders,
// the shield (Auto-Guard) stops the credentials delete and lets the build cleanup through.
import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { Timeline } from "./Video";

export const BG = "#0b0c0f";
export const INK = "#e6e8ee";
export const MUTED = "#5d6270";
export const RED = "#ff5a4f";
export const GREEN = "#3ddc84";
export const MONO = 'ui-monospace, "SF Mono", Menlo, monospace';

const TERM = { x: 100, y: 300, w: 920, h: 480 };
const ICON = 1.3; // folders and shield are drawn at this scale so they read on a phone
const SHIELD = { x: 1255, y: 540 };
const AWS = { x: 1640, y: 340 };
const BUILD = { x: 1640, y: 740 };
const LINE_Y = [TERM.y + 175, TERM.y + 305];
const START = { x: TERM.x + TERM.w, y: 0 };

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

type Beat = { cmd: string; typeAt: number; enterAt: number; latency: number; target: { x: number; y: number }; blocked: boolean };

function beats(t: Timeline, secondType: number): Beat[] {
  const [a, b] = t.steps;
  return [
    { cmd: "rm -rf ~/.aws", typeAt: T.firstType, enterAt: T.firstType + T.type + T.pauseBeforeEnter,
      latency: a.latency_ms / 1000, target: AWS, blocked: true },
    { cmd: "rm -rf ./build", typeAt: secondType, enterAt: secondType + T.type + T.pauseBeforeEnter,
      latency: b.latency_ms / 1000, target: BUILD, blocked: false },
  ];
}

// Pacing, in seconds. Adults read ~238 wpm (Brysbaert 2019, ~4 words/s); shell commands read slower,
// so we budget ~120 wpm: 3 tokens per command -> 1.5s of typing, then time to see the outcome.
// Jev's latency itself is never stretched; it comes from the recorded scene.
export const T = {
  type: 1.5,             // type one command
  pauseBeforeEnter: 0.5,
  beam: 0.4,             // beam travel, slow enough to follow with the eye
  holdOutcome: 2.5,      // look at what happened before the next thing starts
  reset: 0.8,
  firstType: 1.5,        // first 1.5s: take in the scene and read the two folder names
};
const BEAM_TO_SHIELD = T.beam;
const BEAM_TO_TARGET = T.beam;
const POOF = 0.5;

export function heroSeconds(t: Timeline) {
  return schedule(t).end;
}

function schedule(t: Timeline) {
  const [a, b] = t.steps;
  const aVerdict = T.firstType + T.type + T.pauseBeforeEnter + T.beam + a.latency_ms / 1000;
  const secondType = aVerdict + T.holdOutcome;
  const bHit = secondType + T.type + T.pauseBeforeEnter + T.beam + b.latency_ms / 1000 + T.beam;
  const resetAt = bHit + POOF + T.holdOutcome;
  return { aVerdict, secondType, resetAt, end: resetAt + T.reset + 0.4 };
}

export const Folder: React.FC<{ x: number; y: number; icon: "key" | "box"; label: string; scale: number; opacity: number; glow: number; glowColor: string; size?: number }> =
  ({ x, y, icon, label, scale, opacity, glow, glowColor, size = ICON }) => (
    <g transform={`translate(${x} ${y}) scale(${scale * size})`} opacity={opacity}>
      {glow > 0 && <rect x={-130} y={-100} width={260} height={200} rx={34} fill={glowColor} opacity={0.18 * glow} />}
      <path d="M-100 -70 h70 l20 22 h110 a14 14 0 0 1 14 14 v110 a14 14 0 0 1 -14 14 h-200 a14 14 0 0 1 -14 -14 v-132 a14 14 0 0 1 14 -14 z"
        fill="#1c1f26" stroke={glow > 0 ? glowColor : "#3a3f4b"} strokeWidth={5} />
      {icon === "key" ? (
        <g stroke="#ffd479" strokeWidth={9} fill="none" strokeLinecap="round">
          <circle cx={-28} cy={10} r={22} />
          <path d="M-6 10 h62 M34 10 v18 M52 10 v14" />
        </g>
      ) : (
        <g stroke="#9aa3b5" strokeWidth={8} fill="none" strokeLinejoin="round">
          <path d="M-40 -8 l40 -18 l40 18 v44 l-40 18 l-40 -18 z M-40 -8 l40 18 l40 -18 M0 10 v44" />
        </g>
      )}
      <text x={0} y={128} textAnchor="middle" fill="#8b909c" fontFamily={MONO} fontSize={38}>{label}</text>
    </g>
  );

export const Shield: React.FC<{ color: string; scan: number; pulse: number; shake: number; x?: number; y?: number; size?: number }> =
  ({ color, scan, pulse, shake, x = SHIELD.x, y = SHIELD.y, size = ICON }) => (
  <g transform={`translate(${x + shake} ${y}) scale(${size * (1 + 0.12 * pulse)})`}>
    {scan > 0 && (
      <circle r={120} fill="none" stroke={INK} strokeWidth={4} opacity={0.5}
        strokeDasharray="60 40" transform={`rotate(${scan * 360})`} />
    )}
    <path d="M0 -95 L80 -62 V0 C80 52 44 86 0 102 C-44 86 -80 52 -80 0 V-62 Z"
      fill={color === MUTED ? "#15171c" : color} fillOpacity={color === MUTED ? 1 : 0.2} stroke={color} strokeWidth={8} strokeLinejoin="round" />
    {color === RED && <path d="M-26 -22 L26 30 M26 -22 L-26 30" stroke={RED} strokeWidth={12} strokeLinecap="round" />}
    {color === GREEN && <path d="M-30 4 L-8 26 L32 -20" stroke={GREEN} strokeWidth={12} fill="none" strokeLinecap="round" strokeLinejoin="round" />}
  </g>
);

export const HeroVideo: React.FC<{ timeline: Timeline }> = ({ timeline }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const sched = schedule(timeline);
  const [A, B] = beats(timeline, sched.secondType);
  const RESET_AT = sched.resetAt;

  // Everything fades back to the opening state for a seamless loop.
  const reset = interpolate(t, [RESET_AT, RESET_AT + T.reset], [0, 1], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  const live = 1 - reset;

  const phase = (b: Beat) => {
    const reach = b.enterAt + BEAM_TO_SHIELD;
    const verdict = reach + b.latency;
    return { reach, verdict, hit: verdict + BEAM_TO_TARGET };
  };
  const pA = phase(A);
  const pB = phase(B);

  // Which beat is on the shield right now.
  const active = t >= B.enterAt ? B : A;
  const pa = active === A ? pA : pB;
  const scanning = t >= pa.reach && t < pa.verdict;
  const decided = t >= pa.verdict;
  const shieldColor = !decided || t < active.enterAt ? MUTED : active.blocked ? RED : GREEN;
  const sinceVerdict = t - pa.verdict;
  const pulse = decided ? interpolate(sinceVerdict, [0, 0.12, 0.45], [0, 1, 0], clamp) : 0;
  const shake = decided && active.blocked ? Math.sin(sinceVerdict * 70) * 14 * Math.max(0, 1 - sinceVerdict / 0.4) : 0;
  // Settle the shield back to idle while the second command is typed.
  const idleFrom = pA.verdict + T.holdOutcome;
  const shieldFade = t >= idleFrom && t < B.enterAt ? 0 : 1;
  const color = (t >= idleFrom && t < B.enterAt) || reset > 0.5 ? MUTED : shieldColor;

  // Terminal lines
  const line = (b: Beat, i: number) => {
    const p = i === 0 ? pA : pB;
    const typed = Math.floor(b.cmd.length * interpolate(t, [b.typeAt, b.typeAt + T.type], [0, 1], clamp));
    if (t < b.typeAt) return null;
    const done = t >= p.verdict;
    const c = done ? (b.blocked ? RED : GREEN) : INK;
    const caret = !done && Math.floor(t * 2.5) % 2 === 0 && t < b.enterAt;
    return (
      <div key={i} style={{ position: "absolute", left: 50, top: LINE_Y[i] - TERM.y - 40, display: "flex", alignItems: "center", gap: 22, opacity: live }}>
        <span style={{ color: MUTED }}>$</span>
        <span style={{ color: c, textDecoration: done && b.blocked ? "line-through" : "none", textDecorationThickness: 5 }}>{b.cmd.slice(0, typed)}</span>
        {caret && <span style={{ width: 30, height: 58, background: INK, display: "inline-block" }} />}
        {done && (
          <span style={{ color: c, fontWeight: 800, transform: `scale(${interpolate(t - p.verdict, [0, 0.15], [1.8, 1], clamp)})` }}>
            {b.blocked ? "✕" : "✓"}
          </span>
        )}
      </div>
    );
  };
  // Idle caret on the first line before anything is typed (also the loop's resting frame).
  const idleCaret = t < A.typeAt || reset > 0.99;
  const termShake = t >= pA.verdict ? Math.sin((t - pA.verdict) * 70) * 10 * Math.max(0, 1 - (t - pA.verdict) / 0.35) : 0;

  // Beams: a bright segment travelling terminal -> shield (-> folder if allowed).
  const beam = (b: Beat, i: number) => {
    const p = i === 0 ? pA : pB;
    if (t < b.enterAt || t > p.hit + 0.5) return null;
    const from = { x: START.x + 20, y: LINE_Y[i] };
    const toShield = { x: SHIELD.x - 95 * ICON, y: SHIELD.y };
    const k1 = interpolate(t, [b.enterAt, p.reach], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
    const col = t >= p.verdict ? (b.blocked ? RED : GREEN) : INK;
    const fadeOut = interpolate(t, [p.verdict + (b.blocked ? 0.2 : 0.35), p.hit + 0.5], [1, 0], clamp);
    const seg1 = { x: from.x + (toShield.x - from.x) * k1, y: from.y + (toShield.y - from.y) * k1 };
    const out = { x: SHIELD.x + 95 * ICON, y: SHIELD.y };
    const k2 = b.blocked ? 0 : interpolate(t, [p.verdict, p.hit], [0, 1], { ...clamp, easing: Easing.in(Easing.cubic) });
    const tgt = { x: b.target.x - 135 * ICON, y: b.target.y };
    const seg2 = { x: out.x + (tgt.x - out.x) * k2, y: out.y + (tgt.y - out.y) * k2 };
    // Faint dashed line shows where the command is aimed.
    return (
      <g key={i} opacity={fadeOut * live}>
        <path d={`M${from.x} ${from.y} L${toShield.x} ${toShield.y} M${out.x} ${out.y} L${tgt.x} ${tgt.y}`} stroke={col} strokeOpacity={0.25} strokeWidth={4} strokeDasharray="14 14" fill="none" />
        <line x1={from.x} y1={from.y} x2={seg1.x} y2={seg1.y} stroke={col} strokeWidth={9} strokeLinecap="round" />
        {k2 > 0 && <line x1={out.x} y1={out.y} x2={seg2.x} y2={seg2.y} stroke={col} strokeWidth={9} strokeLinecap="round" />}
        {b.blocked && t >= p.verdict && (
          <circle cx={toShield.x} cy={toShield.y} r={interpolate(t - p.verdict, [0, 0.35], [10, 90], clamp)} fill="none" stroke={RED} strokeWidth={6}
            opacity={interpolate(t - p.verdict, [0, 0.35], [0.9, 0], clamp)} />
        )}
      </g>
    );
  };

  // Folders: .aws glows red when protected; build dissolves when the allowed delete lands.
  const awsGlow = t >= pA.verdict ? interpolate(t - pA.verdict, [0, 0.2, 1.6], [0, 1, 0], clamp) : 0;
  const gone = interpolate(t, [pB.hit, pB.hit + POOF], [0, 1], { ...clamp, easing: Easing.in(Easing.cubic) });
  const back = reset;
  const buildScale = (1 + 0.12 * Math.sin(Math.min(1, gone) * Math.PI)) * (1 - gone) * (1 - back) + back;
  const buildOpacity = Math.max(1 - gone, back);
  const particles = t >= pB.hit && t < pB.hit + 1.2 && reset === 0
    ? [...Array(10).keys()].map((i) => {
        const ang = (i / 10) * Math.PI * 2 + 0.3;
        const d = interpolate(t - pB.hit, [0, 1.2], [20, 190], { ...clamp, easing: Easing.out(Easing.cubic) });
        const o = interpolate(t - pB.hit, [0, 1.2], [1, 0], clamp);
        return <rect key={i} x={BUILD.x + Math.cos(ang) * d - 8} y={BUILD.y + Math.sin(ang) * d - 8} width={16} height={16} rx={3} fill={GREEN} opacity={o} />;
      })
    : null;

  return (
    <AbsoluteFill style={{ background: BG }}>
      {/* Terminal */}
      <div style={{ position: "absolute", left: TERM.x + termShake, top: TERM.y, width: TERM.w, height: TERM.h, background: "#12141a",
        borderRadius: 26, border: "2px solid #23262e", boxShadow: "0 40px 100px rgba(0,0,0,.5)", overflow: "hidden",
        fontFamily: MONO, fontSize: 60 }}>
        <div style={{ height: 62, background: "#191c23", display: "flex", gap: 14, alignItems: "center", paddingLeft: 26 }}>
          {["#3a3e47", "#3a3e47", "#3a3e47"].map((c, i) => <span key={i} style={{ width: 18, height: 18, borderRadius: 9, background: c }} />)}
        </div>
        {line(A, 0)}
        {line(B, 1)}
        {idleCaret && (
          <div style={{ position: "absolute", left: 50, top: LINE_Y[0] - TERM.y - 40, display: "flex", alignItems: "center", gap: 22 }}>
            <span style={{ color: MUTED }}>$</span>
            {Math.floor(t * 2.5) % 2 === 0 && <span style={{ width: 30, height: 58, background: INK, display: "inline-block" }} />}
          </div>
        )}
      </div>

      <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
        {beam(A, 0)}
        {beam(B, 1)}
        <Shield color={color} scan={scanning ? (t - pa.reach) / 0.5 : 0} pulse={pulse * shieldFade} shake={shake} />
        <Folder x={AWS.x} y={AWS.y} icon="key" label="~/.aws" scale={1} opacity={1} glow={awsGlow} glowColor={RED} />
        <Folder x={BUILD.x} y={BUILD.y} icon="box" label="./build" scale={buildScale} opacity={buildOpacity} glow={0} glowColor={GREEN} />
        {particles}
      </svg>
    </AbsoluteFill>
  );
};

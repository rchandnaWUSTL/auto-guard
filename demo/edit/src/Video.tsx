import React from "react";
import {
  AbsoluteFill,
  Audio,
  Easing,
  Freeze,
  interpolate,
  OffthreadVideo,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

export type Step = {
  action: "block" | "escalate" | "allow";
  start: number;
  gate: number;
  stamp: number;
  rationale: number | null;
  end: number;
  latency_ms: number;
  cost: number;
};

export type Timeline = { scene: string; fps: number; width: number; height: number; durationMs: number; steps: Step[] };

export type CaptionSet = { open: string; stamp: string; cost?: string; allow?: string; llm?: string; end: string[] };

export type VideoProps = {
  src: string;
  timeline: Timeline;
  captions: CaptionSet;
  square: boolean;
  endCardMs: number;
  music: string | null;
};

const FONT = '-apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif';
const LOOP_FRAMES = 18; // last frames cross-fade into frame 0 so the clip loops cleanly
const STAMP_CENTER = { x: 1432, y: 695 }; // where the console draws the stamp (1920x1080 capture)
// Square: shrink the capture to open a caption band on top, and pan between terminal and panel.
const SQ = { scale: 0.88, top: 130, panelX: 721 };

export const fmtLatency = (ms: number) => `${Math.round(ms)}ms`;
export const fmtCost = (c: number) => (c < 0.001 ? `$${c.toFixed(6)}` : `$${c.toFixed(4)}`);

const fill = (text: string, step: Step) =>
  text.replace("{latency}", fmtLatency(step.latency_ms)).replace("{cost}", fmtCost(step.cost));

const Caption: React.FC<{ text: string; from: number; to: number; square: boolean; big?: boolean; still?: boolean; opacity?: number }> = ({ text, from, to, square, big, still, opacity }) => {
  const frame = useCurrentFrame();
  if (frame < from || frame >= to) return null;
  const pop = still ? 1 : interpolate(frame - from, [0, 6], [0.92, 1], { extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) });
  const fade = opacity ?? (still ? 1 : interpolate(frame, [from, from + 4, to - 5, to], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }));
  const style: React.CSSProperties = square
    ? { top: 16, left: 20, right: 20, justifyContent: "center" }
    : { bottom: 70, left: 56, width: 906, justifyContent: "center" };
  return (
    <div style={{ position: "absolute", display: "flex", ...style }}>
      <div
        style={{
          fontFamily: FONT,
          fontWeight: 800,
          fontSize: big ? 76 : square ? 44 : 64,
          lineHeight: 1.1,
          color: "#fff",
          background: "rgba(8,9,12,0.86)",
          border: "2px solid rgba(255,255,255,0.14)",
          padding: square ? "16px 26px" : "20px 34px",
          whiteSpace: square ? "nowrap" : undefined,
          borderRadius: 22,
          textAlign: "center",
          letterSpacing: "-0.01em",
          transform: `scale(${pop})`,
          opacity: fade,
          boxShadow: "0 20px 60px rgba(0,0,0,.5)",
        }}
      >
        {text}
      </div>
    </div>
  );
};

export const AutoGuardVideo: React.FC<VideoProps> = ({ src, timeline, captions, square, endCardMs, music }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, width } = useVideoConfig();
  const f = (ms: number) => Math.round((ms / 1000) * fps);
  const [first, second] = timeline.steps;
  const captureFrames = f(timeline.durationMs);
  const endStart = durationInFrames - f(endCardMs);

  // Zoom-punch on the first stamp: quick spring in, then ease back out.
  const stampF = f(first.stamp);
  const punchIn = spring({ frame: frame - stampF, fps, config: { damping: 11, stiffness: 260, mass: 0.6 } });
  const punchOut = interpolate(frame, [stampF + f(1100), stampF + f(1600)], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.inOut(Easing.cubic),
  });
  const zoom = 1 + 0.16 * punchIn * (1 - punchOut);

  // Square: pan between the terminal (left) and the Auto-Guard panel (right).
  let panX = 0;
  if (square) {
    const PAN = f(350);
    const moves: [number, number][] = []; // [frame the pan starts, target x]
    timeline.steps.forEach((s, i) => {
      if (i > 0) moves.push([f(s.start) - PAN, 0]);
      moves.push([f(s.gate), SQ.panelX]);
      if (s.rationale != null) moves.push([f(s.rationale), 0]);
    });
    const xs: number[] = [0];
    const ys: number[] = [0];
    for (const [t, x] of moves) {
      xs.push(Math.max(t, xs[xs.length - 1] + 1));
      ys.push(ys[ys.length - 1]);
      xs.push(xs[xs.length - 1] + PAN);
      ys.push(x);
    }
    panX = interpolate(frame, xs, ys, { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.inOut(Easing.cubic) });
  }

  const scale = square ? SQ.scale : 1;
  const top = square ? SQ.top : 0;
  const originX = STAMP_CENTER.x * scale - panX;
  const originY = STAMP_CENTER.y * scale + top;
  const video = (
    <OffthreadVideo src={staticFile(src)} muted style={{ width: 1920, height: 1080 }} />
  );
  const place = (x: number, child: React.ReactNode) => (
    <div style={{ position: "absolute", left: -x, top, width: 1920, height: 1080, transform: `scale(${scale})`, transformOrigin: "0 0" }}>
      {child}
    </div>
  );

  // End card: dim the last capture frame and put the tagline over it.
  const endT = interpolate(frame, [endStart, endStart + 10], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const loopT = interpolate(frame, [durationInFrames - LOOP_FRAMES, durationInFrames - 1], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.inOut(Easing.quad),
  });

  const stampEnd = f(first.stamp) + f(2000);
  const captionTo = second ? f(second.start) : endStart;

  return (
    <AbsoluteFill style={{ background: "#0b0c0f", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${zoom})`, transformOrigin: `${originX}px ${originY}px` }}>
        {place(panX, frame < captureFrames ? video : <Freeze frame={captureFrames - 1}>{video}</Freeze>)}
      </AbsoluteFill>

      <Caption text={captions.open} from={0} to={f(first.stamp)} square={square} still />
      <Caption text={fill(captions.stamp, first)} from={f(first.stamp)} to={first.rationale != null ? f(first.rationale) : stampEnd} square={square} />
      {captions.cost && <Caption text={fill(captions.cost, first)} from={stampEnd} to={captionTo} square={square} />}
      {captions.llm && first.rationale != null && (
        <Caption text={captions.llm} from={f(first.rationale)} to={endStart} square={square} />
      )}
      {captions.allow && second && <Caption text={captions.allow} from={f(second.gate)} to={endStart} square={square} />}

      {/* End card */}
      <AbsoluteFill style={{ background: `rgba(8,9,12,${0.93 * endT})`, justifyContent: "center", alignItems: "center", opacity: endT > 0 ? 1 : 0 }}>
        <div style={{ fontFamily: FONT, color: "#fff", textAlign: "center", opacity: endT, transform: `translateY(${(1 - endT) * 24}px)` }}>
          <div style={{ fontSize: square ? 64 : 84, fontWeight: 800, letterSpacing: "-0.02em", lineHeight: 1.1, maxWidth: width - 120 }}>{captions.end[0]}</div>
          <div style={{ fontSize: square ? 44 : 56, fontWeight: 600, color: "#3ddc84", marginTop: 22 }}>{captions.end[1]}</div>
          <div style={{ fontSize: square ? 24 : 28, color: "#8b909c", marginTop: 34, fontFamily: "ui-monospace, Menlo, monospace" }}>
            Auto-Guard · built on TypeSafe Jev
          </div>
        </div>
      </AbsoluteFill>

      {/* Loop: fade to the opening frame so the last frame flows into the first */}
      <AbsoluteFill style={{ opacity: loopT, background: "#0b0c0f" }}>
        {place(0, <Freeze frame={0}>{video}</Freeze>)}
      </AbsoluteFill>
      {loopT > 0 && <Caption text={captions.open} from={0} to={durationInFrames + 1} square={square} still opacity={loopT} />}

      {music && <Audio src={staticFile(music)} volume={0.12} />}
    </AbsoluteFill>
  );
};

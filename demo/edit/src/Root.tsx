import React from "react";
import { Composition } from "remotion";
import { AutoGuardVideo, type Timeline, type VideoProps } from "./Video";
import { HeroVideo, heroSeconds } from "./Hero";
import { HeroTech, techSeconds, type TechProps } from "./HeroTech";
import blockScene from "../../scenes/block.json";
import metrics from "../../metrics.json";
import blockTimeline from "../../raw/timeline-block.json";
import escalateTimeline from "../../raw/timeline-escalate.json";
import captions from "../captions.json";

const FPS = 60;
const END_CARD_MS = 2200;
const music = (process.env.REMOTION_MUSIC as string | undefined) || null;

const sonnet = metrics.llm_baselines.find((b) => b.model === "anthropic/claude-sonnet-5")!;
const tech: TechProps = {
  steps: blockScene.steps as TechProps["steps"],
  llm: { name: "Claude Sonnet 5", latency_ms: sonnet.latency_p50_ms, cost: sonnet.cost_per_gate_usd },
};

const frames = (t: Timeline, endMs: number) => Math.round(((t.durationMs + endMs) / 1000) * FPS);

const block: VideoProps = {
  src: "capture.webm",
  timeline: blockTimeline as Timeline,
  captions: captions.block,
  square: false,
  endCardMs: END_CARD_MS,
  music,
};
const escalate: VideoProps = {
  src: "escalate.webm",
  timeline: escalateTimeline as Timeline,
  captions: captions.escalate,
  square: false,
  endCardMs: 2000,
  music,
};

export const Root: React.FC = () => (
  <>
    <Composition id="Hero" component={HeroVideo} width={1920} height={1080} fps={FPS}
      durationInFrames={Math.round(heroSeconds(blockTimeline as Timeline) * FPS)} defaultProps={{ timeline: blockTimeline as Timeline }} />
    <Composition id="HeroTech" component={HeroTech} width={1920} height={1080} fps={FPS}
      durationInFrames={Math.round(techSeconds(tech) * FPS)} defaultProps={tech} />
    <Composition id="Landscape" component={AutoGuardVideo} width={1920} height={1080} fps={FPS}
      durationInFrames={frames(block.timeline, block.endCardMs)} defaultProps={block} />
    <Composition id="Square" component={AutoGuardVideo} width={1080} height={1080} fps={FPS}
      durationInFrames={frames(block.timeline, block.endCardMs)} defaultProps={{ ...block, square: true }} />
    <Composition id="Escalate" component={AutoGuardVideo} width={1920} height={1080} fps={FPS}
      durationInFrames={frames(escalate.timeline, escalate.endCardMs)} defaultProps={escalate} />
  </>
);

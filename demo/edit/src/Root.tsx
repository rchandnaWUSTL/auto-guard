import React from "react";
import { Composition } from "remotion";
import { AutoGuardVideo, type Timeline, type VideoProps } from "./Video";
import blockTimeline from "../../raw/timeline-block.json";
import escalateTimeline from "../../raw/timeline-escalate.json";
import captions from "../captions.json";

const FPS = 60;
const END_CARD_MS = 2200;
const music = (process.env.REMOTION_MUSIC as string | undefined) || null;

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
    <Composition id="Landscape" component={AutoGuardVideo} width={1920} height={1080} fps={FPS}
      durationInFrames={frames(block.timeline, block.endCardMs)} defaultProps={block} />
    <Composition id="Square" component={AutoGuardVideo} width={1080} height={1080} fps={FPS}
      durationInFrames={frames(block.timeline, block.endCardMs)} defaultProps={{ ...block, square: true }} />
    <Composition id="Escalate" component={AutoGuardVideo} width={1920} height={1080} fps={FPS}
      durationInFrames={frames(escalate.timeline, escalate.endCardMs)} defaultProps={escalate} />
  </>
);

// Renders the final MP4s from demo/raw/ (produced by record.mjs). Usage: node edit/render.mjs
// Optional background music: MUSIC=path/to/track.mp3 node edit/render.mjs (copied into raw/ as music.*)
import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const RAW = join(HERE, "..", "raw");
const OUT = join(HERE, "..", "out");
mkdirSync(OUT, { recursive: true });

let music = null;
if (process.env.MUSIC) {
  music = "music" + extname(process.env.MUSIC);
  copyFileSync(resolve(process.env.MUSIC), join(RAW, music));
}

const serveUrl = await bundle({
  entryPoint: join(HERE, "src", "index.ts"),
  publicDir: RAW,
  envVariables: music ? { REMOTION_MUSIC: music } : {},
});

const jobs = [
  ["Landscape", "auto-guard-landscape-1920x1080.mp4"],
  ["Square", "auto-guard-square-1080x1080.mp4"],
  ["Escalate", "auto-guard-escalate.mp4"],
];
const only = process.argv.slice(2);
for (const [id, file] of jobs) {
  if (only.length && !only.includes(id)) continue;
  const composition = await selectComposition({ serveUrl, id });
  const outputLocation = join(OUT, file);
  let last = -1;
  await renderMedia({
    composition, serveUrl, outputLocation,
    codec: "h264", crf: 18, pixelFormat: "yuv420p",
    muted: !music,
    onProgress: ({ progress }) => {
      const p = Math.floor(progress * 10);
      if (p !== last) { last = p; process.stdout.write(`\r${id}: ${p * 10}%`); }
    },
  });
  console.log(`\r${id}: wrote ${outputLocation} (${(composition.durationInFrames / composition.fps).toFixed(2)}s)`);
}

// Deterministic capture of the Auto-Guard console scenes.
// Steps the page's timeline frame by frame (window.__seek) instead of screen-recording,
// so every run produces identical frames at a true 60fps.
// Usage: node record.mjs [block|escalate ...]   (default: both)
import { spawn, spawnSync } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..");
const RAW = join(HERE, "raw");
const FPS = 60;
const WIDTH = 1920;
const HEIGHT = 1080;
const TAIL_MS = 400; // hold the final frame a little before the end card
const PORT = 8799;
const OUTPUTS = { block: "capture.webm", escalate: "escalate.webm" };

const scenes = process.argv.slice(2).length ? process.argv.slice(2) : Object.keys(OUTPUTS);
for (const s of scenes) {
  if (!existsSync(join(HERE, "scenes", s + ".json"))) {
    console.error(`Missing demo/scenes/${s}.json. Run: python3 -m autoguard demo ${s} --record`);
    process.exit(1);
  }
}

const server = spawn("python3", ["-m", "autoguard", "console", "--port", String(PORT)], {
  cwd: ROOT,
  stdio: "ignore",
});
const stop = () => server.kill();
process.on("exit", stop);

async function waitForServer() {
  for (let i = 0; i < 50; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/scenes/block.json`);
      if (r.ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("console server did not start");
}

async function capture(browser, scene) {
  const page = await browser.newPage({ viewport: { width: WIDTH, height: HEIGHT }, deviceScaleFactor: 1 });
  await page.goto(`http://127.0.0.1:${PORT}/?scene=${scene}&capture=1&theme=dark`);
  await page.waitForFunction(() => window.__ready === true);
  const timeline = await page.evaluate(() => window.__timeline);
  const durationMs = timeline.duration + TAIL_MS;
  const frames = Math.ceil((durationMs / 1000) * FPS);

  const dir = join(RAW, "frames-" + scene);
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  // Seek, then wait two animation frames so layout and paint have settled before the screenshot.
  const seek = (t) => page.evaluate((t) => new Promise((done) => {
    window.__seek(t);
    requestAnimationFrame(() => requestAnimationFrame(done));
  }), t);
  for (const t of [0, timeline.duration / 2, 0]) await seek(t); // warm up fonts and compositor
  for (let i = 0; i < frames; i++) {
    await seek((i * 1000) / FPS);
    await page.screenshot({ path: join(dir, String(i).padStart(5, "0") + ".png") });
    if (i % 120 === 0) process.stdout.write(`\r${scene}: frame ${i}/${frames}`);
  }
  process.stdout.write(`\r${scene}: ${frames} frames captured\n`);
  await page.close();

  const out = join(RAW, OUTPUTS[scene]);
  const enc = spawnSync("npx", [
    "remotion", "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
    "-framerate", String(FPS), "-i", join(dir, "%05d.png"),
    "-c:v", "libvpx-vp9", "-lossless", "1", "-pix_fmt", "yuv420p", "-row-mt", "0", "-threads", "1",
    // No encoder tags or write dates, so identical frames give a byte-identical file.
    "-fflags", "+bitexact", "-flags:v", "+bitexact", "-map_metadata", "-1",
    out,
  ], { cwd: HERE, stdio: "inherit" });
  if (enc.status !== 0) throw new Error("ffmpeg encode failed");
  rmSync(dir, { recursive: true, force: true });

  const meta = { scene, fps: FPS, width: WIDTH, height: HEIGHT, durationMs, frames, ...timeline };
  writeFileSync(join(RAW, `timeline-${scene}.json`), JSON.stringify(meta, null, 2) + "\n");
  console.log(`wrote ${out} (${(durationMs / 1000).toFixed(2)}s)`);
}

await waitForServer();
mkdirSync(RAW, { recursive: true });
const browser = await chromium.launch();
try {
  for (const s of scenes) await capture(browser, s);
} finally {
  await browser.close();
  stop();
}

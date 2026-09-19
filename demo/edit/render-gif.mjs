// Renders the technical video as a GIF for the README (GitHub won't play repo MP4s inline).
// Usage: node edit/render-gif.mjs
import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const serveUrl = await bundle({ entryPoint: join(HERE, "src", "index.ts"), publicDir: join(HERE, "..", "raw") });
const composition = await selectComposition({ serveUrl, id: "HeroTech" });
const outputLocation = join(HERE, "..", "out", "auto-guard-under-the-hood.gif");
await renderMedia({
  composition, serveUrl, outputLocation,
  codec: "gif",
  everyNthFrame: 4, // 60fps -> 15fps
  scale: 0.5,       // 1920x1080 -> 960x540
  numberOfGifLoops: null, // loop forever
});
console.log("wrote", outputLocation);

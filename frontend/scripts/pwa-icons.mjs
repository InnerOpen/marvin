// Generates the installable app's icons into public/icons/ — run `npm run icons` after changing the mark or
// its colours, and commit the output (the build doesn't regenerate them). The mark is drawn here as SVG (an
// "M" stroke, no font, so every machine renders the same pixels) and rasterised with sharp (Astro's own
// image dependency).
//
// Two sets: the production one (orange) and the one a non-production instance installs as (ENVIRONMENT_LABEL
// set — dark with an amber mark), so an installed "Marvin DEV" never looks like the real one. Each set has a
// regular icon (rounded, transparent corners), a maskable one (full bleed, mark inside the 80% safe zone) and
// an Apple touch icon (full bleed; iOS rounds it). badge-72.png is the monochrome status-bar badge Android
// shows for a notification.
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";

const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "public", "icons");

// Design tokens (src/styles/global.css): --accent #ea580c, --ink #0c0a09, --bg #fafaf9, --gold #d97706.
const SETS = {
  "": { background: "#ea580c", mark: "#fafaf9" },
  "-dev": { background: "#0c0a09", mark: "#f59e0b" },
};

const M = "M136 368V152l120 136 120-136v216";

function svg({ background, mark }, { rounded = false, scale = 1, transparent = false } = {}) {
  const offset = (512 - 512 * scale) / 2;
  const bg = transparent ? "" : `<rect width="512" height="512"${rounded ? ' rx="112"' : ""} fill="${background}"/>`;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">${bg}<path d="${M}" transform="translate(${offset} ${offset}) scale(${scale})" fill="none" stroke="${mark}" stroke-width="56" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}

async function png(source, size, file, { opaque = false } = {}) {
  const image = sharp(Buffer.from(source)).resize(size, size);
  await (opaque ? image.removeAlpha() : image).png({ compressionLevel: 9 }).toFile(join(OUT, file));
}

mkdirSync(OUT, { recursive: true });
for (const [suffix, colors] of Object.entries(SETS)) {
  const regular = svg(colors, { rounded: true });
  writeFileSync(join(OUT, `marvin${suffix}.svg`), `${regular}\n`);
  await png(regular, 192, `icon${suffix}-192.png`);
  await png(regular, 512, `icon${suffix}-512.png`);
  const maskable = svg(colors, { scale: 0.8 });
  await png(maskable, 192, `maskable${suffix}-192.png`, { opaque: true });
  await png(maskable, 512, `maskable${suffix}-512.png`, { opaque: true });
  await png(svg(colors, { scale: 0.86 }), 180, `apple-touch-icon${suffix}.png`, { opaque: true });
}
await png(svg({ background: "none", mark: "#ffffff" }, { transparent: true, scale: 1.12 }), 72, "badge-72.png");
console.info(`Icons written to ${OUT}`);

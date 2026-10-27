// Rebuild Windows ICO from the upstream SVG with existing system Chrome.
// Uses cached playwright-core, like ui_check.mjs; installs nothing.
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const cache = process.platform === "win32"
  ? join(process.env.LOCALAPPDATA, "npm-cache", "_npx") : join(homedir(), ".npm", "_npx");
const found = existsSync(cache) && readdirSync(cache)
  .map(d => join(cache, d, "node_modules", "playwright-core", "index.mjs")).find(existsSync);
if (!found) throw new Error("No cached playwright-core; icon build installs nothing");
const { chromium } = await import(pathToFileURL(found).href);
const executablePath = process.env.MA4_CHROME || (process.platform === "win32"
  ? "C:/Program Files/Google/Chrome/Application/chrome.exe" : "/usr/bin/google-chrome");
const browser = await chromium.launch({ executablePath, headless: true });
const sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256];
let images;
try {
  const page = await browser.newPage();
  images = await page.evaluate(async ({ svg, sizes }) => {
    const source = new Image();
    source.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
    await source.decode();
    return sizes.map(size => {
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = size;
      canvas.getContext("2d").drawImage(source, 0, 0, size, size);
      return canvas.toDataURL("image/png").split(",")[1];
    });
  }, { svg: readFileSync(join(root, "deploy", "ma4-icon.svg"), "utf8"), sizes });
} finally {
  await browser.close();
}
// Windows Vista+ accepts PNG frames in ICO, including alpha and all DPI sizes.
const frames = images.map(image => Buffer.from(image, "base64"));
const directory = Buffer.alloc(6 + 16 * frames.length);
directory.writeUInt16LE(1, 2);
directory.writeUInt16LE(frames.length, 4);
let offset = directory.length;
frames.forEach((frame, index) => {
  const pos = 6 + 16 * index;
  directory[pos] = directory[pos + 1] = sizes[index] % 256;
  directory.writeUInt16LE(1, pos + 4);
  directory.writeUInt16LE(32, pos + 6);
  directory.writeUInt32LE(frame.length, pos + 8);
  directory.writeUInt32LE(offset, pos + 12);
  offset += frame.length;
});
const output = join(root, "deploy", "ma4-icon.ico");
writeFileSync(output, Buffer.concat([directory, ...frames]));
console.log(JSON.stringify({ output, sizes, bytes: offset }));

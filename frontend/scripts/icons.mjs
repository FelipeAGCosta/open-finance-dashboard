// Gera os PNGs do PWA a partir dos SVGs de public/icons (Playwright).
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const dir = fileURLToPath(new URL("../public/icons/", import.meta.url));
const jobs = [
  ["icon.svg", "icon-192.png", 192],
  ["icon.svg", "icon-512.png", 512],
  ["icon-maskable.svg", "icon-maskable-512.png", 512],
];
const browser = await chromium.launch(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {});
const page = await browser.newPage();
for (const [source, target, size] of jobs) {
  const svg = await readFile(dir + source, "utf8");
  await page.setViewportSize({ width: size, height: size });
  await page.setContent(`<html><body style="margin:0;background:transparent">${svg.replace("<svg ", `<svg width="${size}" height="${size}" `)}</body></html>`);
  await page.screenshot({ path: dir + target, omitBackground: true, clip: { x: 0, y: 0, width: size, height: size } });
  console.log(`ícone: ${target}`);
}
await browser.close();

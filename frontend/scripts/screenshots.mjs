// Screenshots do modo demonstração para o README (docs/images).
// Uso: node scripts/screenshots.mjs [url-base] [pasta-de-saída]
// Recusa servidores que não estejam em modo demo: só dados sintéticos viram imagem.
import { mkdir } from "node:fs/promises";
import { chromium } from "playwright";

const base = process.argv[2] ?? "http://127.0.0.1:8765";
const out = process.argv[3] ?? "../docs/images";

const meta = await (await fetch(`${base}/api/meta`)).json();
if (!meta.demo) {
  console.error("Recusado: o servidor não está em modo demonstração (findash demo).");
  process.exit(1);
}
await mkdir(out, { recursive: true });

const screens = ["visao-geral", "gastos", "investimentos", "plano", "fixos"];
const themes = { dark: "escuro", light: "claro" };
const browser = await chromium.launch(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {});
const errors = [];

for (const [theme, label] of Object.entries(themes)) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, reducedMotion: "reduce" });
  await context.addInitScript((value) => {
    try {
      localStorage.setItem("findash:theme", value);
    } catch {
      // about:blank não tem localStorage
    }
  }, theme);
  const page = await context.newPage();
  page.on("pageerror", (err) => errors.push(`${theme}: ${err.message}`));
  for (const route of screens) {
    await page.goto("about:blank"); // força um carregamento novo: mudar só o hash não recarrega a página
    await page.goto(`${base}/#/${route}`);
    await page.waitForLoadState("networkidle");
    await page.waitForFunction(() => !document.querySelector('[aria-busy="true"], .skeleton'), null, { timeout: 30000 });
    await page.waitForTimeout(600);
    const file = `${out}/${route}-${label}.png`;
    await page.screenshot({ path: file });
    console.log(file);
  }
  await context.close();
}
await browser.close();

if (errors.length) {
  console.error(errors.join("\n"));
  process.exit(1);
}

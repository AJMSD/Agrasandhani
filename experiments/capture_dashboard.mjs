import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) {
      continue;
    }
    parsed[token.slice(2)] = argv[index + 1];
    index += 1;
  }
  return parsed;
}

const args = parseArgs(process.argv.slice(2));
const url = args.url;
const outputDir = args["output-dir"];
const captureMs = Number(args["capture-ms"] || 30000);

if (!url || !outputDir) {
  throw new Error("Usage: node experiments/capture_dashboard.mjs --url <url> --output-dir <dir> [--capture-ms <ms>]");
}

await fs.mkdir(outputDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();

try {
  await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
  await page.waitForFunction(() => window.agrasandhaniMeasurements !== undefined, null, { timeout: 10000 });
  await page.waitForFunction(() => {
    const status = document.getElementById("connection-status");
    return status && !status.textContent.includes("Connecting");
  }, null, { timeout: 15000 });
  await page.waitForTimeout(captureMs);

  const payload = await page.evaluate(() => ({
    csv: window.agrasandhaniMeasurements.exportCsv(),
    summary: window.agrasandhaniMeasurements.summary,
    thresholdMs: window.agrasandhaniMeasurements.thresholdMs,
  }));

  await fs.writeFile(path.join(outputDir, "dashboard_measurements.csv"), payload.csv, "utf-8");
  await fs.writeFile(path.join(outputDir, "dashboard_summary.json"), JSON.stringify(payload, null, 2), "utf-8");
  await page.screenshot({ path: path.join(outputDir, "dashboard.png"), fullPage: true });
} finally {
  await browser.close();
}

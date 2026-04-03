import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) {
      continue;
    }
    if (!token.startsWith("--")) {
      continue;
    }
    const key = token.slice(2);
    const next = argv[index + 1];
    if (!next || next.startsWith("--")) {
      parsed[key] = true;
      continue;
    }
    parsed[key] = next;
    index += 1;
  }
  return parsed;
}

const args = parseArgs(process.argv.slice(2));
const url = args.url;
const outputDir = args["output-dir"];
const captureMs = Number(args["capture-ms"] || 30000);
const checkOnly = Object.prototype.hasOwnProperty.call(args, "check-only");

if (!checkOnly && (!url || !outputDir)) {
  throw new Error("Usage: node experiments/capture_dashboard.mjs --url <url> --output-dir <dir> [--capture-ms <ms>] [--check-only]");
}

async function loadPlaywright() {
  const require = createRequire(import.meta.url);
  try {
    require.resolve("playwright");
  } catch {
    throw new Error(
      "Playwright package is not installed. Run `npm install` and `npx playwright install chromium`.",
    );
  }

  const playwright = await import("playwright");
  return playwright.chromium;
}

async function verifyBrowserAvailable() {
  const chromium = await loadPlaywright();
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
  } catch (error) {
    const message = String(error?.message || error);
    if (message.includes("Executable doesn't exist")) {
      throw new Error(
        "Playwright Chromium browser is not installed. Run `npx playwright install chromium`.",
      );
    }
    throw error;
  } finally {
    if (browser) {
      await browser.close();
    }
  }
}

try {
  await verifyBrowserAvailable();

  if (checkOnly) {
    console.log("Playwright and Chromium are available.");
    process.exit(0);
  }

  await fs.mkdir(outputDir, { recursive: true });

  const chromium = await loadPlaywright();
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
} catch (error) {
  console.error(String(error?.message || error));
  process.exit(1);
}

import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";
import fs from "node:fs/promises";
import os from "node:os";
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const python = process.env.TEXT_PACK_PYTHON || "python";
const port = Number(process.env.TEXT_PACK_TEST_PORT || 8766);
const server = spawn(python, ["-X", "utf8", "main.py", "serve", "--port", String(port)], { cwd: root, stdio: "ignore", windowsHide: true });
const screenshots = path.join(root, "docs", "screenshots");
await fs.mkdir(screenshots, { recursive: true });
const temp = await fs.mkdtemp(path.join(os.tmpdir(), "textpack-test-"));
let browser;
const checks = [];
const check = (name, condition) => { assert.ok(condition, name); checks.push(name); };
try {
  let ready = false;
  for (let i = 0; i < 60; i++) {
    try { ready = (await fetch(`http://127.0.0.1:${port}/api/health`)).ok; } catch {}
    if (ready) break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert.ok(ready, "Local server did not start");
  browser = await chromium.launch({ headless: true, ...(process.env.TEXT_PACK_BROWSER ? { executablePath: process.env.TEXT_PACK_BROWSER } : {}) });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 1 });
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${port}`);
  const completed = () => page.waitForFunction(() => document.querySelector("#status").textContent.startsWith("分析完成"));
  await completed();
  const expected = JSON.parse(await fs.readFile(path.join(root, "examples", "expected_analysis.json"), "utf8"));
  check("Sample: actual total archive size", (await page.locator("#archive-size").innerText()).replace(/[, B]/g, "") === String(expected.compression.archive_bytes));
  check("Sample: exact match count", (await page.locator("#match-count").innerText()) === `${expected.match_count} 处`);
  await page.screenshot({ path: path.join(screenshots, "workbench.png"), fullPage: true });

  await page.locator("#text").fill("🙂算法🙂算法");
  await page.locator("#pattern").fill("🙂算法");
  check("Editing invalidates download", await page.locator("#download").isDisabled());
  await page.locator("#analyze").click(); await completed();
  check("Unicode code-point offsets", JSON.stringify(await page.locator("#matches tr td:first-child").allTextContents()) === '["0","3"]');
  check("Unicode highlight", await page.locator("#preview mark").innerText() === "🙂算法🙂算法");
  await page.screenshot({ path: path.join(screenshots, "unicode-search.png"), fullPage: true });

  await page.locator("#text").fill("ababab"); await page.locator("#pattern").fill("abab");
  await page.locator("#analyze").click(); await completed();
  check("Overlapping matches", JSON.stringify(await page.locator("#matches tr td:first-child").allTextContents()) === '["0","2"]');

  const raw = Buffer.from("\ufeff第一行\r\n第二行🙂\r\n", "utf8");
  await page.locator("#text-file").setInputFiles({ name: "crlf-bom.txt", mimeType: "text/plain", buffer: raw });
  await completed();
  const downloadPromise = page.waitForEvent("download");
  await page.locator("#download").click();
  const download = await downloadPromise;
  const archive = path.join(temp, "actual.tpk");
  const restored = path.join(temp, "restored.txt");
  await download.saveAs(archive);
  const decoding = spawnSync(python, ["-X", "utf8", "main.py", "decompress", archive, restored], { cwd: root, encoding: "utf8", windowsHide: true });
  check("Browser download: CRLF/BOM bytes preserved", decoding.status === 0 && raw.equals(await fs.readFile(restored)));
  await page.locator("#archive-file").setInputFiles(archive);
  await completed();
  check("Archive restore flow", (await page.locator("#input-label").innerText()).includes("已还原"));

  await page.locator("#archive-file").setInputFiles({ name: "broken.tpk", mimeType: "application/octet-stream", buffer: Buffer.from("broken") });
  await page.waitForFunction(() => document.querySelector("#status").classList.contains("error"));
  check("Corrupt archive produces visible error", (await page.locator("#status").innerText()).includes("还原失败"));
  await page.screenshot({ path: path.join(screenshots, "corrupt-file.png"), fullPage: true });

  await page.locator("#text").fill('<img src=x onerror="window.injected=true">');
  await page.locator("#pattern").fill("img"); await page.locator("#analyze").click(); await completed();
  check("Input is rendered as text", await page.locator("#preview img").count() === 0 && (await page.locator("#preview").innerText()).includes("<img"));

  await page.locator("#clear").click(); await page.locator("#pattern").fill("");
  await page.locator("#analyze").click(); await completed();
  check("Empty input is supported", await page.locator("#saving").innerText() === "不适用");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator("#sample").click(); await completed();
  check("Mobile layout has no horizontal overflow", await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  await page.screenshot({ path: path.join(screenshots, "mobile.png"), fullPage: true });
  check("No unhandled browser exceptions", errors.length === 0);
  const report = { timestamp: new Date().toISOString(), browser: await browser.version(), passed: checks.length, checks, errors };
  await fs.writeFile(path.join(root, "docs", "browser-results.json"), JSON.stringify(report, null, 2) + "\n");
  console.log(JSON.stringify(report, null, 2));
} finally {
  if (browser) await browser.close();
  server.kill();
  // Only the exact temporary directory created by mkdtemp is removed.
  assert.ok(path.resolve(temp).startsWith(path.resolve(os.tmpdir()) + path.sep));
  await fs.rm(temp, { recursive: true, force: true });
}

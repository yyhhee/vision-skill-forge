import { chromium } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import crypto from "node:crypto";

const origin = process.env.VSF_TEST_BASE_URL ?? "http://127.0.0.1:6174";
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(origin)) {
  throw new Error("Capture origin must be an explicit local HTTP port");
}
const output = path.resolve(process.argv[2] ?? "qa/04/iteration-02");
try {
  await fs.access(output);
  throw new Error("Refusing to overwrite an existing capture directory");
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  ...(process.env.VSF_CHROMIUM_EXECUTABLE
    ? { executablePath: process.env.VSF_CHROMIUM_EXECUTABLE }
    : {}),
});
try {
  const context = await browser.newContext({
    viewport: { width: 1513, height: 1040 },
    deviceScaleFactor: 1,
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
    colorScheme: "light",
    reducedMotion: "reduce",
  });
  const network = [],
    consoleLogs = [],
    errors = [];
  await context.route("**/*", async (route) => {
    const url = route.request().url();
    if (new URL(url).origin !== origin) {
      network.push({ url, blocked: true });
      await route.abort();
    } else await route.continue();
  });
  await context.addInitScript(() => {
    Date.now = () => new Date("2026-10-17T10:26:00+08:00").getTime();
  });
  const page = await context.newPage();
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) =>
    consoleLogs.push({ type: message.type(), text: message.text() }),
  );
  page.on("response", (response) => {
    network.push({ url: response.url(), status: response.status() });
  });
  await page.goto(
    `${origin}/skills/regional-alert/editor?view=linked&fixture=04`,
    { waitUntil: "networkidle" },
  );
  await page.evaluate(() => document.fonts.ready);
  await page.waitForFunction(
    () =>
      [...document.images].every(
        (image) => image.complete && image.naturalWidth > 0,
      ) && document.querySelectorAll(".react-flow__node").length === 5,
  );
  await page.mouse.move(0, 1039);
  const environment = await page.evaluate(() => ({
    viewport: { width: innerWidth, height: innerHeight },
    dpr: devicePixelRatio,
    userAgent: navigator.userAgent,
    language: navigator.language,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    fontStatus: document.fonts.status,
    weights: [400, 500, 600, 700].map((weight) => ({
      weight,
      loaded: document.fonts.check(`${weight} 16px "Noto Sans SC"`),
    })),
    selectedRegion1: document
      .querySelector('[aria-label="选择区域1"]')
      ?.getAttribute("aria-pressed"),
    openInspectorCount: document.querySelectorAll(".inspector").length,
    geometry: [
      ...document.querySelectorAll(
        ".topbar,.sidebar,.instruction-bar,.scene-panel,.canvas-panel,.scene-media,.rule-flow,.app-footer,.detector-card,.branch-card,.final-card,.output-card",
      ),
    ].map((element) => {
      const rect = element.getBoundingClientRect();
      return {
        selector: element.className,
        x: rect.x,
        y: rect.y,
        width: rect.width,
        height: rect.height,
      };
    }),
  }));
  if (
    environment.dpr !== 1 ||
    environment.viewport.width !== 1513 ||
    environment.viewport.height !== 1040 ||
    environment.selectedRegion1 !== "true" ||
    environment.openInspectorCount !== 0
  )
    throw new Error("Capture environment/state mismatch");
  await page.screenshot({
    path: path.join(output, "implementation.png"),
    fullPage: false,
    animations: "disabled",
  });
  const fontNames = await fs.readdir("public/assets/fonts");
  const fonts = [];
  for (const file of fontNames)
    fonts.push({
      file,
      sha256: crypto
        .createHash("sha256")
        .update(await fs.readFile(path.join("public/assets/fonts", file)))
        .digest("hex"),
    });
  const report = {
    purpose: "real browser capture; not visual acceptance",
    browserVersion: browser.version(),
    os: { platform: os.platform(), release: os.release() },
    ...environment,
    fonts,
    errors,
    networkPolicy: `only ${origin}; fresh context; no login/profile`,
    url: page.url(),
  };
  await fs.writeFile(
    path.join(output, "environment.json"),
    JSON.stringify(report, null, 2),
  );
  await fs.writeFile(
    path.join(output, "console.json"),
    JSON.stringify(consoleLogs, null, 2),
  );
  await fs.writeFile(
    path.join(output, "network.json"),
    JSON.stringify(network, null, 2),
  );
  console.log(
    JSON.stringify(
      {
        output,
        viewport: environment.viewport,
        dpr: environment.dpr,
        browserVersion: report.browserVersion,
        errors,
      },
      null,
      2,
    ),
  );
} finally {
  await browser.close();
}

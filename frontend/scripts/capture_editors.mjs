import { chromium } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
const root = path.resolve(process.argv[2] ?? "qa/editor-flow/iteration-01");
try {
  await fs.access(root);
  throw new Error("Refusing to overwrite previous evidence");
} catch (e) {
  if (e.code !== "ENOENT") throw e;
}
await fs.mkdir(root, { recursive: true });
const cases = [
  {
    id: "03",
    name: "03-scene-annotation",
    w: 1513,
    h: 1039,
    query: "view=scene",
    skill: "regional-alert",
  },
  {
    id: "04",
    name: "04-linked-workbench",
    w: 1513,
    h: 1040,
    query: "view=linked",
    skill: "regional-alert",
  },
  {
    id: "05",
    name: "05-condition-evidence-editor",
    w: 1513,
    h: 1039,
    query: "view=linked&drawer=condition",
    skill: "regional-alert",
  },
  {
    id: "06",
    name: "06-time-configuration",
    w: 1513,
    h: 1040,
    query: "view=linked&drawer=time",
    skill: "regional-alert",
  },
  {
    id: "07",
    name: "07-orchestration-groups",
    w: 1513,
    h: 1040,
    query: "view=orchestration&drawer=group",
    skill: "sequence-demo",
  },
  {
    id: "08",
    name: "08-outputs-and-trigger",
    w: 1512,
    h: 1040,
    query: "view=outputs&drawer=output",
    skill: "regional-alert",
  },
  {
    id: "15",
    name: "15-validation-and-recovery",
    w: 1513,
    h: 1040,
    query: "view=linked&drawer=issues",
    skill: "regional-alert",
  },
];
const browser = await chromium.launch({
  headless: true,
  ...(process.env.VSF_CHROMIUM_EXECUTABLE
    ? { executablePath: process.env.VSF_CHROMIUM_EXECUTABLE }
    : {}),
});
try {
  for (const item of cases) {
    const dest = path.join(root, item.id);
    await fs.mkdir(dest);
    const context = await browser.newContext({
      viewport: { width: item.w, height: item.h },
      deviceScaleFactor: 1,
      locale: "zh-CN",
      timezoneId: "Asia/Shanghai",
      colorScheme: "light",
      reducedMotion: "reduce",
    });
    const errors = [],
      network = [];
    await context.route("**/*", async (route) => {
      const url = route.request().url();
      if (new URL(url).origin !== "http://127.0.0.1:6174") {
        network.push({ url, blocked: true });
        return route.abort();
      }
      return route.continue();
    });
    const page = await context.newPage();
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(
      `http://127.0.0.1:6174/skills/${item.skill}/editor?${item.query}&fixture=${item.id}`,
      { waitUntil: "networkidle" },
    );
    await page.evaluate(() => document.fonts.ready);
    await page.waitForFunction(() =>
      [...document.images].every((i) => i.complete && i.naturalWidth > 0),
    );
    if (["03", "04", "05", "06", "15"].includes(item.id))
      await page.getByTestId("scene-media").waitFor({ state: "visible" });
    if (item.id !== "03")
      await page.waitForFunction(
        () =>
          document.querySelectorAll(".react-flow__node").length >= 4 &&
          [...document.querySelectorAll(".react-flow__node")].every(
            (n) => getComputedStyle(n).visibility !== "hidden",
          ),
      );
    await page.evaluate(
      () =>
        new Promise((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(resolve)),
        ),
    );
    await page.mouse.move(0, item.h - 1);
    await page.evaluate(() => {
      if (document.activeElement instanceof HTMLElement)
        document.activeElement.blur();
    });
    await page.screenshot({
      path: path.join(dest, "implementation.png"),
      fullPage: false,
      animations: "disabled",
    });
    const environment = await page.evaluate(() => ({
      viewport: { width: innerWidth, height: innerHeight },
      dpr: devicePixelRatio,
      language: navigator.language,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      fontStatus: document.fonts.status,
      drawer: [...document.querySelectorAll(".inspector")].map((n) =>
        n.getAttribute("aria-label"),
      ),
      geometry: [
        ...document.querySelectorAll(
          ".scene-media,.scene-panel,.canvas-panel,.inspector,.scene-resources,.orchestration-flow",
        ),
      ].map((n) => {
        const b = n.getBoundingClientRect();
        return {
          selector: n.className,
          x: b.x,
          y: b.y,
          width: b.width,
          height: b.height,
        };
      }),
    }));
    const sha256 = crypto
      .createHash("sha256")
      .update(await fs.readFile(path.join(dest, "implementation.png")))
      .digest("hex");
    await fs.writeFile(
      path.join(dest, "environment.json"),
      JSON.stringify(
        {
          ...item,
          ...environment,
          browserVersion: browser.version(),
          url: page.url(),
          errors,
          network,
          sha256,
          purpose: "capture evidence, not automatic visual acceptance",
        },
        null,
        2,
      ),
    );
    console.log(
      `${item.id}: ${errors.length} page errors; ${item.w}x${item.h} DPR1`,
    );
    await context.close();
  }
} finally {
  await browser.close();
}

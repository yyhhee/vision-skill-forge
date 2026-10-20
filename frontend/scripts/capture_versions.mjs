import { chromium } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";

const root = path.resolve(process.argv[2] ?? "qa/versions/iteration-01");
try {
  await fs.access(root);
  throw new Error("Refusing to overwrite previous evidence");
} catch (e) {
  if (e.code !== "ENOENT") throw e;
}
await fs.mkdir(root, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  ...(process.env.VSF_CHROMIUM_EXECUTABLE
    ? { executablePath: process.env.VSF_CHROMIUM_EXECUTABLE }
    : {}),
});
try {
  for (const item of [
    { id: "12", width: 1513, height: 1040, route: "versions?fixture=12" },
    {
      id: "12-compact",
      width: 1366,
      height: 768,
      route: "versions?fixture=12",
    },
    { id: "12-narrow", width: 760, height: 900, route: "versions?fixture=12" },
    {
      id: "04",
      width: 1513,
      height: 1040,
      route: "editor?view=linked&fixture=04",
    },
  ]) {
    const dest = path.join(root, item.id);
    await fs.mkdir(dest);
    const context = await browser.newContext({
      viewport: { width: item.width, height: item.height },
      deviceScaleFactor: 1,
      locale: "zh-CN",
      timezoneId: "Asia/Shanghai",
      colorScheme: "light",
      reducedMotion: "reduce",
    });
    const errors = [],
      blocked = [];
    await context.route("**/*", (r) => {
      if (new URL(r.request().url()).origin === "http://127.0.0.1:6174")
        return r.continue();
      blocked.push(r.request().url());
      return r.abort();
    });
    const page = await context.newPage();
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(
      `http://127.0.0.1:6174/skills/regional-alert/${item.route}`,
      { waitUntil: "networkidle" },
    );
    if (item.id.startsWith("12"))
      await page
        .getByRole("heading", { name: "保存完整技能", exact: true })
        .waitFor();
    else await page.getByTestId("scene-media").waitFor();
    await page.evaluate(() => document.fonts.ready);
    await page.waitForFunction(() =>
      [...document.images].every((i) => i.complete && i.naturalWidth > 0),
    );
    if (item.id === "04")
      await page.waitForFunction(
        () => document.querySelectorAll(".react-flow__node").length >= 4,
      );
    if (item.id === "12") {
      if (
        (await page
          .locator(".versions-grid")
          .evaluate((n) => getComputedStyle(n).display)) !== "grid"
      )
        throw new Error("Missing version layout");
      if (
        !(await page
          .getByRole("button", { name: "保存为 V4", exact: true })
          .isVisible())
      )
        throw new Error("Missing save action");
    }
    await page.evaluate(
      () =>
        new Promise((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(resolve)),
        ),
    );
    await page.mouse.move(0, item.height - 1);
    await page.evaluate(
      () =>
        document.activeElement instanceof HTMLElement &&
        document.activeElement.blur(),
    );
    const shot = path.join(dest, "implementation.png");
    await page.screenshot({ path: shot, animations: "disabled" });
    const environment = await page.evaluate(() => ({
      dpr: devicePixelRatio,
      viewport: { width: innerWidth, height: innerHeight },
      fonts: document.fonts.status,
      storageKeys: Object.keys(localStorage),
      overflow: document.documentElement.scrollWidth > innerWidth,
      geometry: [
        ...document.querySelectorAll(
          ".versions-grid,.version-history,.version-save,.version-save-footer",
        ),
      ].map((n) => ({
        class: n.className,
        x: n.getBoundingClientRect().x,
        y: n.getBoundingClientRect().y,
        width: n.getBoundingClientRect().width,
        height: n.getBoundingClientRect().height,
      })),
    }));
    await fs.writeFile(
      path.join(dest, "environment.json"),
      JSON.stringify(
        {
          ...item,
          ...environment,
          url: page.url(),
          browserVersion: browser.version(),
          errors,
          blocked,
          sha256: crypto
            .createHash("sha256")
            .update(await fs.readFile(shot))
            .digest("hex"),
        },
        null,
        2,
      ),
    );
    if (item.id === "12") {
      await page
        .getByRole("button", { name: "打开并编辑 V2", exact: true })
        .click();
      await page.getByRole("dialog").waitFor();
      await page.screenshot({
        path: path.join(dest, "load-confirmation.png"),
        animations: "disabled",
      });
    }
    console.log(
      `${item.id}: ${errors.length} page errors, ${blocked.length} external requests, DPR1`,
    );
    await context.close();
  }
} finally {
  await browser.close();
}

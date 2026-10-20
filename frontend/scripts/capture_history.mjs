import { chromium } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
const root = path.resolve(process.argv[2] ?? "qa/history/iteration-01");
try {
  await fs.access(root);
  throw Error("Refusing to overwrite evidence");
} catch (e) {
  if (e.code !== "ENOENT") throw e;
}
await fs.mkdir(root, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.VSF_CHROMIUM_EXECUTABLE,
});
try {
  for (const item of [
    { id: "16", width: 1513, height: 1040, route: "/runs?fixture=run-history" },
    {
      id: "16-summary",
      width: 1513,
      height: 1040,
      route: "/runs?fixture=run-history",
    },
    {
      id: "16-date",
      width: 1513,
      height: 1040,
      route: "/runs?fixture=run-history",
    },
    { id: "16-empty", width: 1513, height: 1040, route: "/runs" },
    {
      id: "16-filter-empty",
      width: 1513,
      height: 1040,
      route: "/runs?fixture=run-history",
    },
    { id: "16-error", width: 1513, height: 1040, route: "/runs" },
    {
      id: "16-compact",
      width: 1366,
      height: 768,
      route: "/runs?fixture=run-history",
    },
    {
      id: "16-narrow",
      width: 760,
      height: 900,
      route: "/runs?fixture=run-history",
    },
    { id: "01", width: 1513, height: 1040, route: "/skills?fixture=01" },
    { id: "02", width: 1513, height: 1039, route: "/skills/new?fixture=02" },
    {
      id: "04",
      width: 1513,
      height: 1040,
      route: "/skills/regional-alert/editor?view=linked&fixture=04",
    },
    {
      id: "12",
      width: 1513,
      height: 1040,
      route: "/skills/regional-alert/versions?fixture=12",
    },
    {
      id: "13",
      width: 1513,
      height: 1039,
      route: "/settings/models?fixture=models",
    },
    {
      id: "14",
      width: 1512,
      height: 1040,
      route: "/settings/capabilities?fixture=capabilities",
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
    if (item.id === "16-error")
      await context.addInitScript(() =>
        localStorage.setItem("vsf-frontend-run-v1", "broken"),
      );
    const page = await context.newPage();
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(m.text());
    });
    await page.goto("http://127.0.0.1:6174" + item.route, {
      waitUntil: "networkidle",
    });
    const heading = {
      "01": "我的视觉技能",
      12: "保存完整技能",
      13: "模型接入",
      14: "能力管理",
    }[item.id];
    if (item.id.startsWith("16")) {
      await page
        .getByRole("heading", { name: "运行记录", exact: true })
        .waitFor();
      await page
        .getByText("正在读取本地运行归档…", { exact: true })
        .waitFor({ state: "hidden" });
      if (!["16-empty", "16-error"].includes(item.id))
        await page
          .getByRole("complementary", { name: "运行结果详情", exact: true })
          .waitFor();
      if (item.id === "16-summary")
        await page.getByRole("button", { name: /多车道拥堵/ }).click();
      if (item.id === "16-date")
        await page
          .getByRole("button", { name: "日期：全部", exact: true })
          .click();
      if (item.id === "16-filter-empty")
        await page.getByLabel("搜索运行记录").fill("not-a-skill");
    } else if (heading)
      await page.getByRole("heading", { name: heading, exact: true }).waitFor();
    else if (item.id === "04") {
      await page.getByTestId("scene-media").waitFor();
      await page.waitForFunction(
        () => document.querySelectorAll(".react-flow__node").length >= 4,
      );
    } else if (item.id === "02") {
      await page.getByTestId("creation-preview").waitFor();
      await page.waitForFunction(
        () =>
          document.querySelectorAll(".creation-diagram .react-flow__node")
            .length === 4,
      );
    }
    await page.evaluate(() => document.fonts.ready);
    await page.waitForFunction(() =>
      [...document.images].every((i) => i.complete && i.naturalWidth > 0),
    );
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
    const target = path.join(dest, "implementation.png");
    await page.screenshot({ path: target, animations: "disabled" });
    const env = await page.evaluate(() => ({
      dpr: devicePixelRatio,
      fonts: document.fonts.status,
      storage: Object.keys(localStorage),
      overflow: document.documentElement.scrollWidth > innerWidth,
      geometry: [
        ...document.querySelectorAll(
          ".history-heading,.history-list,.history-detail",
        ),
      ].map((n) => ({
        class: n.className,
        ...n.getBoundingClientRect().toJSON(),
      })),
    }));
    await fs.writeFile(
      path.join(dest, "environment.json"),
      JSON.stringify(
        {
          ...item,
          ...env,
          browser: browser.version(),
          errors,
          blocked,
          sha256: crypto
            .createHash("sha256")
            .update(await fs.readFile(target))
            .digest("hex"),
        },
        null,
        2,
      ),
    );
    if (["16-compact", "16-narrow"].includes(item.id)) {
      await page
        .getByRole("complementary", { name: "运行结果详情" })
        .getByText("历史结果对应当次运行版本，不随当前草稿变化。", {
          exact: true,
        })
        .scrollIntoViewIfNeeded();
      await page.screenshot({
        path: path.join(dest, "detail-scrolled.png"),
        animations: "disabled",
      });
    }
    console.log(item.id, errors.length, blocked.length);
    await context.close();
  }
} finally {
  await browser.close();
}

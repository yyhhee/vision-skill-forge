import { chromium } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
const root = path.resolve(process.argv[2] ?? "qa/create/iteration-01");
try {
  await fs.access(root);
  throw new Error("Refusing to overwrite evidence");
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
    { id: "02", width: 1513, height: 1039, route: "/skills/new?fixture=02" },
    {
      id: "02-compact",
      width: 1366,
      height: 768,
      route: "/skills/new?fixture=02",
    },
    {
      id: "02-narrow",
      width: 760,
      height: 900,
      route: "/skills/new?fixture=02",
    },
    { id: "02-empty", width: 1513, height: 1039, route: "/skills/new" },
    {
      id: "02-expanded",
      width: 1513,
      height: 1039,
      route: "/skills/new?fixture=02",
    },
    { id: "02-unsupported", width: 1513, height: 1039, route: "/skills/new" },
    { id: "02-saved", width: 1513, height: 1039, route: "/skills/new" },
    { id: "01", width: 1513, height: 1040, route: "/skills?fixture=01" },
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
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    await page.goto("http://127.0.0.1:6174" + item.route, {
      waitUntil: "networkidle",
    });
    if (item.id.startsWith("02")) {
      await page
        .getByRole("heading", { name: "用一句话描述你的需求" })
        .waitFor();
      if (!["02-empty", "02-unsupported", "02-saved"].includes(item.id))
        await page.waitForFunction(
          () =>
            document.querySelectorAll(".creation-diagram .react-flow__node")
              .length === 4,
        );
    } else if (item.id === "01")
      await page
        .getByRole("heading", { name: "我的视觉技能", exact: true })
        .waitFor();
    else if (item.id === "12")
      await page
        .getByRole("heading", { name: "保存完整技能", exact: true })
        .waitFor();
    else {
      await page.getByTestId("scene-media").waitFor();
      await page.waitForFunction(
        () => document.querySelectorAll(".react-flow__node").length >= 4,
      );
    }
    await page.evaluate(() => document.fonts.ready);
    if (item.id === "02-expanded")
      await page.getByText("演示示例与高级选项", { exact: true }).click();
    if (item.id === "02-unsupported") {
      await page.getByLabel("需求描述").fill("识别桥梁裂缝");
      await page.getByLabel("技能名称", { exact: true }).fill("桥梁检查");
      await page
        .getByRole("button", { name: "生成演示预览", exact: true })
        .click();
    }
    if (item.id === "02-saved") {
      await page.getByText("演示示例与高级选项", { exact: true }).click();
      await page
        .getByRole("button", { name: "使用区域告警演示示例", exact: true })
        .click();
      await page.getByText("演示示例与高级选项", { exact: true }).click();
      await page
        .getByRole("button", { name: "生成演示预览", exact: true })
        .click();
      await page.getByRole("button", { name: "保存草稿", exact: true }).click();
    }
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
    const environment = await page.evaluate(() => ({
      dpr: devicePixelRatio,
      fonts: document.fonts.status,
      storage: Object.keys(localStorage),
      overflow: document.documentElement.scrollWidth > innerWidth,
      geometry: [
        ...document.querySelectorAll(
          ".creation-columns,.creation-form,.creation-understanding,.creation-input,.creation-diagram,.creation-annotation",
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
          ...environment,
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
    console.log(item.id, errors.length, blocked.length);
    if (item.id === "02-narrow" || item.id === "02-compact") {
      await page
        .getByRole("button", { name: "定位到场景标注", exact: true })
        .scrollIntoViewIfNeeded();
      await page.screenshot({
        path: path.join(dest, "preview-scrolled.png"),
        animations: "disabled",
      });
    }
    await context.close();
  }
} finally {
  await browser.close();
}

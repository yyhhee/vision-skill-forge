import { chromium } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
const root = path.resolve(process.argv[2] ?? "qa/models/iteration-01");
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
    {
      id: "13",
      width: 1513,
      height: 1039,
      route: "/settings/models?fixture=models",
    },
    {
      id: "13-compact",
      width: 1366,
      height: 768,
      route: "/settings/models?fixture=models",
    },
    {
      id: "13-narrow",
      width: 760,
      height: 900,
      route: "/settings/models?fixture=models",
    },
    {
      id: "13-planner",
      width: 1513,
      height: 1039,
      route: "/settings/models?fixture=models",
    },
    { id: "13-normal", width: 1513, height: 1039, route: "/settings/models" },
    {
      id: "13-mapping",
      width: 1513,
      height: 1039,
      route: "/settings/models?fixture=models",
    },
    {
      id: "13-menu",
      width: 1513,
      height: 1039,
      route: "/settings/models?fixture=models",
    },
    {
      id: "13-error",
      width: 1513,
      height: 1039,
      route: "/settings/models?fixture=models",
    },
    {
      id: "13-new",
      width: 1513,
      height: 1039,
      route: "/settings/models?fixture=models",
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
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(m.text());
    });
    await page.goto("http://127.0.0.1:6174" + item.route, {
      waitUntil: "networkidle",
    });
    if (item.id.startsWith("13")) {
      await page
        .getByRole("heading", { name: "模型接入", exact: true })
        .waitFor();
      if (item.id === "13-planner")
        await page.getByRole("tab", { name: "编排模型", exact: true }).click();
      if (item.id === "13-mapping") {
        await page.getByText("可选映射配置", { exact: true }).click();
        await page.getByLabel("自定义响应字段", { exact: true }).check();
      }
      if (item.id === "13-menu")
        await page
          .getByRole("button", { name: "更多操作：Rex-Omni", exact: true })
          .click();
      if (item.id === "13-error") {
        await page
          .getByLabel("服务地址", { exact: true })
          .fill("file:///not-an-api");
        await page
          .getByRole("button", { name: "保存配置", exact: true })
          .click();
      }
      if (item.id === "13-new")
        await page
          .getByRole("button", { name: "添加模型", exact: true })
          .click();
    } else if (item.id === "01")
      await page
        .getByRole("heading", { name: "我的视觉技能", exact: true })
        .waitFor();
    else if (item.id === "12")
      await page
        .getByRole("heading", { name: "保存完整技能", exact: true })
        .waitFor();
    else if (item.id === "02") {
      await page.getByTestId("creation-preview").waitFor();
      await page.waitForFunction(
        () =>
          document.querySelectorAll(".creation-diagram .react-flow__node")
            .length === 4,
      );
    } else {
      await page.getByTestId("scene-media").waitFor();
      await page.waitForFunction(
        () => document.querySelectorAll(".react-flow__node").length >= 4,
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
    const environment = await page.evaluate(() => ({
      dpr: devicePixelRatio,
      fonts: document.fonts.status,
      storage: Object.keys(localStorage),
      overflow: document.documentElement.scrollWidth > innerWidth,
      geometry: [
        ...document.querySelectorAll(
          ".models-columns,.models-list,.models-editor,.model-fields,.model-save",
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
    if (
      ["13-compact", "13-narrow", "13-mapping", "13-error"].includes(item.id)
    ) {
      await page
        .getByRole("button", { name: "保存配置", exact: true })
        .scrollIntoViewIfNeeded();
      await page.screenshot({
        path: path.join(dest, "editor-scrolled.png"),
        animations: "disabled",
      });
    }
    console.log(item.id, errors.length, blocked.length);
    await context.close();
  }
} finally {
  await browser.close();
}

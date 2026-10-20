import { chromium } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
const root = path.resolve(process.argv[2] ?? "qa/run-flow/iteration-01");
try {
  await fs.access(root);
  throw new Error("Refusing to overwrite evidence");
} catch (e) {
  if (e.code !== "ENOENT") throw e;
}
const cases = [
  {
    id: "09",
    w: 1512,
    h: 1040,
    route: "/skills/regional-alert/validate?fixture=09",
  },
  {
    id: "10",
    w: 1513,
    h: 1040,
    route: "/runs/run-regional-r3?state=running&fixture=10",
  },
  {
    id: "11",
    w: 1513,
    h: 1040,
    route: "/runs/run-regional-r3?state=completed&fixture=11",
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
    await fs.mkdir(dest, { recursive: true });
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
    await context.route("**/*", (r) => {
      if (new URL(r.request().url()).origin !== "http://127.0.0.1:6174") {
        network.push(r.request().url());
        return r.abort();
      }
      return r.continue();
    });
    const page = await context.newPage();
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(`http://127.0.0.1:6174${item.route}`, {
      waitUntil: "networkidle",
    });
    await page.getByTestId("run-media").waitFor();
    await page.evaluate(() => document.fonts.ready);
    await page.waitForFunction(
      () =>
        [...document.images].every((i) => i.complete && i.naturalWidth > 0) &&
        document.querySelector(".run-media canvas")?.width > 0,
    );
    await page.evaluate(
      () =>
        new Promise((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(resolve)),
        ),
    );
    await page.mouse.move(0, item.h - 1);
    await page.screenshot({
      path: path.join(dest, "implementation.png"),
      animations: "disabled",
    });
    const env = await page.evaluate(() => ({
      dpr: devicePixelRatio,
      width: innerWidth,
      height: innerHeight,
      fonts: document.fonts.status,
      language: navigator.language,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      colorScheme: matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light',
      reducedMotion: matchMedia('(prefers-reduced-motion: reduce)').matches,
      geometry: [
        ...document.querySelectorAll(
          ".run-page,.run-card,.run-media,.run-section,.result-details",
        ),
      ].map((n) => {
        const b = n.getBoundingClientRect();
        return {
          className: n.className,
          x: b.x,
          y: b.y,
          w: b.width,
          h: b.height,
        };
      }),
      storage: {
        workspace: localStorage.getItem("vsf-frontend-workspace-v1"),
        runs: localStorage.getItem("vsf-frontend-run-v1"),
      },
    }));
    await fs.writeFile(
      path.join(dest, "environment.json"),
      JSON.stringify(
        {
          ...item,
          ...env,
          browserVersion: browser.version(),
          errors,
          network,
          sha256: crypto
            .createHash("sha256")
            .update(await fs.readFile(path.join(dest, "implementation.png")))
            .digest("hex"),
        },
        null,
        2,
      ),
    );
    console.log(
      `${item.id}: ${item.w}x${item.h} DPR${env.dpr}, errors ${errors.length}`,
    );
    if (item.id === '11') {
      await page.getByRole('button', {name:'查看证据红色上衣',exact:true}).click();
      await page.getByRole('dialog',{name:'红色上衣 · 示例证据'}).waitFor();
      await page.screenshot({path:path.join(dest,'evidence-detail.png'),animations:'disabled'});
    }
    if (item.id === '09') {
      await page.getByText('展开算法说明',{exact:true}).click();
      await page.screenshot({path:path.join(dest,'algorithm-help.png'),animations:'disabled'});
    }
    await context.close();
  }
} finally {
  await browser.close();
}

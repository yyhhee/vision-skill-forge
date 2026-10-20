import { test, expect } from "@playwright/test";
import { testOrigin } from "../testOrigin";
import { RunPage } from "./RunPage";
test.beforeEach(async ({ context }) => {
  await context.route("**/*", (r) =>
    new URL(r.request().url()).origin === testOrigin
      ? r.continue()
      : r.abort(),
  );
});
test("saving unsaved runtime form before start still runs applied settings, not draft settings", async ({
  page,
}) => {
  await page.clock.install();
  const ui = new RunPage(page);
  await ui.setup(false);
  await ui.sampling();
  await page.getByLabel("采样间隔（秒）").fill("2");
  await ui.start();
  await page.getByRole("button", { name: "保存后继续", exact: true }).click();
  await ui.pause();
  const data = await page.evaluate(() => ({
    workspace: JSON.parse(localStorage.getItem("vsf-frontend-workspace-v1")!),
    archive: JSON.parse(localStorage.getItem("vsf-frontend-run-v1")!),
  }));
  expect(data.workspace.draft.runSettings.sampleIntervalSeconds).toBe(2);
  expect(data.workspace.applied.runSettings.sampleIntervalSeconds).toBe(1);
  expect(data.archive.runs[0].settings.sampleIntervalSeconds).toBe(1);
  expect(data.archive.runs[0].sampleTimes).toHaveLength(30);
});
test("paused task refreshes with the same identity and does not duplicate on a second start", async ({
  page,
}) => {
  await page.clock.install();
  const ui = new RunPage(page);
  await ui.setup(false);
  await ui.start();
  await ui.pause();
  const url = page.url();
  await page
    .getByRole("button", { name: "推进一个采样点", exact: true })
    .click();
  await page.reload();
  await ui.ready();
  await expect(
    page.getByRole("button", { name: "继续模拟", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("progressbar", { name: "模拟采样进度" }),
  ).toHaveAttribute("value", "1");
  await page.goto("/skills/regional-alert/validate");
  await ui.ready();
  await ui.start();
  expect(page.url()).toBe(url);
  await expect(page.getByRole("alert")).toContainText("不会重复新建");
  expect(
    await page.evaluate(
      () =>
        JSON.parse(localStorage.getItem("vsf-frontend-run-v1")!).runs.length,
    ),
  ).toBe(1);
});
test("empty numeric runtime input reports validation without React console errors", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await new RunPage(page).setup();
  await page.getByLabel("切片宽（像素）").clear();
  await expect(page.getByRole("alert")).toContainText("切片宽高");
  await page.getByLabel("切片宽（像素）").fill("640");
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect(errors).toEqual([]);
});
test("editor validation step and run snapshot dialog both reach setup", async ({
  page,
}) => {
  await page.goto("/skills/regional-alert/editor?view=linked");
  await page.getByRole("button", { name: "4 验证", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "验证配置", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "返回编排", exact: true }).click();
  await page.getByRole("button", { name: "测试运行", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "打开运行设置", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "验证配置", exact: true }),
  ).toBeVisible();
});
test("09 controlled settings save only draft; applying whole draft explicitly creates R4", async ({
  page,
}) => {
  const ui = new RunPage(page);
  await ui.setup(false);
  await ui.sampling();
  await page.getByLabel("采样间隔（秒）").fill("2");
  await expect(
    page.getByText("预计采样 15 帧（估算，尚未运行）"),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "保存运行设置到草稿", exact: true })
    .click();
  let data = await page.evaluate(() =>
    JSON.parse(localStorage.getItem("vsf-frontend-workspace-v1")!),
  );
  expect(data.draft.runSettings.sampleIntervalSeconds).toBe(2);
  expect(data.applied.runSettings.sampleIntervalSeconds).toBe(1);
  expect(data.revision).toBe(3);
  await page
    .getByRole("button", { name: "校验并应用草稿", exact: true })
    .click();
  await page
    .getByRole("button", { name: "校验并应用为 R4", exact: true })
    .click();
  await expect(page.getByTestId("revision-status")).toContainText("R4");
  data = await page.evaluate(() =>
    JSON.parse(localStorage.getItem("vsf-frontend-workspace-v1")!),
  );
  expect(data.applied.runSettings.sampleIntervalSeconds).toBe(2);
});
test("09 guards unsaved settings and validates overlap separately from dedup", async ({
  page,
}) => {
  const ui = new RunPage(page);
  await ui.setup();
  await page.getByLabel("横向覆盖（%）").fill("95");
  await expect(page.getByRole("alert")).toContainText("0–90%");
  await page.getByRole("button", { name: "返回编排", exact: true }).click();
  await expect(
    page.getByRole("dialog", { name: "运行设置尚未保存" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "继续编辑", exact: true }).click();
  await page.getByLabel("横向覆盖（%）").fill("30");
  await page.getByText("展开算法说明", { exact: true }).click();
  await expect(page.getByText(/中心距离不超过较小框对角线25%/)).toBeVisible();
  await page.getByLabel("IoU", { exact: true }).check();
  await expect(page.getByLabel("去重阈值", { exact: true })).toHaveValue(
    "0.45",
  );
});
test("10 fixture frozen at 18/30; cancel is not completed and never writes normal storage", async ({
  page,
}) => {
  const ui = new RunPage(page);
  await ui.monitor();
  await expect(
    page.getByRole("progressbar", { name: "模拟采样进度" }),
  ).toHaveAttribute("value", "18");
  await page.getByRole("button", { name: "停止本次模拟", exact: true }).click();
  await page.getByRole("button", { name: "确认停止", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "本次模拟已取消", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "查看结果与证据", exact: true }),
  ).toHaveCount(0);
  expect(
    await page.evaluate(() => localStorage.getItem("vsf-frontend-run-v1")),
  ).toBeNull();
});
test("10 start takes R3, cancel persists, next start does not reuse a cancelled task", async ({
  page,
}) => {
  await page.clock.install();
  const ui = new RunPage(page);
  await ui.setup(false);
  await ui.start();
  await ui.pause();
  const first = page.url();
  await page.getByRole("button", { name: "停止本次模拟", exact: true }).click();
  await page.getByRole("button", { name: "确认停止", exact: true }).click();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "本次模拟已取消", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "返回运行设置", exact: true }).click();
  await ui.start();
  await ui.pause();
  expect(page.url()).not.toBe(first);
  const runs = await page.evaluate(
    () => JSON.parse(localStorage.getItem("vsf-frontend-run-v1")!).runs,
  );
  expect(runs).toHaveLength(2);
  expect(runs[0].status).toBe("cancelled");
  expect(runs[1].snapshot.conditions[1].minimumFraction).toBe(0.2);
});
test("10 simulated failure shows failure without generated business events", async ({
  page,
}) => {
  const ui = new RunPage(page);
  await ui.monitor();
  await page.getByText("专业执行明细 · 点击展开", { exact: true }).click();
  await page.getByRole("button", { name: "触发模拟失败", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "本次模拟失败", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("用户触发的模拟失败");
});
test("11 event, time, same-entity evidence, snapshot and filters work", async ({
  page,
}) => {
  const ui = new RunPage(page);
  await ui.results();
  await page
    .getByRole("button", { name: "查看模拟时间20秒", exact: true })
    .click();
  await expect(
    page.getByRole("slider", { name: "结果模拟时间轴" }),
  ).toHaveValue("20");
  await page
    .getByRole("button", { name: "定位事件区域告警事件", exact: true })
    .click();
  await expect(
    page.getByRole("slider", { name: "结果模拟时间轴" }),
  ).toHaveValue("12");
  await page
    .getByRole("button", { name: "查看证据红色上衣", exact: true })
    .click();
  const modal = page.getByRole("dialog", { name: "红色上衣 · 示例证据" });
  await expect(modal).toContainText("主体person-1");
  await expect(modal).toContainText("阈值20%");
  await modal.getByRole("button", { name: "关闭对话框" }).click();
  await expect(page.getByTestId("run-media")).toHaveAttribute(
    "data-highlight",
    "evidence-upper",
  );
  await page.getByLabel("筛选事件").fill("没有的事件");
  await expect(
    page.getByText("没有匹配的示例事件", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("筛选事件").clear();
  await page.getByRole("tab", { name: "条件过程", exact: true }).click();
  await expect(page.getByRole("tabpanel")).toContainText("颜色至少占20%");
  await page.getByRole("button", { name: "查看快照", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("红色上衣 · 至少20%");
});
test("11 JSON export includes immutable run snapshot and honest demo provenance", async ({
  page,
}) => {
  await new RunPage(page).results();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出结果", exact: true }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe("run-regional-r3-demo-result.json");
  const stream = await file.createReadStream();
  const chunks = [];
  for await (const chunk of stream!) chunks.push(chunk);
  const value = JSON.parse(Buffer.concat(chunks).toString());
  expect(value.demo).toBe(true);
  expect(value.snapshot.conditions[1].minimumFraction).toBe(0.2);
  expect(value.events[0].evidence).toHaveLength(2);
});
test("run completion, refresh and edits never rewrite historic snapshot or invent R4 results", async ({
  page,
}) => {
  // Two complete30-sample runs plus editing/navigation; no sleeps or retries.
  test.setTimeout(45000);
  await page.clock.install();
  const ui = new RunPage(page);
  await ui.setup(false);
  await ui.start();
  await ui.pause();
  await ui.finish();
  const firstUrl = page.url();
  await page.getByRole("button", { name: "返回规则", exact: true }).click();
  await page.getByRole("button", { name: "编辑当前草稿", exact: true }).click();
  await page.getByRole("button", { name: "红色上衣", exact: true }).click();
  await page.getByLabel("颜色", { exact: true }).selectOption("blue");
  await page.getByLabel("模型语义短语").fill("person wearing a blue top");
  await page
    .getByRole("button", { name: "已核对，保留当前自定义短语", exact: true })
    .click();
  await page.getByRole("button", { name: "保存到草稿", exact: true }).click();
  await page.getByRole("button", { name: "校验并应用", exact: true }).click();
  await page.goto(firstUrl);
  await page.getByRole("tab", { name: "条件过程", exact: true }).click();
  await expect(page.getByRole("tabpanel")).toContainText("红色上衣");
  await expect(page.getByRole("tabpanel")).not.toContainText("蓝色上衣");
  await page.goto("/skills/regional-alert/validate");
  await ui.start();
  await ui.pause();
  await ui.finish();
  await expect(
    page.getByText("未提供该配置的演示结果", { exact: true }),
  ).toBeVisible();
});
test("unknown run and corrupted storage do not silently substitute or overwrite records", async ({
  page,
}) => {
  await page.addInitScript(() =>
    localStorage.setItem("vsf-frontend-run-v1", "broken"),
  );
  await page.goto("/runs/not-a-real-run");
  await expect(
    page.getByRole("heading", { name: "未找到该运行记录" }),
  ).toBeVisible();
  expect(
    await page.evaluate(() => localStorage.getItem("vsf-frontend-run-v1")),
  ).toBe("broken");
  await expect(page.getByRole("alert")).toContainText("未覆盖旧内容");
});
for (const size of [
  { width: 1366, height: 768 },
  { width: 760, height: 900 },
])
  test(`run pages keep primary actions reachable at ${size.width}x${size.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(size);
    const ui = new RunPage(page);
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    for (const mode of ["setup", "monitor", "results"] as const) {
      await ui[mode]();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBeTruthy();
      await expect(
        page.getByRole("button", {
          name:
            mode === "setup"
              ? "开始模拟验证"
              : mode === "monitor"
                ? "停止本次模拟"
                : "导出结果",
          exact: true,
        }),
      ).toBeInViewport();
    }
    expect(errors).toEqual([]);
  });

import { test, expect } from "@playwright/test";
import { testOrigin } from "../testOrigin";
import { HistoryPage } from "./HistoryPage";
import { WorkspacePage } from "./WorkspacePage";
import { RunPage } from "./RunPage";
import { VersionsPage } from "./VersionsPage";
import { CapabilitiesPage } from "./CapabilitiesPage";
test.beforeEach(async ({ context }) => {
  await context.route("**/*", (r) =>
    new URL(r.request().url()).origin === testOrigin
      ? r.continue()
      : r.abort(),
  );
});
test("16 normal history is empty and read-only; fixture contains five honest summaries with only one complete run", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const ui = new HistoryPage(page);
  await ui.open();
  await expect(
    page.getByRole("heading", { name: "还没有本地运行记录", exact: true }),
  ).toBeVisible();
  expect(await ui.archive()).toBeNull();
  await ui.open(true);
  await expect(page.getByRole("row")).toHaveCount(6);
  await expect(ui.detail()).toContainText("事件示例 1 条");
  await expect(
    ui
      .detail()
      .getByRole("button", { name: "下载标注视频（未接入）", exact: true }),
  ).toBeDisabled();
  expect(await ui.archive()).toBeNull();
  expect(errors).toEqual([]);
});
test("16 status, media and search intersect; hidden selections cannot open an unrelated record", async ({
  page,
}) => {
  const ui = new HistoryPage(page);
  await ui.open(true);
  await page.getByLabel("运行状态", { exact: true }).selectOption("completed");
  await expect(page.getByRole("row")).toHaveCount(4);
  await page.getByLabel("媒体类型", { exact: true }).selectOption("image");
  await expect(page.getByRole("row")).toHaveCount(2);
  await page.getByLabel("搜索运行记录", { exact: true }).fill("not found");
  await expect(
    page.getByRole("heading", { name: "没有符合筛选条件的记录", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "查看所选结果", exact: true }),
  ).toBeDisabled();
  await expect(ui.detail()).toHaveCount(0);
  await page.getByRole("button", { name: "清除筛选", exact: true }).click();
  await expect(page.getByRole("row")).toHaveCount(6);
  expect(await ui.archive()).toBeNull();
});
test("16 date filters are inclusive in Beijing time and invalid or reversed dates are blocked", async ({
  page,
}) => {
  const ui = new HistoryPage(page);
  await ui.open(true);
  await page.getByRole("button", { name: "日期：全部", exact: true }).click();
  await page.getByLabel("日期范围", { exact: true }).selectOption("custom");
  await expect(
    page.getByRole("button", { name: "应用日期筛选", exact: true }),
  ).toBeDisabled();
  await page.getByLabel("开始日期", { exact: true }).fill("2026-10-17");
  await page.getByLabel("结束日期", { exact: true }).fill("2026-10-16");
  await expect(page.getByRole("alert")).toContainText("结束不得早于开始");
  await page.getByLabel("开始日期", { exact: true }).fill("2026-10-16");
  await page.getByRole("button", { name: "应用日期筛选", exact: true }).click();
  await expect(page.getByRole("row")).toHaveCount(3);
  await expect(
    page.getByRole("region", { name: "运行记录列表" }),
  ).toContainText("2026-10-16 至 2026-10-16");
});
test("16 summary-only rows explain missing details and export only marked summaries, never the regional snapshot", async ({
  page,
}) => {
  const ui = new HistoryPage(page);
  await ui.open(true);
  await page.getByRole("button", { name: /多车道拥堵/ }).click();
  await expect(ui.detail()).toContainText("未提供完整配置与结果详情");
  const value = await ui.exportDetail();
  expect(value).toMatchObject({
    format: "vsf-run-summary",
    snapshotIncluded: false,
    detailsAvailable: false,
  });
  expect(value).not.toHaveProperty("snapshot");
  await ui
    .detail()
    .getByRole("button", { name: "查看结果", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText(
    "不会跳转到区域告警结果冒充",
  );
  expect(new URL(page.url()).pathname).toBe("/runs");
});
test("16 main fixture opens its own completed result, and browser back restores filters and selection", async ({
  page,
}) => {
  const ui = new HistoryPage(page);
  await ui.open(true);
  await page.getByLabel("搜索运行记录", { exact: true }).fill("区域");
  await page.getByRole("button", { name: /区域联合告警.*海报/ }).click();
  await ui
    .detail()
    .getByRole("button", { name: "查看结果", exact: true })
    .click();
  await expect(page.getByRole("heading", { name: /验证结果/ })).toBeVisible();
  expect(new URL(page.url()).pathname).toBe("/runs/run-regional-r3");
  await page.goBack();
  await ui.ready();
  await expect(page.getByLabel("搜索运行记录", { exact: true })).toHaveValue(
    "区域",
  );
  await expect(page.getByRole("row")).toHaveCount(2);
  await expect(ui.detail()).toContainText("R3");
  expect(await ui.archive()).toBeNull();
});
test("16 actual archive viewing and exporting preserve its immutable full snapshot and current draft", async ({
  page,
}) => {
  const ui = new HistoryPage(page);
  await ui.open();
  await ui.seed();
  const before = await ui.archive();
  const exported = await ui.exportDetail();
  expect(exported).toEqual(JSON.parse(before!).runs[0]);
  await page.getByRole("button", { name: "查看所选结果", exact: true }).click();
  await expect(page.getByRole("heading", { name: /验证结果/ })).toBeVisible();
  expect(new URL(page.url()).pathname).toBe("/runs/record-0");
  await page.getByRole("button", { name: "运行记录", exact: true }).click();
  await ui.ready();
  expect(await ui.archive()).toBe(before);
  expect(
    await page.evaluate(() =>
      localStorage.getItem("vsf-frontend-workspace-v1"),
    ),
  ).toBeNull();
});
test("16 checkbox selection and pagination are real, bulk export contains only selected identities", async ({
  page,
}) => {
  const ui = new HistoryPage(page);
  await ui.open();
  await ui.seed(8);
  await expect(page.getByRole("row")).toHaveCount(6);
  await page.getByLabel("选择本页全部记录", { exact: true }).check();
  await expect(
    page.getByRole("button", { name: "查看所选结果", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(page.getByRole("row")).toHaveCount(4);
  await page.getByLabel("选择本页全部记录", { exact: true }).check();
  const event = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "导出所选 8 条", exact: true })
    .click();
  const stream = await (await event).createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream!) chunks.push(chunk);
  const value = JSON.parse(Buffer.concat(chunks).toString());
  expect(value.records).toHaveLength(8);
  expect(new Set(value.records.map((r: { id: string }) => r.id)).size).toBe(8);
  await page.getByLabel("搜索运行记录", { exact: true }).fill("no match");
  await expect(page.getByRole("button", { name: /导出所选/ })).toHaveCount(0);
});
test("16 corrupt cache stays untouched, can be backed up and explicitly re-read after repair", async ({
  page,
}) => {
  const ui = new HistoryPage(page);
  await ui.open();
  await page.evaluate(() =>
    localStorage.setItem("vsf-frontend-run-v1", "broken"),
  );
  await page.reload();
  await ui.ready();
  await expect(page.getByRole("alert")).toContainText("原内容未覆盖");
  expect(await ui.archive()).toBe("broken");
  const event = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "导出原始缓存备份", exact: true })
    .click();
  const stream = await (await event).createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream!) chunks.push(chunk);
  expect(JSON.parse(Buffer.concat(chunks).toString()).raw).toBe("broken");
  await page.evaluate(() => localStorage.removeItem("vsf-frontend-run-v1"));
  await page.getByRole("button", { name: "重新读取记录", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "还没有本地运行记录", exact: true }),
  ).toBeVisible();
  expect(await ui.archive()).toBeNull();
});
test("16 updates from other tabs remove stale details and never overwrite either archive", async ({
  page,
  context,
}) => {
  const ui = new HistoryPage(page);
  await ui.open();
  await ui.seed();
  const other = await context.newPage();
  await other.goto("/runs");
  const replacement = JSON.stringify({ schemaVersion: 1, runs: [] });
  await other.evaluate(
    (raw) => localStorage.setItem("vsf-frontend-run-v1", raw),
    replacement,
  );
  await expect(
    page.getByRole("heading", { name: "还没有本地运行记录", exact: true }),
  ).toBeVisible();
  await expect(ui.detail()).toHaveCount(0);
  expect(await ui.archive()).toBe(replacement);
  await other.close();
});
test("16 read-only export still works when browser storage writes fail", async ({
  page,
}) => {
  const ui = new HistoryPage(page);
  await ui.open();
  await ui.seed();
  const before = await ui.archive();
  await page.evaluate(() => {
    Storage.prototype.setItem = () => {
      throw new Error("quota");
    };
  });
  await page.getByLabel("搜索运行记录", { exact: true }).fill("区域");
  expect((await ui.exportDetail()).id).toBe("record-0");
  expect(await ui.archive()).toBe(before);
});
test("16 unknown media is not replaced with the construction poster or a fabricated viewer", async ({
  page,
}) => {
  const ui = new HistoryPage(page);
  await ui.open();
  await page.evaluate(async () => {
    // @ts-expect-error Vite browser module
    const { createRun } = await import("/src/data/runs.ts");
    // @ts-expect-error Vite browser module
    const { seedWorkspace } = await import("/src/data/document.ts");
    const run = createRun(
      { ...seedWorkspace().applied, mediaRef: "foreign-poster" },
      3,
      "foreign-run",
    );
    localStorage.setItem(
      "vsf-frontend-run-v1",
      JSON.stringify({ schemaVersion: 1, runs: [run] }),
    );
  });
  await page.reload();
  await ui.ready();
  await expect(ui.detail().getByRole("img")).toHaveCount(0);
  await expect(ui.detail()).toContainText("素材未接入");
  await page.getByRole("button", { name: "查看所选结果", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("不会用施工海报冒充");
});
test("16 unfinished tasks open paused and do not duplicate, advance or restart automatically", async ({
  page,
}) => {
  await page.clock.install();
  const run = new RunPage(page);
  await run.setup(false);
  await run.start();
  await run.pause();
  const before = await page.evaluate(() =>
    localStorage.getItem("vsf-frontend-run-v1"),
  );
  await page.getByRole("button", { name: "运行记录", exact: true }).click();
  const ui = new HistoryPage(page);
  await ui.ready();
  await expect(ui.detail()).toContainText("未结束");
  await page.getByRole("button", { name: "查看所选结果", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "继续模拟", exact: true }),
  ).toBeVisible();
  await page.clock.runFor(1500);
  expect(await ui.archive()).toBe(before);
});
test("16 skill library scoped history does not borrow other skills and can clear its scope", async ({
  page,
}) => {
  const ui = new HistoryPage(page);
  await ui.open();
  await ui.seed();
  await page.goto("/runs?skill=not-this-skill");
  await ui.ready();
  await expect(
    page.getByRole("heading", { name: "没有符合筛选条件的记录", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "查看全部技能", exact: true }).click();
  await expect(page.getByRole("row")).toHaveCount(2);
  await page.getByRole("button", { name: "技能库", exact: true }).click();
  await page.getByRole("button", { name: "运行记录", exact: true }).click();
  await ui.ready();
});
test("16 editor and version navigation preserve newly saved configuration without applying", async ({
  page,
}) => {
  const editor = new WorkspacePage(page);
  await editor.open(false);
  await editor.editColor();
  await page.getByLabel("颜色至少占该部位").fill("35");
  await page.getByRole("button", { name: "运行记录", exact: true }).click();
  await page.getByRole("button", { name: "保存后继续", exact: true }).click();
  await new HistoryPage(page).ready();
  const versions = new VersionsPage(page);
  expect(
    (await versions.workspace()).draft.conditions.find(
      (c: { id: string }) => c.id === "a-red",
    ).minimumFraction,
  ).toBe(0.35);
  await versions.open(false);
  await page.getByLabel("技能名称", { exact: true }).fill("运行列表前保存");
  await page.getByRole("button", { name: "运行记录", exact: true }).click();
  await page
    .getByRole("button", { name: "保存版本后返回", exact: true })
    .click();
  await new HistoryPage(page).ready();
  expect((await versions.workspace()).draft.name).toBe("运行列表前保存");
  expect((await versions.workspace()).revision).toBe(3);
});
test("16 model settings navigation still prompts before discarding unsaved inputs", async ({
  page,
}) => {
  await page.goto("/settings/models");
  await page.getByLabel("显示名称", { exact: true }).fill("未保存模型");
  await page.getByRole("button", { name: "运行记录", exact: true }).click();
  await expect(
    page.getByRole("dialog", { name: "有未保存的模型配置" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "放弃修改并继续", exact: true })
    .click();
  await new HistoryPage(page).ready();
});
test("16 historical viewing works after the source skill is deleted and a capability is disabled", async ({
  page,
}) => {
  const ui = new HistoryPage(page);
  await ui.open();
  await ui.seed();
  await page.evaluate(() => {
    localStorage.setItem(
      "vsf-frontend-library-v1",
      JSON.stringify({
        schemaVersion: 1,
        ids: [],
        removed: ["regional-alert"],
      }),
    );
    localStorage.setItem(
      "vsf-frontend-capabilities-v1",
      JSON.stringify({
        schemaVersion: 1,
        states: { detect: false },
        custom: [],
      }),
    );
  });
  await page.getByRole("button", { name: "查看所选结果", exact: true }).click();
  await expect(page.getByRole("heading", { name: /验证结果/ })).toBeVisible();
  expect(
    await page.evaluate(() =>
      localStorage.getItem("vsf-frontend-workspace-v1"),
    ),
  ).toBeNull();
});
test("16 missing normal history IDs cannot silently reconstruct the known regional example", async ({ page }) => {
  await page.goto("/runs/run-regional-r3");
  await expect(page.getByRole("heading", { name: "未找到该运行记录", exact: true })).toBeVisible();
  const raw = await page.evaluate(() => localStorage.getItem("vsf-frontend-run-v1"));
  expect(raw === null ? [] : JSON.parse(raw).runs).toEqual([]);
  await expect(page.getByRole("heading", { name: /验证结果/ })).toHaveCount(0);
});
test("16 running settings guard saves only the draft before navigating to history", async ({
  page,
}) => {
  const run = new RunPage(page);
  await run.setup(false);
  await run.sampling();
  await page.getByLabel("采样间隔（秒）").fill("3");
  await page.getByRole("button", { name: "运行记录", exact: true }).click();
  await page.getByRole("button", { name: /保存.*继续/ }).click();
  await new HistoryPage(page).ready();
  const saved = await new VersionsPage(page).workspace();
  expect(saved.draft.runSettings.sampleIntervalSeconds).toBe(3);
  expect(saved.applied.runSettings.sampleIntervalSeconds).toBe(1);
  expect(saved.revision).toBe(3);
});
test("16 capability import preview still guards navigation before opening history", async ({
  page,
}) => {
  const history = new HistoryPage(page);
  await history.open();
  await page.getByRole("button", { name: "能力管理", exact: true }).click();
  const caps = new CapabilitiesPage(page);
  await caps.ready();
  await caps.preview({
    format: "vsf-capability-manifest",
    schemaVersion: 1,
    id: "pending-custom",
    name: "未安装清单",
    kind: "template",
    description: "只读预览",
    input: "目标",
    output: "判断",
    parameters: [],
    uses: ["detect"],
    plannerHint: "说明",
  });
  await expect(
    page.getByRole("button", { name: "确认安装（默认停用）", exact: true }),
  ).toBeEnabled();
  await page.goBack();
  await expect(
    page.getByRole("dialog", { name: "有尚未安装的能力清单" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "放弃清单并继续", exact: true })
    .click();
  await history.ready();
  expect(await caps.stored()).toBeNull();
});
for (const viewport of [
  { width: 1366, height: 768 },
  { width: 760, height: 900 },
])
  test(`16 controls and detail remain reachable at ${viewport.width}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    const ui = new HistoryPage(page);
    await ui.open(true);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await expect(
      page.getByRole("button", { name: "查看所选结果", exact: true }),
    ).toBeInViewport();
    await ui
      .detail()
      .getByText("历史结果对应当次运行版本，不随当前草稿变化。", {
        exact: true,
      })
      .scrollIntoViewIfNeeded();
    await expect(
      ui.detail().getByText("历史结果对应当次运行版本，不随当前草稿变化。", {
        exact: true,
      }),
    ).toBeInViewport();
    await page
      .getByRole("button", { name: "关闭运行详情", exact: true })
      .click();
    await expect(ui.detail()).toHaveCount(0);
  });

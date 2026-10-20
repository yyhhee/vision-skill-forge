import { test, expect } from "@playwright/test";
import { testOrigin } from "../testOrigin";
import { CapabilitiesPage } from "./CapabilitiesPage";
import { WorkspacePage } from "./WorkspacePage";
import { RunPage } from "./RunPage";
import { VersionsPage } from "./VersionsPage";
const manifest = {
  format: "vsf-capability-manifest",
  schemaVersion: 1,
  id: "my-custom",
  name: "我的组合能力",
  kind: "template",
  description: "仅声明组合，不执行代码",
  input: "目标",
  output: "目标判断",
  parameters: ["数量"],
  uses: ["detect"],
  plannerHint: "按用户需求组合已有能力。",
};
test.beforeEach(async ({ context }) => {
  await context.route("**/*", (r) =>
    new URL(r.request().url()).origin === testOrigin
      ? r.continue()
      : r.abort(),
  );
});
test("14 list, controlled filters, actual usage and dependency selection work without initial writes", async ({
  page,
}) => {
  const ui = new CapabilitiesPage(page);
  await ui.open();
  await expect(page.getByRole("row")).toHaveCount(6);
  await expect(page.getByRole("region", { name: "能力详情" })).toContainText(
    "区域联合告警",
  );
  await page
    .getByRole("region", { name: "能力详情" })
    .getByRole("button", { name: /筛色占比/ })
    .click();
  await expect(
    page.getByRole("heading", { name: "筛色占比", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("显示基础依赖能力")).toBeChecked();
  await page.getByRole("tab", { name: "组合模板", exact: true }).click();
  await expect(page.getByRole("row")).toHaveCount(3);
  await expect(page.getByRole("region", { name: "能力详情" })).toContainText(
    "请从当前列表选择",
  );
  await page.getByLabel("搜索能力").fill("nothing-matches");
  await expect(
    page.getByText("没有符合筛选条件的能力。", { exact: true }),
  ).toBeVisible();
  expect(await ui.stored()).toBeNull();
});
test("14 builtin delete is disabled and referenced disabling is explicit and persists without rewriting skills", async ({
  page,
}) => {
  const ui = new CapabilitiesPage(page);
  await ui.open();
  await ui.menu("目标检测");
  await expect(
    page.getByRole("button", { name: "内置不可删除", exact: true }),
  ).toBeDisabled();
  await page.keyboard.press("Escape");
  await page.getByRole("switch", { name: "颜色复核启用状态" }).click();
  await expect(page.getByRole("dialog")).toContainText("运行 R3");
  await expect(page.getByRole("dialog")).toContainText("区域联合告警");
  await page.getByRole("button", { name: "取消", exact: true }).click();
  expect(await ui.stored()).toBeNull();
  await ui.disable("颜色复核");
  await page.reload();
  await ui.ready();
  await expect(
    page.getByRole("switch", { name: "颜色复核启用状态" }),
  ).toHaveAttribute("aria-checked", "false");
  expect(
    await page.evaluate(() =>
      localStorage.getItem("vsf-frontend-workspace-v1"),
    ),
  ).toBeNull();
});
test("14 imported metadata is previewed then installed disabled; enabling is not execution and deletion persists", async ({
  page,
}) => {
  const ui = new CapabilitiesPage(page);
  await ui.open();
  await ui.preview(manifest);
  expect(await ui.stored()).toBeNull();
  await expect(page.getByRole("dialog")).toContainText("仅清单");
  await page
    .getByRole("button", { name: "确认安装（默认停用）", exact: true })
    .click();
  await expect(
    page.getByRole("switch", { name: "我的组合能力启用状态" }),
  ).toHaveAttribute("aria-checked", "false");
  await page.getByRole("switch", { name: "我的组合能力启用状态" }).click();
  expect((await ui.stored()).states["my-custom"]).toBe(true);
  await page.getByText("开发者接口", { exact: true }).click();
  await expect(page.getByRole("region", { name: "能力详情" })).toContainText(
    "执行器未接入",
  );
  await page
    .getByRole("button", { name: "删除自定义能力", exact: true })
    .click();
  await page.getByRole("button", { name: "确认删除", exact: true }).click();
  await page.reload();
  await ui.ready();
  await expect(
    page.getByRole("switch", { name: "我的组合能力启用状态" }),
  ).toHaveCount(0);
});
test("14 unsafe and duplicate imports do not mutate any stored configuration or execute scripts", async ({
  page,
}) => {
  const ui = new CapabilitiesPage(page);
  await ui.open();
  for (const invalid of [
    { ...manifest, handler: "globalThis.__pluginRan=true" },
    { ...manifest, id: "detect" },
    { ...manifest, uses: ["missing"] },
  ]) {
    await ui.preview(invalid);
    await expect(page.getByRole("dialog").getByRole("alert")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "确认安装（默认停用）", exact: true }),
    ).toBeDisabled();
    await page.getByRole("button", { name: "关闭对话框", exact: true }).click();
  }
  expect(await ui.stored()).toBeNull();
  expect(await page.evaluate(() => "__pluginRan" in globalThis)).toBe(false);
});
test("14 dependencies cannot be enabled implicitly, and dependent manifests block deletion even when disabled", async ({
  page,
}) => {
  const ui = new CapabilitiesPage(page);
  await ui.open();
  await ui.install(manifest);
  await ui.install({
    ...manifest,
    id: "my-dependent",
    name: "依赖我的组合",
    uses: ["my-custom"],
  });
  await ui.choose("我的组合能力");
  await page
    .getByRole("button", { name: "删除自定义能力", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("依赖我的组合");
  await expect(
    page.getByRole("button", { name: "确认删除", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await ui.disable("目标检测");
  await page.getByRole("switch", { name: "我的组合能力启用状态" }).click();
  await expect(page.getByRole("alert")).toContainText("请先启用依赖");
  expect((await ui.stored()).states.detect).toBe(false);
  expect((await ui.stored()).states["my-custom"]).toBe(false);
});
test("14 saved-version references prevent custom deletion without touching archive bytes", async ({
  page,
}) => {
  const ui = new CapabilitiesPage(page);
  await ui.open();
  await ui.install(manifest);
  const original = await page.evaluate(async () => {
    // @ts-expect-error Vite browser-only module, never evaluated by Node
    const docs = await import("/src/data/document.ts");
    // @ts-expect-error Vite browser-only module
    const versions = await import("/src/data/versions.ts");
    const doc = {
      ...docs.seedWorkspace().applied,
      capabilityRefs: ["my-custom"],
    };
    const raw = JSON.stringify(
      versions.appendVersion(versions.emptyArchive(doc.id), doc, "自定义引用"),
    );
    localStorage.setItem(versions.versionStorageKey(doc.id), raw);
    return raw;
  });
  await page.reload();
  await ui.ready();
  await ui.choose("我的组合能力");
  await page
    .getByRole("button", { name: "删除自定义能力", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("保存 V1");
  await expect(
    page.getByRole("button", { name: "确认删除", exact: true }),
  ).toBeDisabled();
  expect(
    await page.evaluate(() =>
      localStorage.getItem("vsf-frontend-versions-v1:regional-alert"),
    ),
  ).toBe(original);
});
test("14 unavailable capabilities block editor application and new simulation, reenable restores availability", async ({
  page,
}) => {
  const ui = new CapabilitiesPage(page);
  await ui.open();
  await ui.disable("颜色复核");
  const editor = new WorkspacePage(page);
  await editor.open(false);
  const before = await page.evaluate(() =>
    localStorage.getItem("vsf-frontend-workspace-v1"),
  );
  await page.getByRole("button", { name: "校验并应用", exact: true }).click();
  await expect(
    page.getByRole("dialog", { name: "依赖能力不可用" }),
  ).toContainText("颜色复核");
  expect(
    await page.evaluate(() =>
      localStorage.getItem("vsf-frontend-workspace-v1"),
    ),
  ).toBe(before);
  await page.getByRole("button", { name: "管理能力", exact: true }).click();
  await ui.ready();
  const run = new RunPage(page);
  await run.setup(false);
  await run.start();
  await expect(page.getByRole("alert")).toContainText("颜色复核");
  expect(
    await page.evaluate(
      () => JSON.parse(localStorage.getItem("vsf-frontend-run-v1")!).runs,
    ),
  ).toEqual([]);
  await ui.open();
  await page.getByRole("switch", { name: "颜色复核启用状态" }).click();
  await page.clock.install();
  await run.setup(false);
  await run.start();
  await run.pause();
  expect(
    await page.evaluate(
      () =>
        JSON.parse(localStorage.getItem("vsf-frontend-run-v1")!).runs.length,
    ),
  ).toBe(1);
});
test("14 stopping capability pauses active advancement and resume without cancelling or rewriting its snapshot", async ({
  page,
  context,
}) => {
  await page.clock.install();
  const run = new RunPage(page);
  await run.setup(false);
  await run.start();
  await run.pause();
  const before = await page.evaluate(
    () => JSON.parse(localStorage.getItem("vsf-frontend-run-v1")!).runs[0],
  );
  const other = await context.newPage();
  const ui = new CapabilitiesPage(other);
  await ui.open();
  await ui.disable("目标检测");
  await page
    .getByRole("button", { name: "推进一个采样点", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("目标检测");
  await page.getByRole("button", { name: "继续模拟", exact: true }).click();
  await page.clock.runFor(1200);
  expect(
    await page.evaluate(
      () => JSON.parse(localStorage.getItem("vsf-frontend-run-v1")!).runs[0],
    ),
  ).toEqual(before);
  await other.close();
});
test("14 applying run settings also checks dependencies and keeps applied R3 unchanged", async ({
  page,
}) => {
  const ui = new CapabilitiesPage(page);
  await ui.open();
  await ui.disable("目标检测");
  const run = new RunPage(page);
  await run.setup(false);
  await run.sampling();
  await page.getByLabel("采样间隔（秒）").fill("2");
  await page
    .getByRole("button", { name: "保存运行设置到草稿", exact: true })
    .click();
  await page.getByRole("button", { name: /校验并应用/ }).click();
  await page.getByRole("dialog").getByRole("button", { name: /应用/ }).click();
  await expect(page.getByRole("alert")).toContainText("目标检测");
  expect(
    await page.evaluate(
      () =>
        JSON.parse(localStorage.getItem("vsf-frontend-workspace-v1")!).revision,
    ),
  ).toBe(3);
});
test("14 corrupt and quota-failed writes preserve data and report no false success", async ({
  page,
}) => {
  const ui = new CapabilitiesPage(page);
  await ui.open();
  await page.evaluate(() =>
    localStorage.setItem("vsf-frontend-capabilities-v1", "broken"),
  );
  await page.reload();
  await ui.ready();
  await expect(page.getByRole("alert")).toContainText("不可读取");
  await expect(
    page.getByRole("button", { name: "安装自定义能力", exact: true }),
  ).toBeDisabled();
  expect(
    await page.evaluate(() =>
      localStorage.getItem("vsf-frontend-capabilities-v1"),
    ),
  ).toBe("broken");
  await page.evaluate(() =>
    localStorage.removeItem("vsf-frontend-capabilities-v1"),
  );
  await page.getByRole("button", { name: "重新载入配置", exact: true }).click();
  await ui.preview(manifest);
  await page.evaluate(() => {
    Storage.prototype.setItem = () => {
      throw new DOMException("quota", "QuotaExceededError");
    };
  });
  await page
    .getByRole("button", { name: "确认安装（默认停用）", exact: true })
    .click();
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText(
    "空间不足",
  );
  expect(await ui.stored()).toBeNull();
  await expect(page.getByRole("dialog")).toContainText("我的组合能力");
});
test("14 cross-tab changes preserve pending import and require explicit reload", async ({
  page,
  context,
}) => {
  const ui = new CapabilitiesPage(page);
  await ui.open();
  await ui.preview(manifest);
  const other = await context.newPage();
  const second = new CapabilitiesPage(other);
  await second.open();
  await second.disable("颜色复核");
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText(
    "其它页面",
  );
  await expect(
    page.getByRole("button", { name: "确认安装（默认停用）", exact: true }),
  ).toBeDisabled();
  await expect(page.getByRole("dialog")).toContainText("我的组合能力");
  await page.getByRole("button", { name: "关闭对话框", exact: true }).click();
  await page.getByRole("button", { name: "重新载入配置", exact: true }).click();
  await expect(
    page.getByRole("switch", { name: "颜色复核启用状态" }),
  ).toHaveAttribute("aria-checked", "false");
  await other.close();
});
test("14 damaged dependency audit blocks deletion and disabling without mutating registry", async ({
  page,
}) => {
  const ui = new CapabilitiesPage(page);
  await ui.open();
  await ui.install(manifest);
  const before = await ui.stored();
  await page.evaluate(() =>
    localStorage.setItem("vsf-frontend-versions-v1:regional-alert", "broken"),
  );
  await ui.choose("我的组合能力");
  await page
    .getByRole("button", { name: "删除自定义能力", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "确认删除", exact: true }),
  ).toBeDisabled();
  await expect(page.getByRole("dialog")).toContainText("无法安全检查");
  expect(await ui.stored()).toEqual(before);
});
test("14 editor unsaved navigation saves the actual new condition before opening capabilities", async ({
  page,
}) => {
  const editor = new WorkspacePage(page);
  await editor.open(false);
  await editor.editColor();
  await page.getByLabel("颜色至少占该部位").fill("35");
  await page.getByRole("button", { name: "能力管理", exact: true }).click();
  await page.getByRole("button", { name: "保存后继续", exact: true }).click();
  await new CapabilitiesPage(page).ready();
  const saved = await page.evaluate(() =>
    JSON.parse(localStorage.getItem("vsf-frontend-workspace-v1")!),
  );
  expect(
    saved.draft.conditions.find((c: { id: string }) => c.id === "a-red")
      .minimumFraction,
  ).toBe(0.35);
  expect(saved.revision).toBe(3);
});
test("14 navigation reaches models and preserves their unsaved configuration guard", async ({
  page,
}) => {
  const ui = new CapabilitiesPage(page);
  await ui.open();
  await page.getByRole("button", { name: "模型接入", exact: true }).click();
  await page.getByLabel("显示名称", { exact: true }).fill("尚未保存模型");
  await page.getByRole("button", { name: "能力管理", exact: true }).click();
  await expect(
    page.getByRole("dialog", { name: "有未保存的模型配置" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "放弃修改并继续", exact: true })
    .click();
  await ui.ready();
});
test("14 pending manifest guards browser back and fixture interactions never write normal storage", async ({
  page,
}) => {
  await page.goto("/skills?fixture=01");
  await page.getByRole("button", { name: "能力管理", exact: true }).click();
  const ui = new CapabilitiesPage(page);
  await ui.ready();
  await ui.preview(manifest);
  await expect(
    page.getByRole("button", { name: "确认安装（默认停用）", exact: true }),
  ).toBeEnabled();
  await page.goBack();
  await expect(
    page.getByRole("dialog", { name: "有尚未安装的能力清单" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "返回安装预览", exact: true }).click();
  await page
    .getByRole("button", { name: "确认安装（默认停用）", exact: true })
    .click();
  await ui.disable("颜色复核");
  expect(await ui.stored()).toBeNull();
});
test("14 disabled capabilities do not make archived versions unreadable or change historical content", async ({
  page,
}) => {
  const versions = new VersionsPage(page);
  await versions.open(false);
  await page.getByLabel("版本说明", { exact: true }).fill("停用前归档");
  await page.getByRole("button", { name: "保存新版本", exact: true }).click();
  const before = await page.evaluate(() =>
    localStorage.getItem("vsf-frontend-versions-v1:regional-alert"),
  );
  const ui = new CapabilitiesPage(page);
  await ui.open();
  await ui.disable("颜色复核");
  await versions.open(false);
  await expect(page.getByText("停用前归档", { exact: true })).toBeVisible();
  expect(
    await page.evaluate(() =>
      localStorage.getItem("vsf-frontend-versions-v1:regional-alert"),
    ),
  ).toBe(before);
});
test("14 enabled custom metadata cannot be applied or run merely because its declared dependencies exist", async ({
  page,
}) => {
  const ui = new CapabilitiesPage(page);
  await ui.open();
  await ui.install(manifest);
  await page.getByRole("switch", { name: "我的组合能力启用状态" }).click();
  await page.evaluate(async () => {
    // @ts-expect-error browser Vite module
    const { seedWorkspace } = await import("/src/data/document.ts");
    const data = seedWorkspace();
    data.draft.capabilityRefs = ["my-custom"];
    data.applied.capabilityRefs = ["my-custom"];
    localStorage.setItem("vsf-frontend-workspace-v1", JSON.stringify(data));
  });
  await new WorkspacePage(page).open(false);
  await page.getByRole("button", { name: "校验并应用", exact: true }).click();
  await expect(
    page.getByRole("dialog", { name: "依赖能力不可用" }),
  ).toContainText("执行器未接入");
  const run = new RunPage(page);
  await run.setup(false);
  await run.start();
  await expect(page.getByRole("alert")).toContainText("执行器未接入");
  expect(
    await page.evaluate(
      () => JSON.parse(localStorage.getItem("vsf-frontend-run-v1")!).runs,
    ),
  ).toEqual([]);
});
test("14 automatic advancement also pauses on capability disable in another tab", async ({
  page,
  context,
}) => {
  await page.clock.install({ time: new Date("2026-10-20T08:00:00+08:00") });
  const run = new RunPage(page);
  await run.setup(false);
  // Load lazy React views before freezing timers; no task exists yet.
  const other = await context.newPage();
  const ui = new CapabilitiesPage(other);
  await ui.open();
  await page.clock.pauseAt(new Date("2026-10-20T08:00:10+08:00"));
  await run.start();
  const before = await page.evaluate(() =>
    localStorage.getItem("vsf-frontend-run-v1"),
  );
  await ui.disable("实例去重");
  await page.clock.runFor(1000);
  await expect(page.getByRole("alert")).toContainText("实例去重");
  await expect(
    page.getByRole("button", { name: "继续模拟", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(() => localStorage.getItem("vsf-frontend-run-v1")),
  ).toBe(before);
  await other.close();
});
test("14 version and runtime navigation use their original save guards before opening capabilities", async ({
  page,
}) => {
  const versions = new VersionsPage(page);
  await versions.open(false);
  await page.getByLabel("技能名称", { exact: true }).fill("能力页面前保存");
  await page.getByRole("button", { name: "能力管理", exact: true }).click();
  await page
    .getByRole("button", { name: "保存版本后返回", exact: true })
    .click();
  const ui = new CapabilitiesPage(page);
  await ui.ready();
  expect((await versions.workspace()).draft.name).toBe("能力页面前保存");
  const run = new RunPage(page);
  await run.setup(false);
  await run.sampling();
  await page.getByLabel("采样间隔（秒）").fill("3");
  await page.getByRole("button", { name: "能力管理", exact: true }).click();
  await page.getByRole("button", { name: /保存.*继续/ }).click();
  await ui.ready();
  const saved = await versions.workspace();
  expect(saved.draft.runSettings.sampleIntervalSeconds).toBe(3);
  expect(saved.applied.runSettings.sampleIntervalSeconds).toBe(1);
  expect(saved.revision).toBe(3);
});
for (const viewport of [
  { width: 1366, height: 768 },
  { width: 760, height: 900 },
])
  test(`14 controls remain usable at ${viewport.width}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const ui = new CapabilitiesPage(page);
    await ui.open(true);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await expect(
      page.getByRole("button", { name: "安装自定义能力", exact: true }),
    ).toBeInViewport();
    await page
      .getByText("内置能力不可删除；可启用或停用。", { exact: true })
      .scrollIntoViewIfNeeded();
    await expect(
      page.getByText("内置能力不可删除；可启用或停用。", { exact: true }),
    ).toBeInViewport();
    await page.getByRole("tab", { name: "组合模板", exact: true }).click();
    await ui.choose("自定义区域巡检");
    await page
      .getByRole("button", { name: "删除自定义能力", exact: true })
      .click();
    await page.getByRole("button", { name: "确认删除", exact: true }).click();
    expect(await ui.stored()).toBeNull();
  });

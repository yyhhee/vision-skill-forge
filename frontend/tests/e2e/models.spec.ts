import { test, expect } from "@playwright/test";
import { testOrigin } from "../testOrigin";
import { ModelsPage } from "./ModelsPage";
import { LibraryPage } from "./LibraryPage";
import { WorkspacePage } from "./WorkspacePage";
import { VersionsPage } from "./VersionsPage";
import { RunPage } from "./RunPage";
test.beforeEach(async ({ context }) => {
  await context.route("**/*", (r) =>
    new URL(r.request().url()).origin === testOrigin
      ? r.continue()
      : r.abort(),
  );
});
test("13 library entry, model purpose tabs and credential prohibition work without writes", async ({
  page,
}) => {
  const lib = new LibraryPage(page);
  await lib.open();
  await page.getByRole("button", { name: "模型接入", exact: true }).click();
  const ui = new ModelsPage(page);
  await ui.ready();
  await expect(
    page.getByRole("tab", { name: "视觉模型", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await expect(page.getByLabel("访问凭证（当前不可用）")).toBeDisabled();
  expect(await ui.stored()).toBeNull();
  await page.getByRole("tab", { name: "编排模型", exact: true }).click();
  await expect(page.getByLabel("坐标", { exact: true })).toHaveCount(0);
  await expect(
    page.getByLabel("结构化草稿输出", { exact: true }),
  ).toBeChecked();
  await expect(page.getByLabel("输出规范", { exact: true })).toHaveValue(
    "business_draft",
  );
  expect(await ui.storage()).toEqual({});
});
test("13 add, save, enable, choose and refresh preserve one independent disconnected configuration", async ({
  page,
}) => {
  const ui = new ModelsPage(page);
  await ui.open();
  await page.getByRole("button", { name: "添加模型", exact: true }).click();
  await ui.fill();
  await ui.save();
  await expect(page.getByRole("status")).toContainText("未连接模型");
  let store = await ui.stored();
  expect(store.models).toHaveLength(5);
  expect(store.selected).toEqual({});
  await ui.menu("我的检测模型");
  await page.getByRole("button", { name: "启用配置", exact: true }).click();
  await ui.menu("我的检测模型");
  await page
    .getByRole("button", { name: "选为待接入模型", exact: true })
    .click();
  store = await ui.stored();
  expect(store.selected.vision).toBe(
    store.models.find((m: { name: string }) => m.name === "我的检测模型").id,
  );
  await page.reload();
  await ui.ready();
  await expect(
    page.getByRole("row").filter({ hasText: "我的检测模型" }),
  ).toContainText("已选择 · 未连接");
  expect((await ui.storage())["vsf-frontend-workspace-v1"]).toBeUndefined();
  expect(JSON.stringify(await ui.stored())).not.toContain("credential");
});
test("13 local checks never contact the user URL or claim connection success", async ({
  page,
}) => {
  const remote: string[] = [];
  page.on("request", (r) => {
    if (new URL(r.url()).origin !== testOrigin)
      remote.push(r.url());
  });
  const ui = new ModelsPage(page);
  await ui.open();
  await ui.fill();
  await page.getByRole("button", { name: "检查配置", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("连接未验证");
  expect(remote).toEqual([]);
  expect(await ui.stored()).toBeNull();
  await page
    .getByLabel("服务地址", { exact: true })
    .fill("https://name:secret@example.com/api?token=never");
  await ui.save();
  await expect(page.getByRole("alert")).toContainText("不得包含");
  expect(await ui.storage()).toEqual({});
});
test("13 pending saved edits are used by the subsequent enable action instead of stale state", async ({
  page,
}) => {
  const ui = new ModelsPage(page);
  await ui.open();
  await ui.fill("改名前");
  await ui.save();
  await page.getByLabel("显示名称", { exact: true }).fill("已保存的新名称");
  await ui.menu("改名前");
  await page.getByRole("button", { name: "启用配置", exact: true }).click();
  await page.getByRole("button", { name: "保存并继续", exact: true }).click();
  const item = (await ui.stored()).models.find(
    (m: { id: string }) => m.id === "visual-demo",
  );
  expect(item.name).toBe("已保存的新名称");
  expect(item.enabled).toBe(true);
  await expect(page.getByLabel("显示名称", { exact: true })).toHaveValue(
    "已保存的新名称",
  );
});
test("13 same-row configure after save keeps the newly saved form instead of the previous label", async ({
  page,
}) => {
  const ui = new ModelsPage(page);
  await ui.open();
  await ui.fill("原名称");
  await ui.save();
  await page.getByLabel("显示名称", { exact: true }).fill("新名称");
  await ui.configure("原名称");
  await page.getByRole("button", { name: "保存并继续", exact: true }).click();
  await expect(page.getByLabel("显示名称", { exact: true })).toHaveValue(
    "新名称",
  );
});
test("13 disabling the selected config requires confirmation and never auto-selects another model", async ({
  page,
}) => {
  const ui = new ModelsPage(page);
  await ui.open(true);
  await ui.menu("Rex-Omni");
  await page.getByRole("button", { name: "停用配置", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("不会自动选择其它模型");
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await expect(
    page.getByRole("row").filter({ hasText: "Rex-Omni" }),
  ).toContainText("已选择");
  await ui.menu("Rex-Omni");
  await page.getByRole("button", { name: "停用配置", exact: true }).click();
  await page
    .getByRole("button", { name: "停用并取消选择", exact: true })
    .click();
  await expect(
    page.getByRole("row").filter({ hasText: "Rex-Omni" }),
  ).toContainText("未启用");
  expect(await ui.storage()).toEqual({});
});
test("13 mappings are controlled declarations, can be disabled, and cannot contain executable expressions", async ({
  page,
}) => {
  const ui = new ModelsPage(page);
  await ui.open();
  await ui.fill();
  await page.getByText("可选映射配置", { exact: true }).click();
  await page.getByLabel("自定义响应字段", { exact: true }).check();
  await page.getByLabel("目标框字段", { exact: true }).fill("boxes[0]");
  await ui.save();
  await expect(page.getByRole("alert")).toContainText("不接受表达式");
  await page.getByLabel("目标框字段", { exact: true }).fill("data.boxes");
  await ui.save();
  expect(
    (await ui.stored()).models.find(
      (m: { id: string }) => m.id === "visual-demo",
    ).mapping.boxes,
  ).toBe("data.boxes");
  await page.getByLabel("自定义响应字段", { exact: true }).uncheck();
  await ui.save();
  expect(
    (await ui.stored()).models.find(
      (m: { id: string }) => m.id === "visual-demo",
    ).mapping,
  ).toBeUndefined();
});
test("13 dirty form is protected when switching tabs, sidebar and browser history", async ({
  page,
}) => {
  await new LibraryPage(page).open();
  await page.getByRole("button", { name: "模型接入", exact: true }).click();
  const ui = new ModelsPage(page);
  await ui.ready();
  await ui.fill();
  await page.getByRole("tab", { name: "编排模型", exact: true }).click();
  await page.getByRole("button", { name: "继续编辑", exact: true }).click();
  await expect(page.getByLabel("显示名称", { exact: true })).toHaveValue(
    "我的检测模型",
  );
  await page.goBack();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "保存并继续", exact: true }).click();
  await new LibraryPage(page).ready();
  expect(
    (await ui.stored()).models.find(
      (m: { id: string }) => m.id === "visual-demo",
    ).name,
  ).toBe("我的检测模型");
});
test("13 corrupted cache and quota failure preserve original bytes and the unsaved form", async ({
  page,
}) => {
  const ui = new ModelsPage(page);
  await ui.open();
  await ui.fill();
  await page.evaluate(() => {
    Storage.prototype.setItem = () => {
      throw Error("quota");
    };
  });
  await ui.save();
  await expect(page.getByRole("alert")).toContainText("未保存");
  await expect(page.getByLabel("显示名称", { exact: true })).toHaveValue(
    "我的检测模型",
  );
  expect(await ui.stored()).toBeNull();
  await page.reload();
  await ui.ready();
  await page.evaluate(() =>
    localStorage.setItem("vsf-frontend-models-v1", "broken"),
  );
  await page.reload();
  await ui.ready();
  await expect(page.getByRole("alert")).toContainText("原内容未覆盖");
  await expect(
    page.getByRole("button", { name: "添加模型", exact: true }),
  ).toBeDisabled();
  expect((await ui.storage())["vsf-frontend-models-v1"]).toBe("broken");
  await page.getByRole("tab", { name: "编排模型", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("原内容未覆盖");
});
test("13 another tab cannot silently replace dirty edits; reload is explicit", async ({
  page,
  context,
}) => {
  const ui = new ModelsPage(page);
  await ui.open();
  await ui.fill("本页修改");
  const other = await context.newPage();
  const second = new ModelsPage(other);
  await second.open();
  await second.fill("其它页面");
  await second.save();
  await expect(page.getByRole("alert")).toContainText("其它页面修改");
  await expect(page.getByLabel("显示名称", { exact: true })).toHaveValue(
    "本页修改",
  );
  await expect(
    page.getByRole("button", { name: "保存配置", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "重新载入配置", exact: true }).click();
  await page
    .getByRole("button", { name: "放弃修改并继续", exact: true })
    .click();
  await expect(page.getByLabel("显示名称", { exact: true })).toHaveValue(
    "其它页面",
  );
  await other.close();
});
test("13 navigation from editor preserves saved conditions and applied R3", async ({
  page,
}) => {
  const editor = new WorkspacePage(page);
  await editor.open(false);
  await editor.editColor();
  await page.getByLabel("颜色至少占该部位").fill("35");
  await page.getByRole("button", { name: "模型接入", exact: true }).click();
  await page.getByRole("button", { name: "保存后继续", exact: true }).click();
  await new ModelsPage(page).ready();
  const workspace = await page.evaluate(() =>
    JSON.parse(localStorage.getItem("vsf-frontend-workspace-v1")!),
  );
  expect(workspace.revision).toBe(3);
  expect(
    workspace.draft.conditions.find((c: { id: string }) => c.id === "a-red")
      .minimumFraction,
  ).toBe(0.35);
  expect(
    workspace.applied.conditions.find((c: { id: string }) => c.id === "a-red")
      .minimumFraction,
  ).toBe(0.2);
});
test("13 opening settings from version metadata saves the new document before navigation, not the old closure", async ({
  page,
}) => {
  const versions = new VersionsPage(page);
  await versions.open(false);
  await page.getByLabel("技能名称", { exact: true }).fill("模型页面跳转前保存");
  await page.getByRole("button", { name: "模型接入", exact: true }).click();
  await page
    .getByRole("button", { name: "保存版本后返回", exact: true })
    .click();
  await new ModelsPage(page).ready();
  const saved = await versions.workspace();
  expect(saved.draft.name).toBe("模型页面跳转前保存");
  expect(saved.applied.name).toBe("区域联合告警");
  expect(saved.revision).toBe(3);
});
test("13 opening settings from pending runtime setup preserves new settings in draft without applying", async ({
  page,
}) => {
  const run = new RunPage(page);
  await run.setup(false);
  await run.sampling();
  await page.getByLabel("采样间隔（秒）").fill("3");
  await page.getByRole("button", { name: "模型接入", exact: true }).click();
  await page.getByRole("button", { name: /保存.*继续/ }).click();
  const ui = new ModelsPage(page);
  await ui.ready();
  const saved = JSON.parse((await ui.storage())["vsf-frontend-workspace-v1"]!);
  expect(saved.draft.runSettings.sampleIntervalSeconds).toBe(3);
  expect(saved.applied.runSettings.sampleIntervalSeconds).toBe(1);
  expect(saved.revision).toBe(3);
});
for (const viewport of [
  { width: 1366, height: 768 },
  { width: 760, height: 900 },
])
  test(`13 settings remain editable at ${viewport.width}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const ui = new ModelsPage(page);
    await ui.open(true);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await expect(
      page.getByRole("button", { name: "添加模型", exact: true }),
    ).toBeInViewport();
    await page.getByLabel("显示名称", { exact: true }).fill("窄屏模型");
    await ui.save();
    await expect(page.getByRole("status")).toContainText("保存");
    const panel = await page
      .getByRole("region", { name: "模型配置", exact: true })
      .boundingBox();
    const save = await page
      .getByRole("button", { name: "保存配置", exact: true })
      .boundingBox();
    expect(
      panel && save && panel.y + panel.height >= save.y + save.height,
    ).toBe(true);
    expect(await ui.storage()).toEqual({});
  });

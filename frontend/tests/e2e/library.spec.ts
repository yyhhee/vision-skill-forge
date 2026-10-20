import { test, expect } from "@playwright/test";
import { testOrigin } from "../testOrigin";
import { LibraryPage } from "./LibraryPage";
import { WorkspacePage } from "./WorkspacePage";
import { VersionsPage } from "./VersionsPage";
import { RunPage } from "./RunPage";
import { readFileSync } from "node:fs";
const seed = JSON.parse(
  readFileSync(
    new URL("../../src/fixtures/mock-fixtures.json", import.meta.url),
    "utf8",
  ),
);
const RUN_STORAGE_KEY = "vsf-frontend-run-v1";

test.beforeEach(async ({ context }) => {
  await context.route("**/*", (r) =>
    new URL(r.request().url()).origin === testOrigin
      ? r.continue()
      : r.abort(),
  );
});
const file = (id = "inspection-import") => {
  const doc = structuredClone(seed.documents["regional-draft"]);
  doc.groups = [
    {
      id: "inner",
      name: "内层组",
      operator: "AND",
      members: ["branch-a", "branch-b"],
    },
    { id: "outer", name: "外层组", operator: "AND", members: ["inner"] },
  ];
  doc.final.members = ["outer"];
  doc.id = id;
  doc.name = "导入的完整技能";
  return { format: "vsf-skill-document", schemaVersion: 1, document: doc };
};
test("01 fixture shows five real-state entries, filtering and layout toggle without normal writes", async ({
  page,
}, info) => {
  const ui = new LibraryPage(page);
  await ui.open(true);
  await expect(page.getByRole("article")).toHaveCount(5);
  await expect(ui.entry("区域联合告警")).toContainText("草稿有修改");
  await expect(ui.entry("桥梁病害")).toContainText("示例说明");
  await page.screenshot({ path: info.outputPath("01-library.png") });
  await page.getByRole("tab", { name: "预置示例", exact: true }).click();
  await expect(page.getByRole("article")).toHaveCount(4);
  await page.getByLabel("搜索技能名称或描述").fill("桥梁");
  await expect(page.getByRole("article")).toHaveCount(1);
  await page.getByRole("button", { name: "卡片视图", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "卡片视图", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  expect(await ui.storage()).toEqual({});
});
test("unknown skills and unimplemented page addresses never substitute a regional workspace", async ({
  page,
}) => {
  const ui = new LibraryPage(page);
  for (const path of [
    "/skills/not-installed/editor",
    "/settings/not-a-page",
    "/runs",
  ]) {
    await page.goto(path);
    await expect(
      page.getByRole("button", { name: "返回技能库", exact: true }),
    ).toBeVisible();
    await expect(page.getByTestId("workspace-panels")).toHaveCount(0);
    expect(await ui.storage()).toEqual({});
  }
});
test("template creation, nested editing and library re-open share a complete independent document", async ({
  page,
}) => {
  const ui = new LibraryPage(page);
  await ui.open();
  await ui.create("我的顺序流程");
  const id = new URL(page.url()).pathname.split("/")[2];
  await page.getByRole("button", { name: "更多操作", exact: true }).click();
  await page.getByRole("button", { name: "编排组", exact: true }).click();
  await page.getByRole("button", { name: "先A后B", exact: true }).click();
  await page.getByLabel("最长间隔（秒）", { exact: true }).fill("18");
  await page.getByRole("button", { name: "保存到草稿", exact: true }).click();
  await ui.backToLibrary();
  await expect(ui.entry("我的顺序流程")).toContainText("尚未应用");
  await ui
    .entry("我的顺序流程")
    .getByRole("button", { name: "继续编辑", exact: true })
    .click();
  const stored = await page.evaluate(
    (id) => JSON.parse(localStorage.getItem(`vsf-frontend-skill-v1:${id}`)!),
    id,
  );
  expect(stored.draft.groups[0].transition.maxGapSeconds).toBe(18);
  expect(stored.draft.groups[1].members).toEqual(["group-ab", "seq-c"]);
  expect(stored.revision).toBe(0);
  await page.reload();
  await expect(page.getByTestId("revision-status")).toContainText("尚未应用");
});
test("save-before-leaving to library persists the newly saved form rather than stale draft", async ({
  page,
}) => {
  const editor = new WorkspacePage(page),
    ui = new LibraryPage(page);
  await editor.open(false);
  await page.getByRole("button", { name: "人数 ≥ 2", exact: true }).click();
  await page.getByLabel("至少有多少人", { exact: true }).fill("7");
  await page.getByRole("button", { name: "技能库", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: /保存.*继续/ }).click();
  await ui.ready();
  await ui
    .entry("区域联合告警")
    .getByRole("button", { name: "继续编辑", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "人数 ≥ 7", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        JSON.parse(localStorage.getItem("vsf-frontend-workspace-v1")!).applied
          .conditions[4].value,
    ),
  ).toBe(2);
});
test("import preserves full structure, conflicts require explicit independent copy and cancel changes nothing", async ({
  page,
}) => {
  const ui = new LibraryPage(page);
  await ui.open();
  const payload = file();
  await ui.import(payload);
  await expect(page.getByRole("status")).toContainText("尚未应用");
  const before = await ui.storage();
  await ui.import(payload);
  await expect(
    page.getByRole("dialog", { name: "该技能已存在" }),
  ).toBeVisible();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "取消", exact: true })
    .click();
  expect(await ui.storage()).toEqual(before);
  await ui.import(payload);
  await page
    .getByRole("button", { name: "另存为独立副本", exact: true })
    .click();
  await expect(ui.entry("导入的完整技能（导入副本）")).toBeVisible();
  await ui
    .entry("导入的完整技能")
    .getByRole("button", { name: "继续编辑", exact: true })
    .click();
  const versions = new VersionsPage(page);
  await versions.fromEditor();
  const contents = await versions.contents(await versions.export(1));
  expect(contents.version.document).toEqual(payload.document);
});
test("malformed imports and quota failure do not leave partial workspaces or versions", async ({
  page,
}) => {
  const ui = new LibraryPage(page);
  await ui.open();
  const before = await ui.storage();
  for (const value of [
    "bad-json",
    JSON.stringify({ ...file(), schemaVersion: 99 }),
    JSON.stringify({ ...file(), apiKey: "never-real" }),
  ]) {
    await ui.import(value, true);
    await expect(page.getByRole("alert")).toBeVisible();
    expect(await ui.storage()).toEqual(before);
  }
  await page.evaluate(() => {
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key === "vsf-frontend-skill-v1:inspection-import")
        throw new DOMException("quota", "QuotaExceededError");
      original.call(this, key, value);
    };
  });
  await ui.import(file());
  await expect(page.getByRole("alert")).toContainText("未保存");
  expect(await ui.storage()).toEqual(before);
});
test("browser back protects unsaved conditions and forward reopens the saved complete document", async ({
  page,
}) => {
  const ui = new LibraryPage(page);
  await ui.open();
  await ui
    .entry("区域联合告警")
    .getByRole("button", { name: "继续编辑", exact: true })
    .click();
  await page.getByRole("button", { name: "人数 ≥ 2", exact: true }).click();
  await page.getByLabel("至少有多少人", { exact: true }).fill("6");
  await page.evaluate(() => history.back());
  await expect(
    page.getByRole("dialog", { name: "当前表单尚未保存" }),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/editor/);
  await page.getByRole("button", { name: "继续编辑", exact: true }).click();
  await expect(page.getByLabel("至少有多少人", { exact: true })).toHaveValue(
    "6",
  );
  await page.evaluate(() => history.back());
  await expect(page).toHaveURL(/\/editor/);
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "保存后继续", exact: true })
    .click();
  await ui.ready();
  await page.evaluate(() => history.forward());
  await expect(
    page.getByRole("button", { name: "人数 ≥ 6", exact: true }),
  ).toBeVisible();
  expect(
    JSON.parse((await ui.storage())["vsf-frontend-workspace-v1"]!).revision,
  ).toBe(3);
});
test("browser back from unsaved version metadata uses the same save guard as page navigation", async ({
  page,
}) => {
  const ui = new LibraryPage(page),
    versions = new VersionsPage(page);
  await ui.open();
  await ui
    .entry("区域联合告警")
    .getByRole("button", { name: "继续编辑", exact: true })
    .click();
  await versions.fromEditor();
  await page.getByLabel("技能名称", { exact: true }).fill("浏览器返回保存");
  await page.evaluate(() => history.back());
  await expect(
    page.getByRole("dialog", { name: "版本说明尚未保存" }),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/versions/);
  await page
    .getByRole("button", { name: "保存版本后返回", exact: true })
    .click();
  await ui.ready();
  await expect(ui.entry("浏览器返回保存")).toBeVisible();
});
test("version metadata save before returning to library persists the new name and keeps R3", async ({
  page,
}) => {
  const editor = new WorkspacePage(page),
    versions = new VersionsPage(page),
    ui = new LibraryPage(page);
  await editor.open(false);
  await versions.fromEditor();
  await page.getByLabel("技能名称", { exact: true }).fill("已保存的新名称");
  await page.getByRole("button", { name: "技能库", exact: true }).click();
  await page
    .getByRole("button", { name: "保存版本后返回", exact: true })
    .click();
  await ui.ready();
  await expect(ui.entry("已保存的新名称")).toBeVisible();
  const saved = await versions.workspace();
  expect(saved.draft.name).toBe("已保存的新名称");
  expect(saved.applied.name).toBe("区域联合告警");
  expect(saved.revision).toBe(3);
});
test("runtime navigation to library guards discard and save without applying settings", async ({
  page,
}) => {
  const run = new RunPage(page),
    ui = new LibraryPage(page);
  await run.setup(false);
  await run.sampling();
  await page.getByLabel("采样间隔（秒）").fill("2");
  await page.getByRole("button", { name: "技能库", exact: true }).click();
  await expect(
    page.getByRole("dialog", { name: "运行设置尚未保存" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "放弃修改", exact: true }).click();
  await ui.ready();
  expect(
    JSON.parse((await ui.storage())["vsf-frontend-workspace-v1"]!).draft
      .runSettings.sampleIntervalSeconds,
  ).toBe(1);
  await run.setup(false);
  await run.sampling();
  await page.getByLabel("采样间隔（秒）").fill("3");
  await page.getByRole("button", { name: "技能库", exact: true }).click();
  await page.getByRole("button", { name: /保存.*继续/ }).click();
  await ui.ready();
  const data = JSON.parse((await ui.storage())["vsf-frontend-workspace-v1"]!);
  expect(data.draft.runSettings.sampleIntervalSeconds).toBe(3);
  expect(data.applied.runSettings.sampleIntervalSeconds).toBe(1);
});
test("unknown media remains exportable but never opens the unrelated construction poster", async ({
  page,
}) => {
  const ui = new LibraryPage(page);
  await ui.open();
  const payload = file();
  payload.document.mediaRef = "my-furniture-photo";
  await ui.import(payload);
  await expect(page.getByRole("status")).toBeVisible();
  await ui
    .entry(payload.document.name)
    .getByRole("button", { name: "继续编辑", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("素材尚未接入");
  await expect(page.getByTestId("workspace-panels")).toHaveCount(0);
});
test("delete confirmation preserves other skills and historic runs; deleted links never resurrect data", async ({
  page,
  context,
}) => {
  const ui = new LibraryPage(page);
  await ui.open();
  await ui.import(file());
  const run = await page.evaluate(async () => {
    const path = "/src/data/runs.ts";
    return (await import(path)).exampleRun(true);
  });
  run.id = "historic-import";
  run.snapshot = file().document;
  run.resultAvailability = "not_provided";
  run.events = [];
  await page.evaluate(
    ({ key, run }) =>
      localStorage.setItem(
        key,
        JSON.stringify({ schemaVersion: 1, runs: [run] }),
      ),
    { key: RUN_STORAGE_KEY, run },
  );
  const before = await ui.storage();
  await ui.menu("导入的完整技能");
  await page.getByRole("button", { name: "删除本地技能", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "取消", exact: true })
    .click();
  expect(await ui.storage()).toEqual(before);
  const stale = await context.newPage();
  await stale.goto("/skills/inspection-import/editor");
  await expect(stale.getByTestId("workspace-panels")).toBeVisible();
  await ui.menu("导入的完整技能");
  await page.getByRole("button", { name: "删除本地技能", exact: true }).click();
  await page
    .getByRole("button", { name: "确认删除本地技能", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("历史运行记录未改变");
  await expect(stale.getByRole("alert")).toContainText("已删除");
  await stale.close();
  expect((await ui.storage())[RUN_STORAGE_KEY]).toBe(before[RUN_STORAGE_KEY]);
  await page.goto("/skills/inspection-import/editor");
  await expect(page.getByRole("alert")).toContainText("已删除");
  await page.goto("/runs/historic-import");
  await expect(page.getByRole("heading", { name: /验证结果/ })).toBeVisible();
  expect(
    (await ui.storage())["vsf-frontend-skill-v1:inspection-import"],
  ).toBeUndefined();
  await ui.open();
  await ui.import(file());
  await expect(
    page.getByRole("dialog", { name: "该技能身份已删除" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "另存为独立副本", exact: true })
    .click();
  await expect(ui.entry("导入的完整技能（导入副本）")).toBeVisible();
  expect((await ui.storage())[RUN_STORAGE_KEY]).toBe(before[RUN_STORAGE_KEY]);
});
test("active tasks block deleting a skill and corrupted directory bytes are preserved", async ({
  page,
}) => {
  const ui = new LibraryPage(page);
  await ui.open();
  await ui.import(file());
  const run = await page.evaluate(async () => {
    const path = "/src/data/runs.ts";
    return (await import(path)).exampleRun(false);
  });
  run.snapshot = file().document;
  run.resultAvailability = "not_provided";
  run.events = [];
  await page.evaluate(
    ({ key, run }) =>
      localStorage.setItem(
        key,
        JSON.stringify({ schemaVersion: 1, runs: [run] }),
      ),
    { key: RUN_STORAGE_KEY, run },
  );
  await ui.menu("导入的完整技能");
  await page.getByRole("button", { name: "删除本地技能", exact: true }).click();
  await page
    .getByRole("button", { name: "确认删除本地技能", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("未结束任务");
  expect(
    (await ui.storage())["vsf-frontend-skill-v1:inspection-import"],
  ).toBeDefined();
  await page.evaluate(() =>
    localStorage.setItem("vsf-frontend-library-v1", "broken"),
  );
  await page.reload();
  await ui.ready();
  await expect(page.getByRole("alert")).toContainText("原内容未覆盖");
  expect((await ui.storage())["vsf-frontend-library-v1"]).toBe("broken");
});
for (const viewport of [
  { width: 1366, height: 768 },
  { width: 760, height: 900 },
])
  test(`library remains operable at ${viewport.width}x${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    const ui = new LibraryPage(page);
    await ui.open();
    if (viewport.width >= 1150)
      await page
        .getByRole("button", { name: "关闭技能详情", exact: true })
        .click();
    await expect(
      page.getByRole("button", { name: "新建技能", exact: true }),
    ).toBeInViewport();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.getByLabel("搜索技能名称或描述").fill("no-matching-skill");
    await expect(
      page.getByRole("heading", { name: "没有匹配的技能" }),
    ).toBeVisible();
  });

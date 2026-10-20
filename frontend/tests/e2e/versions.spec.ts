import { expect, test } from "@playwright/test";
import { testOrigin } from "../testOrigin";
import { VersionsPage, archiveKey } from "./VersionsPage";
import { WorkspacePage } from "./WorkspacePage";
import { RunPage } from "./RunPage";

test.beforeEach(async ({ context }) => {
  await context.route("**/*", (r) =>
    new URL(r.request().url()).origin === testOrigin
      ? r.continue()
      : r.abort(),
  );
});

test("12 fixture displays complete V3 and proposes V4 without touching normal storage", async ({
  page,
}, testInfo) => {
  const ui = new VersionsPage(page);
  await ui.open(true);
  await expect(
    page.getByRole("button", { name: "查看 V3", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByRole("button", { name: "保存为 V4", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "保存为 V4", exact: true }),
  ).toBeInViewport();
  expect(
    await page
      .locator(".versions-grid")
      .evaluate((n) => getComputedStyle(n).display),
  ).toBe("grid");
  await expect(page.getByLabel("所选版本内容摘要")).toContainText("无额外等待");
  await page.screenshot({ path: testInfo.outputPath("12-version-page.png") });
  await ui.save("隔离保存");
  expect(
    await page.evaluate(() =>
      localStorage.getItem("vsf-frontend-workspace-v1"),
    ),
  ).toBeNull();
  expect(
    await page.evaluate((k) => localStorage.getItem(k), archiveKey),
  ).toBeNull();
});

test("save, edit, cancel load and backup-before-load preserve complete versions and applied R3", async ({
  page,
}) => {
  const editor = new WorkspacePage(page),
    ui = new VersionsPage(page);
  await editor.open(false);
  await ui.fromEditor();
  const original = await ui.workspace();
  await ui.save("第一份完整草稿");
  await ui.back();
  await page.getByRole("button", { name: "人数 ≥ 2", exact: true }).click();
  await page.getByLabel("至少有多少人", { exact: true }).fill("4");
  await editor.save();
  await ui.fromEditor();
  await ui.load(1);
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "取消", exact: true })
    .click();
  expect((await ui.workspace()).draft.conditions[4].value).toBe(4);
  await ui.load(1);
  await page
    .getByRole("button", { name: "先保存当前草稿再加载", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("已加载 V1 到草稿");
  const after = await ui.workspace(),
    archive = await ui.archive();
  expect(after.draft).toEqual(original.draft);
  expect(after.applied).toEqual(original.applied);
  expect(after.revision).toBe(3);
  expect(archive.versions).toHaveLength(2);
  expect(archive.versions[1].document.conditions[4].value).toBe(4);
  await page.reload();
  await page.getByRole("button", { name: "人数 ≥ 2", exact: true }).click();
  await expect(page.getByLabel("至少有多少人", { exact: true })).toHaveValue(
    "2",
  );
});

test("nested sequence round trips through export and empty storage, and remains editable", async ({
  page,
}) => {
  const ui = new VersionsPage(page);
  await page.goto(
    "/skills/sequence-demo/editor?view=orchestration&drawer=group",
  );
  await page.getByRole("button", { name: "下移步骤1", exact: true }).click();
  await page.getByLabel("最长间隔（秒）", { exact: true }).fill("15");
  await page.getByRole("button", { name: "保存到草稿", exact: true }).click();
  const before = await ui.workspace("vsf-frontend-sequence-v1");
  await ui.fromEditor();
  await ui.save("嵌套组完整往返");
  const file = await ui.contents(await ui.export(1));
  expect(file.version.document).toEqual(before.draft);
  await page.evaluate(() => localStorage.clear());
  await ui.open(false, "sequence-demo");
  await expect(
    page.getByText("还没有保存的版本", { exact: true }),
  ).toBeVisible();
  await ui.importPayload(file);
  await expect(page.getByRole("status")).toContainText("尚未加载或应用");
  await ui.load(1);
  await page
    .getByRole("button", { name: "替换草稿并加载", exact: true })
    .click();
  const restored = await ui.workspace("vsf-frontend-sequence-v1");
  expect(restored.draft).toEqual(before.draft);
  expect(restored.revision).toBe(0);
  await page.getByRole("button", { name: "更多操作", exact: true }).click();
  await page.getByRole("button", { name: "编排组", exact: true }).click();
  await page.getByRole("button", { name: "先A后B", exact: true }).click();
  await expect(page.getByLabel("最长间隔（秒）", { exact: true })).toHaveValue(
    "15",
  );
});

test("invalid JSON, schema, credentials and references cannot replace current draft or versions", async ({
  page,
}) => {
  const ui = new VersionsPage(page);
  await ui.open();
  await ui.save();
  const before = await ui.workspace(),
    archive = await ui.archive();
  const payload = {
    format: "vsf-skill-document",
    schemaVersion: 1,
    document: before.draft,
  };
  for (const value of [
    "{bad-json",
    JSON.stringify({ ...payload, schemaVersion: 999 }),
    JSON.stringify({
      ...payload,
      document: { ...before.draft, conditions: null },
    }),
    JSON.stringify({ ...payload, apiKey: "not-a-real-key" }),
    JSON.stringify({
      ...payload,
      document: {
        ...before.draft,
        outputs: [{ ...before.draft.outputs[0], source: "missing" }],
      },
    }),
  ]) {
    await ui.importPayload(value, true);
    await expect(page.getByRole("alert")).toBeVisible();
    expect(await ui.workspace()).toEqual(before);
    expect(await ui.archive()).toEqual(archive);
  }
});

test("pending evidence review is archived and loaded without being automatically confirmed", async ({
  page,
}) => {
  const ui = new VersionsPage(page),
    editor = new WorkspacePage(page);
  await editor.open(false);
  await editor.editColor();
  await page.getByLabel("判断部位", { exact: true }).selectOption("lower");
  await editor.save();
  const before = await ui.workspace();
  await ui.fromEditor();
  await ui.save("仍需核对");
  await ui.load(1);
  await page
    .getByRole("button", { name: "替换草稿并加载", exact: true })
    .click();
  expect((await ui.workspace()).draft.conditions[1].semanticBinding).toEqual(
    before.draft.conditions[1].semanticBinding,
  );
  await page.getByRole("button", { name: "校验并应用", exact: true }).click();
  await expect(page.getByLabel("待处理问题", { exact: true })).toContainText(
    "语义证据待核对",
  );
  expect((await ui.workspace()).revision).toBe(3);
});

test("returning from versions preserves scene editing context", async ({
  page,
}) => {
  const ui = new VersionsPage(page);
  await page.goto("/skills/regional-alert/editor?view=scene");
  await expect(page.getByTestId("scene-media")).toBeVisible();
  await ui.fromEditor();
  await ui.back();
  await expect(page).toHaveURL(/view=scene/);
  await expect(page.getByTestId("scene-media")).toBeVisible();
});

test("unavailable media is staged but never replaced with the current poster", async ({
  page,
}) => {
  const ui = new VersionsPage(page);
  await ui.open();
  const before = await ui.workspace();
  await ui.importPayload({
    format: "vsf-skill-document",
    schemaVersion: 1,
    document: { ...before.draft, mediaRef: "missing-media" },
  });
  await expect(page.getByRole("status")).toContainText("尚未加载或应用");
  await ui.load(1);
  await page
    .getByRole("button", { name: "替换草稿并加载", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("素材引用与当前环境不同");
  expect(await ui.workspace()).toEqual(before);
  expect((await ui.archive()).versions).toHaveLength(1);
});

test("old workspace import and duplicate version import never restore an applied snapshot", async ({
  page,
}) => {
  const ui = new VersionsPage(page);
  await ui.open();
  const before = await ui.workspace();
  await ui.importPayload({
    format: "vsf-frontend-demo",
    schemaVersion: 1,
    ...before,
    revision: 999,
  });
  const file = await ui.contents(await ui.export(1));
  await ui.importPayload(file);
  await expect(page.getByRole("status")).toContainText("已存在");
  expect((await ui.archive()).versions).toHaveLength(1);
  expect(await ui.workspace()).toEqual(before);
});

test("loading a version cannot rewrite active or historic run snapshots", async ({
  page,
}) => {
  await page.clock.install();
  const run = new RunPage(page),
    ui = new VersionsPage(page);
  await run.setup(false);
  await run.start();
  await run.pause();
  const runsBefore = await page.evaluate(() =>
    localStorage.getItem("vsf-frontend-run-v1"),
  );
  await page.getByRole("button", { name: "返回规则", exact: true }).click();
  await page.getByRole("button", { name: "编辑当前草稿", exact: true }).click();
  await ui.fromEditor();
  await ui.save();
  await ui.load(1);
  await page
    .getByRole("button", { name: "替换草稿并加载", exact: true })
    .click();
  expect(
    await page.evaluate(() => localStorage.getItem("vsf-frontend-run-v1")),
  ).toBe(runsBefore);
  expect((await ui.workspace()).revision).toBe(3);
});

test("archive persistence failure is not reported as success and preserves existing workspace", async ({
  page,
}) => {
  await page.addInitScript(() => {
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key.startsWith("vsf-frontend-versions-v1:"))
        throw new DOMException("quota", "QuotaExceededError");
      original.call(this, key, value);
    };
  });
  const ui = new VersionsPage(page);
  await ui.open();
  const before = await ui.workspace();
  await page.getByRole("button", { name: "保存新版本", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("版本未保存");
  await expect(page.getByRole("status")).toHaveCount(0);
  expect(await ui.workspace()).toEqual(before);
  await expect(
    page.getByRole("button", { name: "查看 V1", exact: true }),
  ).toHaveCount(0);
});

test("unsaved version metadata protects return and corrupted cache is preserved", async ({
  page,
}) => {
  await page.addInitScript(
    (k) => localStorage.setItem(k, "broken"),
    archiveKey,
  );
  const ui = new VersionsPage(page);
  await ui.open();
  await expect(page.getByRole("alert")).toContainText("旧内容未覆盖");
  await page.getByLabel("版本说明", { exact: true }).fill("未保存说明");
  await ui.back();
  await expect(
    page.getByRole("dialog", { name: "版本说明尚未保存", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "继续编辑", exact: true }).click();
  await expect(page.getByLabel("版本说明", { exact: true })).toHaveValue(
    "未保存说明",
  );
  await page.getByRole("button", { name: "保存新版本", exact: true }).click();
  expect(await page.evaluate((k) => localStorage.getItem(k), archiveKey)).toBe(
    "broken",
  );
});

for (const viewport of [
  { width: 1366, height: 768 },
  { width: 760, height: 900 },
])
  test(`12 actions remain reachable at ${viewport.width}x${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    const ui = new VersionsPage(page);
    await ui.open(true);
    await expect(
      page.getByRole("button", { name: "保存新版本", exact: true }),
    ).toBeInViewport();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await ui.save("窄窗口保存");
    await expect(
      page.getByRole("button", { name: "查看 V4", exact: true }),
    ).toBeVisible();
  });

import { test, expect } from "@playwright/test";
import { testOrigin } from "../testOrigin";
import { CreationPage } from "./CreationPage";
import { LibraryPage } from "./LibraryPage";
import { EditorFlowPage } from "./EditorFlowPage";
test.beforeEach(async ({ context }) => {
  await context.route("**/*", (r) =>
    new URL(r.request().url()).origin === testOrigin
      ? r.continue()
      : r.abort(),
  );
});
test("library create reaches02, starts empty and cannot continue without preview", async ({
  page,
}) => {
  const library = new LibraryPage(page);
  await library.open();
  await page.getByRole("button", { name: "新建技能", exact: true }).click();
  const ui = new CreationPage(page);
  await ui.ready();
  await expect(page).toHaveURL(/\/skills\/new$/);
  await expect(page.getByLabel("需求描述")).toBeEmpty();
  await expect(
    page.getByRole("button", { name: "继续编辑规则", exact: true }),
  ).toBeDisabled();
  expect(await ui.storage()).toEqual({});
});
test("example creates a full preview; any input change invalidates it and real count updates", async ({
  page,
}) => {
  const ui = new CreationPage(page);
  await ui.open();
  await ui.example();
  await ui.generate();
  await ui.preview();
  const text = await page.getByLabel("需求描述").inputValue();
  await expect(
    page.getByText(`${Array.from(text).length} / 300`, { exact: true }),
  ).toBeVisible();
  await page.getByLabel("技能名称", { exact: true }).fill("新名字");
  await expect(page.getByTestId("creation-preview")).toHaveCount(0);
  await ui.generate();
  await ui.preview();
  await page.getByRole("radio", { name: "图片", exact: true }).check();
  await expect(page.getByTestId("creation-preview")).toHaveCount(0);
  await ui.generate();
  await ui.preview();
  await page.getByLabel("需求描述").fill("检测黄色沙发和白色椅子");
  await ui.generate();
  await expect(page.getByRole("alert")).toContainText("尚未连接 LLM");
  await expect(
    page.getByRole("button", { name: "保存草稿", exact: true }),
  ).toBeDisabled();
  expect(await ui.storage()).toEqual({});
});
test("save once then continue opens the same full identity, pending geometry, R0 and V1", async ({
  page,
}) => {
  const ui = new CreationPage(page);
  await ui.open();
  await ui.example();
  await ui.generate();
  await page.getByRole("button", { name: "保存草稿", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("草稿已保存");
  const stored = await ui.storage();
  const index = JSON.parse(stored["vsf-frontend-library-v1"]!);
  const id = index.ids[0];
  const expected = JSON.parse(stored[`vsf-frontend-skill-v1:${id}`]!);
  expect(expected.revision).toBe(0);
  expect(
    expected.draft.regions.every(
      (r: { saved: boolean; points: unknown[] }) =>
        !r.saved && r.points.length === 0,
    ),
  ).toBe(true);
  await expect(page.getByLabel("需求描述")).toBeDisabled();
  await page
    .getByRole("button", { name: "定位到场景标注", exact: true })
    .click();
  await expect(page).toHaveURL(new RegExp(`/skills/${id}/editor\\?view=scene`));
  await expect(
    page.getByRole("heading", { name: "标注资源", exact: true }),
  ).toBeVisible();
  expect(
    JSON.parse((await ui.storage())["vsf-frontend-library-v1"]!).ids,
  ).toEqual([id]);
  await page.reload();
  const saved = JSON.parse(
    (await ui.storage())[`vsf-frontend-skill-v1:${id}`]!,
  );
  expect(saved.draft).toEqual(expected.draft);
  expect(
    JSON.parse((await ui.storage())[`vsf-frontend-versions-v1:${id}`]!)
      .versions[0].document,
  ).toEqual(expected.draft);
});
test("continue directly saves once and uses shared editor validation, not auto-apply", async ({
  page,
}) => {
  const ui = new CreationPage(page);
  await ui.open();
  await ui.example();
  await ui.generate();
  await page.getByRole("button", { name: "继续编辑规则", exact: true }).click();
  await expect(page).toHaveURL(/\/skills\/skill-[^/]+\/editor\?view=linked/);
  await expect(page.getByTestId("revision-status")).toContainText("尚未应用");
  await page.getByRole("button", { name: "校验并应用", exact: true }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "校验未通过" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "区域1尚未绘制并保存。" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "区域2尚未绘制并保存。" }),
  ).toBeVisible();
  await expect(page.getByTestId("revision-status")).toContainText("尚未应用");
});
test("leaving requires explicit discard or saving, including browser history", async ({
  page,
}) => {
  await page.goto("/skills");
  await new LibraryPage(page).ready();
  await page.getByRole("button", { name: "新建技能", exact: true }).click();
  const ui = new CreationPage(page);
  await ui.ready();
  await ui.example();
  await page.goBack();
  await expect(
    page.getByRole("dialog", { name: "离开新建页面？" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "继续填写", exact: true }).click();
  await expect(page).toHaveURL(/\/skills\/new$/);
  await ui.generate();
  await page.getByRole("button", { name: "技能库", exact: true }).click();
  await page
    .getByRole("button", { name: "保存草稿并离开", exact: true })
    .click();
  await new LibraryPage(page).ready();
  expect(
    JSON.parse((await ui.storage())["vsf-frontend-library-v1"]!).ids,
  ).toHaveLength(1);
});
test("unsupported text cannot be saved; discard exits without writes", async ({
  page,
}) => {
  const ui = new CreationPage(page);
  await ui.open();
  await page.getByLabel("需求描述").fill("识别桥梁裂缝");
  await page.getByLabel("技能名称", { exact: true }).fill("桥梁");
  await ui.generate();
  await page.getByRole("button", { name: "技能库", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "保存草稿并离开", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "放弃并离开", exact: true }).click();
  await new LibraryPage(page).ready();
  expect(await ui.storage()).toEqual({});
});
test("quota failure keeps input and preview, never navigates or claims success", async ({
  page,
}) => {
  const ui = new CreationPage(page);
  await ui.open();
  await ui.example();
  await ui.generate();
  await page.evaluate(() => {
    Storage.prototype.setItem = () => {
      throw new Error("quota");
    };
  });
  await page.getByRole("button", { name: "继续编辑规则", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("未保存");
  await ui.preview();
  await expect(page.getByLabel("需求描述")).toBeEnabled();
  await expect(page).toHaveURL(/\/skills\/new$/);
  expect(await ui.storage()).toEqual({});
});
test("fixture02 preview never creates normal workspace or archive", async ({
  page,
}) => {
  const ui = new CreationPage(page);
  await ui.open(true);
  await ui.preview();
  await page.getByRole("button", { name: "继续编辑规则", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("隔离演示");
  expect(await ui.storage()).toEqual({});
});
test("02 to03 to15 draws required regions then explicitly applies R1 without changing rule sources", async ({
  page,
}) => {
  const ui = new CreationPage(page);
  await ui.open();
  await ui.example();
  await ui.generate();
  await page
    .getByRole("button", { name: "定位到场景标注", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "标注资源", exact: true }),
  ).toBeVisible();
  const drawing = new EditorFlowPage(page);
  for (const [index, points] of [
    [
      [0.1, 0.3],
      [0.3, 0.3],
      [0.3, 0.7],
      [0.1, 0.7],
    ],
    [
      [0.6, 0.3],
      [0.9, 0.3],
      [0.9, 0.7],
      [0.6, 0.7],
    ],
  ].entries()) {
    await page
      .getByRole("button", { name: `编辑资源区域${index + 1}`, exact: true })
      .click();
    await page.getByRole("button", { name: "多边形", exact: true }).click();
    await drawing.draw(points);
  }
  await page
    .getByRole("button", { name: "保存标注并继续", exact: true })
    .click();
  await page.getByRole("button", { name: "校验并应用", exact: true }).click();
  await expect(page.getByTestId("revision-status")).toContainText(
    "当前运行 R1",
  );
  const data = await ui.storage();
  const id = JSON.parse(data["vsf-frontend-library-v1"]!).ids[0];
  const workspace = JSON.parse(data[`vsf-frontend-skill-v1:${id}`]!);
  expect(workspace.revision).toBe(1);
  expect(workspace.draft).toEqual(workspace.applied);
  expect(workspace.draft.conditions).toHaveLength(5);
  expect(workspace.draft.final.members).toEqual(["branch-a", "branch-b"]);
});
for (const viewport of [
  { width: 1366, height: 768 },
  { width: 760, height: 900 },
])
  test(`creation is reachable without horizontal overflow at ${viewport.width}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    const ui = new CreationPage(page);
    await ui.open(true);
    await ui.preview();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await expect(
      page.getByRole("button", { name: "继续编辑规则", exact: true }),
    ).toBeInViewport();
    await page
      .getByRole("button", { name: "定位到场景标注", exact: true })
      .click();
    await expect(page.getByRole("dialog")).toBeVisible();
  });

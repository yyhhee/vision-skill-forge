import { test, expect } from "@playwright/test";
import { testOrigin } from "../testOrigin";
import { WorkspacePage } from "./WorkspacePage";

test.beforeEach(async ({ context }) => {
  await context.route("**/*", (route) =>
    new URL(route.request().url()).origin === testOrigin
      ? route.continue()
      : route.abort(),
  );
});

test("fixed state uses native viewport, real local assets, no console failures or external requests", async ({
  page,
}) => {
  const errors: string[] = [];
  const external: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("request", (r) => {
    if (!r.url().startsWith(`${testOrigin}/`)) external.push(r.url());
  });
  await new WorkspacePage(page).open();
  const state = await page.evaluate(() => ({
    width: innerWidth,
    height: innerHeight,
    dpr: devicePixelRatio,
    fonts: document.fonts.check('700 24px "Noto Sans SC"'),
    images: [...document.images].every((i) => i.complete && i.naturalWidth > 0),
  }));
  expect(state).toEqual({
    width: 1513,
    height: 1040,
    dpr: 1,
    fonts: true,
    images: true,
  });
  await expect(page.getByTestId("revision-status")).toContainText("R3");
  expect(errors).toEqual([]);
  expect(external).toEqual([]);
});

test("ROI and branch selection link both directions without changing revision", async ({
  page,
}) => {
  await new WorkspacePage(page).open();
  await page.getByRole("button", { name: "选择区域2", exact: true }).click();
  await expect(page.getByTestId("branch-b")).toHaveClass(/selected/);
  await page
    .getByTestId("branch-a")
    .getByText("分支A · 区域1", { exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "选择区域1", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("revision-status")).toContainText("R3");
});

test("saving color changes draft only; explicit apply createsR4 and snapshot matches", async ({
  page,
}) => {
  const ui = new WorkspacePage(page);
  await ui.open();
  await ui.editColor();
  await page.getByLabel("颜色", { exact: true }).selectOption("blue");
  await page.getByLabel("颜色至少占该部位").fill("15");
  await page.getByLabel("模型语义短语").fill("person wearing a blue top");
  await ui.confirmEvidence();
  await ui.save();
  await expect(
    page.getByRole("button", { name: "蓝色上衣", exact: true }),
  ).toBeVisible();
  const oldSnapshot = await ui.appliedSnapshot();
  await expect(oldSnapshot).toContainText("红色上衣 · 至少20%");
  await oldSnapshot.getByRole("button", { name: "返回编排" }).click();
  await page.getByRole("button", { name: "校验并应用", exact: true }).click();
  await expect(page.getByTestId("revision-status")).toHaveText(
    "已应用 · 当前运行 R4",
  );
  const newSnapshot = await ui.appliedSnapshot();
  await expect(newSnapshot).toContainText("蓝色上衣 · 至少15%");
});

test("unsaved form protects switching, supports cancel and discard", async ({
  page,
}) => {
  const ui = new WorkspacePage(page);
  await ui.open();
  await ui.editColor();
  await page.getByLabel("颜色", { exact: true }).selectOption("yellow");
  await page.getByRole("button", { name: "关闭编辑面板" }).click();
  await expect(
    page.getByRole("dialog", { name: "当前表单尚未保存" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "继续编辑", exact: true }).click();
  await expect(page.getByLabel("颜色", { exact: true })).toHaveValue("yellow");
  await page.getByRole("button", { name: "关闭编辑面板" }).click();
  await page.getByRole("button", { name: "放弃修改" }).click();
  await expect(
    page.getByRole("button", { name: "红色上衣", exact: true }),
  ).toBeVisible();
});

test("save-before-apply guard applies the newly saved values rather than stale draft", async ({
  page,
}) => {
  const ui = new WorkspacePage(page);
  await ui.open();
  await ui.editColor();
  await page.getByLabel("颜色至少占该部位").fill("35");
  await page.getByRole("button", { name: "校验并应用", exact: true }).click();
  await page.getByRole("button", { name: "保存后继续", exact: true }).click();
  const snapshot = await ui.appliedSnapshot();
  await expect(snapshot).toContainText("红色上衣 · 至少35%");
});

test("undo and redo restore draft without mutatingR3", async ({ page }) => {
  const ui = new WorkspacePage(page);
  await ui.open();
  await ui.editColor();
  await page.getByLabel("颜色", { exact: true }).selectOption("blue");
  await ui.confirmEvidence();
  await ui.save();
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "红色上衣", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "重做", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "蓝色上衣", exact: true }),
  ).toBeVisible();
  await expect(page.getByTestId("revision-status")).toContainText("R3");
});

test("evidence combination and custom condition name remain editable", async ({
  page,
}) => {
  const ui = new WorkspacePage(page);
  await ui.open();
  await ui.editColor();
  await page.getByLabel("条件名称", { exact: true }).fill("自定义颜色条件");
  await page.getByLabel("任一满足（OR）", { exact: true }).check();
  await ui.save();
  await page
    .getByRole("button", { name: "自定义颜色条件", exact: true })
    .click();
  await expect(
    page.getByLabel("任一满足（OR）", { exact: true }),
  ).toBeChecked();
});

test("branch scope is explicit; immediate hides time inputs; continuous values persist", async ({
  page,
}) => {
  const ui = new WorkspacePage(page);
  await ui.open();
  await page
    .getByRole("button", { name: "编辑分支B · 区域2", exact: true })
    .click();
  await expect(
    page.getByText("区域2内的人员集合，按区域判断", { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("连续满足（秒）")).toHaveCount(0);
  await page.getByLabel("何时算分支成立").selectOption("continuous");
  await page.getByLabel("连续满足（秒）").fill("6");
  await ui.save();
  await page
    .getByRole("button", { name: "编辑分支B · 区域2", exact: true })
    .click();
  await expect(page.getByLabel("连续满足（秒）")).toHaveValue("6");
});

test("finalAND/OR and output naming update the shared diagram", async ({
  page,
}) => {
  const ui = new WorkspacePage(page);
  await ui.open();
  await page.getByRole("button", { name: "编辑最终判定", exact: true }).click();
  await page.getByLabel("分支A或分支B满足（OR）").check();
  await ui.save();
  await expect(
    page.getByRole("button", { name: "编辑最终判定", exact: true }),
  ).toContainText("任一分支满足");
  await page
    .getByRole("button", { name: "编辑区域告警事件", exact: true })
    .click();
  await expect(page.getByLabel("结果来源")).toHaveValue("final-and");
  await page.getByLabel("输出名称").fill("新的区域事件");
  await ui.save();
  await expect(
    page.getByRole("button", { name: "编辑区域告警事件", exact: true }),
  ).toContainText("新的区域事件");
});

test("three views, simulated timeline and evidence expansion are functional", async ({
  page,
}) => {
  await new WorkspacePage(page).open();
  await page.getByRole("button", { name: "仅画布", exact: true }).click();
  await expect(page.getByTestId("scene-media")).toHaveCount(0);
  await page.getByRole("button", { name: "仅画面", exact: true }).click();
  await expect(page.getByTestId("rule-flow")).toHaveCount(0);
  await page.getByRole("button", { name: "联动编排", exact: true }).click();
  await page
    .getByRole("button", { name: "查看模拟时间20秒", exact: true })
    .click();
  await expect(page.getByRole("slider", { name: "模拟时间轴" })).toHaveValue(
    "20",
  );
  await page
    .getByRole("button", { name: "结果与证据 · 运行后查看", exact: true })
    .click();
  await expect(page.getByText(/本页尚未运行识别/)).toBeVisible();
});

test("unsaved polygon points cannot disappear when switching view", async ({
  page,
}) => {
  await new WorkspacePage(page).open();
  await page.getByRole("button", { name: "绘制区域", exact: true }).click();
  const media = page.getByTestId("scene-media");
  const box = (await media.boundingBox())!;
  await page.mouse.click(box.x + box.width * 0.2, box.y + box.height * 0.3);
  await page.mouse.click(box.x + box.width * 0.4, box.y + box.height * 0.3);
  await page.mouse.click(box.x + box.width * 0.4, box.y + box.height * 0.6);
  await page.getByRole("button", { name: "仅画布", exact: true }).click();
  await expect(
    page.getByRole("dialog", { name: "当前区域尚未保存" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "继续绘制", exact: true }).click();
  await expect(page.getByText(/已选3点/)).toBeVisible();
  await page.getByRole("button", { name: "保存区域", exact: true }).click();
  await expect(page.getByText(/已选3点/)).toHaveCount(0);
});

test("normal demo refresh preserves draft; fixture mode never overwrites user demo data", async ({
  page,
}) => {
  const ui = new WorkspacePage(page);
  await ui.open(false);
  await ui.editColor();
  await page.getByLabel("颜色", { exact: true }).selectOption("blue");
  await ui.save();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "蓝色上衣", exact: true }),
  ).toBeVisible();
  await ui.open(true);
  await expect(
    page.getByRole("button", { name: "红色上衣", exact: true }),
  ).toBeVisible();
  await ui.open(false);
  await expect(
    page.getByRole("button", { name: "蓝色上衣", exact: true }),
  ).toBeVisible();
});

for (const size of [
  { width: 1366, height: 768 },
  { width: 1920, height: 1080 },
  { width: 760, height: 900 },
]) {
  test(`primary controls and drawer remain reachable at${size.width}×${size.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(size);
    await new WorkspacePage(page).open();
    await expect(
      page.getByRole("button", { name: "校验并应用", exact: true }),
    ).toBeInViewport();
    if (size.width < 1100)
      await page.getByRole("button", { name: "仅画布", exact: true }).click();
    await page.getByRole("button", { name: "红色上衣", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "保存到草稿", exact: true }),
    ).toBeInViewport();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
  });
}

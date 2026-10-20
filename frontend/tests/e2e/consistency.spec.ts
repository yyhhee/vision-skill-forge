import { test, expect } from "@playwright/test";
import { testOrigin } from "../testOrigin";
import { ConsistencyPage } from "./ConsistencyPage";
import { RunPage } from "./RunPage";

test.beforeEach(async ({ context }) => {
  await context.route("**/*", (r) =>
    new URL(r.request().url()).origin === testOrigin
      ? r.continue()
      : r.abort(),
  );
});

test("description editing is explicitly non-executable and exposes an honest unconnected replan action", async ({
  page,
}, testInfo) => {
  const ui = new ConsistencyPage(page);
  await ui.open(false);
  const before = await ui.workspace();
  await ui.description();
  await expect(page.getByText(/仅修改说明，不会修改目标/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "按描述重新编排（未接入）", exact: true }),
  ).toBeDisabled();
  await page
    .getByLabel("技能说明", { exact: true })
    .fill("区域1蓝色上衣，区域2至少4人。此处仅为说明。");
  await expect(
    page.getByText(/检测人员 · 上半区域 · 红色占比≥10%/),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("01-description-boundary.png"),
  });
  await ui.save();
  const after = await ui.workspace();
  expect(after.draft.instruction).toContain("此处仅为说明");
  expect(after.draft.conditions).toEqual(before.draft.conditions);
  expect(after.applied).toEqual(before.applied);
  expect(after.revision).toBe(3);
  await expect(page.getByRole("status")).toContainText("检测规则未改变");
});

test("linked input changes preserve custom phrases, persist pending review and block apply until acknowledged", async ({
  page,
}, testInfo) => {
  const ui = new ConsistencyPage(page);
  await ui.open(false);
  await ui.editColor();
  await page.getByLabel("判断部位", { exact: true }).selectOption("lower");
  await expect(page.getByLabel("模型语义短语", { exact: true })).toHaveValue(
    "person wearing a red top",
  );
  await expect(page.getByRole("alert")).toContainText("语义证据待核对");
  await page.getByRole("alert").scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath("02-linked-review.png") });
  await ui.save();
  await page.reload();
  await page.getByRole("button", { name: "校验并应用", exact: true }).click();
  await expect(page.getByLabel("待处理问题", { exact: true })).toContainText(
    "语义证据待核对",
  );
  expect((await ui.workspace()).revision).toBe(3);
  await page.getByRole("button", { name: "定位并修改", exact: true }).click();
  await expect(page.getByLabel("判断部位", { exact: true })).toHaveValue(
    "lower",
  );
  await page
    .getByLabel("模型语义短语", { exact: true })
    .fill("person with a red lower part");
  await ui.confirmEvidence();
  await expect(
    page.getByRole("alert").filter({ hasText: "自定义语义证据待核对" }),
  ).toHaveCount(0);
  await ui.save();
  await page.getByRole("button", { name: "校验并应用", exact: true }).click();
  const data = await ui.workspace();
  expect(data.revision).toBe(4);
  expect(data.applied.conditions[1].semanticQuery).toBe(
    "person with a red lower part",
  );
  expect(data.applied.conditions[1].part).toBe("lower");
});

test("generated phrases follow the selected inputs while custom phrases are never silently replaced", async ({
  page,
}) => {
  const ui = new ConsistencyPage(page);
  await ui.open();
  await ui.editColor();
  await page.getByLabel("颜色", { exact: true }).selectOption("blue");
  await expect(page.getByLabel("模型语义短语", { exact: true })).toHaveValue(
    "person wearing a red top",
  );
  await page
    .getByLabel("语义短语来源", { exact: true })
    .selectOption("generated");
  await page.getByLabel("判断部位", { exact: true }).selectOption("lower");
  await expect(page.getByLabel("模型语义短语", { exact: true })).toHaveValue(
    "person with blue lower part",
  );
  await expect(
    page.getByLabel("模型语义短语", { exact: true }),
  ).toHaveAttribute("readonly", "");
  await expect(
    page.getByRole("alert").filter({ hasText: "语义证据待核对" }),
  ).toHaveCount(0);
  await ui.save();
  await page.getByRole("button", { name: "校验并应用", exact: true }).click();
  await expect(page.getByTestId("revision-status")).toContainText("R4");
});

test("cancelling a revision conflict creates or cancels no task, and continuing explicitly keeps R3", async ({
  page,
}, testInfo) => {
  const ui = new ConsistencyPage(page);
  const original = await ui.prepareVersionConflict();
  await expect(page.getByRole("dialog")).toContainText(
    "准备验证：区域联合告警 · R4",
  );
  await expect(page.getByRole("dialog")).toContainText(
    "尚未结束：区域联合告警 · R3",
  );
  await page.screenshot({ path: testInfo.outputPath("03-version-choice.png") });
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await expect(page.getByTestId("revision-status")).toContainText("R4");
  expect(await ui.archive()).toEqual(original);
  await new RunPage(page).start();
  await page
    .getByRole("button", { name: "继续旧任务 R3", exact: true })
    .click();
  await expect(page.getByTestId("revision-status")).toContainText(
    "使用版本 R3",
  );
  expect(await ui.archive()).toEqual(original);
});

test("starting R4 explicitly cancels the old R3 in the same update without rewriting its snapshot", async ({
  page,
}, testInfo) => {
  const ui = new ConsistencyPage(page);
  const original = await ui.prepareVersionConflict();
  await page
    .getByRole("button", { name: "停止旧任务并新建 R4", exact: true })
    .click();
  await new RunPage(page).pause();
  await expect(page.getByTestId("revision-status")).toContainText(
    "使用版本 R4",
  );
  const archive = await ui.archive();
  expect(archive).toHaveLength(2);
  expect(archive[0].id).toBe(original[0].id);
  expect(archive[0].status).toBe("cancelled");
  expect(archive[0].snapshot).toEqual(original[0].snapshot);
  expect(archive[0].settings).toEqual(original[0].settings);
  expect(archive[0].events).toEqual([]);
  expect(archive[1].id).not.toBe(original[0].id);
  expect(archive[1].revision).toBe(4);
  expect(archive[1].snapshot.conditions[1].minimumFraction).toBe(0.15);
  expect(archive[1].events).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("04-new-r4-task.png") });
});

test("identical revision numbers in different skills still require a deliberate task choice", async ({
  page,
}) => {
  await page.clock.install();
  const ui = new RunPage(page);
  await ui.setup(false);
  await ui.start();
  await ui.pause();
  await page.evaluate(() => {
    const archive = JSON.parse(localStorage.getItem("vsf-frontend-run-v1")!);
    archive.runs[0].snapshot.id = "other-skill";
    archive.runs[0].snapshot.name = "另一个技能";
    archive.runs[0].resultAvailability = "not_provided";
    localStorage.setItem("vsf-frontend-run-v1", JSON.stringify(archive));
  });
  await new RunPage(page).setup(false);
  await new RunPage(page).start();
  await expect(
    page.getByRole("dialog", { name: "选择要验证的版本", exact: true }),
  ).toContainText("另一个技能 · R3");
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "验证配置", exact: true }),
  ).toBeVisible();
});

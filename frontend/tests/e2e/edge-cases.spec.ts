import { test, expect } from "@playwright/test";
import { testOrigin } from "../testOrigin";
import fs from "node:fs/promises";
import { WorkspacePage } from "./WorkspacePage";

test.beforeEach(async ({ context }) => {
  await context.route("**/*", (route) =>
    new URL(route.request().url()).origin === testOrigin
      ? route.continue()
      : route.abort(),
  );
});
test("invalid stored configuration is preserved, not silently overwritten by seed", async ({
  page,
}) => {
  await page.addInitScript(() =>
    localStorage.setItem("vsf-frontend-workspace-v1", "{invalid-json"),
  );
  const ui = new WorkspacePage(page);
  await ui.open(false);
  await expect(page.getByRole("alert")).toContainText("未覆盖旧内容");
  await ui.editColor();
  await page.getByLabel("颜色", { exact: true }).selectOption("blue");
  await ui.save();
  expect(
    await page.evaluate(() =>
      localStorage.getItem("vsf-frontend-workspace-v1"),
    ),
  ).toBe("{invalid-json");
});
test("keyboard Escape opens unsaved guard, cancellation preserves the current form", async ({
  page,
}) => {
  const ui = new WorkspacePage(page);
  await ui.open();
  await ui.editColor();
  await page.getByLabel("条件名称").fill("键盘编辑");
  await page.getByLabel("条件名称").press("Escape");
  await expect(
    page.getByRole("dialog", { name: "当前表单尚未保存" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "继续编辑", exact: true }).click();
  await expect(page.getByLabel("条件名称")).toHaveValue("键盘编辑");
});
test("export contains full draft and the separate applied snapshot", async ({
  page,
}) => {
  const ui = new WorkspacePage(page);
  await ui.open();
  await page.getByRole("button", { name: "更多操作", exact: true }).click();
  const downloadPromise = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "导出完整演示配置", exact: true })
    .click();
  const download = await downloadPromise;
  const payload = JSON.parse(
    await fs.readFile((await download.path())!, "utf8"),
  );
  expect(payload.draft.regions).toHaveLength(2);
  expect(payload.draft.branches).toHaveLength(2);
  expect(payload.draft.outputs[0].source).toBe("final-and");
  expect(payload.draft.runSettings).toBeTruthy();
  expect(payload.draft.conditions[1].minimumFraction).toBe(0.1);
  expect(payload.applied.conditions[1].minimumFraction).toBe(0.2);
  expect(payload.revision).toBe(3);
});
test("native reference anchor geometry stays within2px", async ({ page }) => {
  await new WorkspacePage(page).open();
  const expected = [
    [".topbar", 0, 0, 1513, 68],
    [".instruction-bar", 202, 137, 1297, 60],
    [".scene-panel", 202, 210, 615, 762],
    [".canvas-panel", 829, 210, 670, 762],
    [".scene-media", 217, 275, 585, 440],
    [".detector-card", 1027, 302, 246, 70],
    [".branch-card.orange", 860, 436, 294, 224],
    [".final-card", 1040, 718, 220, 62],
    [".output-card", 1040, 829, 220, 66],
  ] as const;
  for (const [selector, x, y, width, height] of expected) {
    const actual = await page.locator(selector).boundingBox();
    expect(actual).not.toBeNull();
    for (const [key, value] of Object.entries({ x, y, width, height }))
      expect(
        Math.abs(actual![key as keyof typeof actual] - value),
        `${selector} ${key}`,
      ).toBeLessThanOrEqual(2);
  }
});

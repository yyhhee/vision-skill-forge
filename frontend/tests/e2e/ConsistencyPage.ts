import { expect, type Page } from "@playwright/test";
import { WorkspacePage } from "./WorkspacePage";
import { RunPage } from "./RunPage";

export class ConsistencyPage extends WorkspacePage {
  constructor(page: Page) {
    super(page);
  }
  async description() {
    await this.page
      .getByRole("button", { name: "编辑一句话描述", exact: true })
      .click();
  }
  async prepareVersionConflict() {
    await this.page.clock.install();
    const run = new RunPage(this.page);
    await run.setup(false);
    await run.start();
    await run.pause();
    const original = await this.archive();
    await this.page
      .getByRole("button", { name: "返回规则", exact: true })
      .click();
    await this.page
      .getByRole("button", { name: "编辑当前草稿", exact: true })
      .click();
    await this.editColor();
    await this.page.getByLabel("颜色至少占该部位", { exact: true }).fill("15");
    await this.save();
    await this.page
      .getByRole("button", { name: "校验并应用", exact: true })
      .click();
    await expect(this.page.getByTestId("revision-status")).toContainText("R4");
    await this.page
      .getByRole("button", { name: "4 验证", exact: true })
      .click();
    await run.start();
    await expect(
      this.page.getByRole("dialog", { name: "选择要验证的版本", exact: true }),
    ).toBeVisible();
    return original;
  }
  async archive() {
    return this.page.evaluate(
      () => JSON.parse(localStorage.getItem("vsf-frontend-run-v1")!).runs,
    );
  }
  async workspace() {
    return this.page.evaluate(() =>
      JSON.parse(localStorage.getItem("vsf-frontend-workspace-v1")!),
    );
  }
}

import { expect, type Page } from "@playwright/test";
export class WorkspacePage {
  constructor(readonly page: Page) {}
  async open(fixture = true) {
    await this.page.goto(
      `/skills/regional-alert/editor?view=linked${fixture ? "&fixture=04" : ""}`,
    );
    await this.page.evaluate(() => document.fonts.ready);
    await expect(this.page.getByTestId("workspace-panels")).toBeVisible();
    await expect(this.page.getByTestId("scene-media")).toBeVisible();
    await this.page.waitForFunction(
      () =>
        [...document.images].every(
          (image) => image.complete && image.naturalWidth > 0,
        ) && document.fonts.status === "loaded",
    );
    if (this.page.viewportSize()!.width >= 1100)
      await expect(
        this.page.getByRole("button", { name: "编辑检测人员", exact: true }),
      ).toBeVisible();
    else await expect(this.page.getByTestId("scene-media")).toBeVisible();
  }
  async editColor() {
    await this.page
      .getByRole("button", { name: "红色上衣", exact: true })
      .click();
  }
  async save() {
    await this.page
      .getByRole("button", { name: "保存到草稿", exact: true })
      .click();
  }
  async confirmEvidence() {
    await this.page
      .getByRole("button", { name: "已核对，保留当前自定义短语", exact: true })
      .click();
  }
  async appliedSnapshot() {
    await this.page
      .getByRole("button", { name: "测试运行", exact: true })
      .click();
    return this.page.getByRole("dialog");
  }
}

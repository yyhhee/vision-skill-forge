import { expect, type Page } from "@playwright/test";
export class CapabilitiesPage {
  constructor(readonly page: Page) {}
  async open(fixture = false) {
    await this.page.goto(
      `/settings/capabilities${fixture ? "?fixture=capabilities" : ""}`,
    );
    await this.ready();
  }
  async ready() {
    await expect(
      this.page.getByRole("heading", { name: "能力管理", exact: true }),
    ).toBeVisible();
    await this.page.evaluate(() => document.fonts.ready);
  }
  async choose(name: string) {
    await this.page.getByRole("button", { name, exact: true }).click();
  }
  async menu(name: string) {
    await this.page
      .getByRole("button", { name: `更多操作：${name}`, exact: true })
      .click();
  }
  async disable(name: string) {
    await this.page.getByRole("switch", { name: `${name}启用状态` }).click();
    await this.page
      .getByRole("button", { name: "确认停用", exact: true })
      .click();
  }
  async preview(manifest: unknown) {
    await this.page
      .getByRole("button", { name: "安装自定义能力", exact: true })
      .click();
    await this.page
      .getByLabel("选择清单文件", { exact: true })
      .setInputFiles({
        name: "manifest.json",
        mimeType: "application/json",
        buffer: Buffer.from(JSON.stringify(manifest)),
      });
  }
  async install(manifest: unknown) {
    await this.preview(manifest);
    await expect(
      this.page.getByRole("button", {
        name: "确认安装（默认停用）",
        exact: true,
      }),
    ).toBeEnabled();
    await this.page
      .getByRole("button", { name: "确认安装（默认停用）", exact: true })
      .click();
  }
  async stored() {
    return this.page.evaluate(() =>
      JSON.parse(
        localStorage.getItem("vsf-frontend-capabilities-v1") ?? "null",
      ),
    );
  }
}

import { expect, type Page } from "@playwright/test";
export class ModelsPage {
  constructor(readonly page: Page) {}
  async open(fixture = false) {
    await this.page.goto(`/settings/models${fixture ? "?fixture=models" : ""}`);
    await this.ready();
  }
  async ready() {
    await expect(
      this.page.getByRole("heading", { name: "模型接入", exact: true }),
    ).toBeVisible();
    await this.page.evaluate(() => document.fonts.ready);
  }
  async configure(name: string) {
    await this.page
      .getByRole("button", { name: `配置${name}`, exact: true })
      .click();
  }
  async menu(name: string) {
    await this.page
      .getByRole("button", { name: `更多操作：${name}`, exact: true })
      .click();
  }
  async save() {
    await this.page
      .getByRole("button", { name: "保存配置", exact: true })
      .click();
  }
  async fill(name = "我的检测模型") {
    await this.page.getByLabel("显示名称", { exact: true }).fill(name);
    await this.page
      .getByLabel("服务地址", { exact: true })
      .fill("https://model.example/api");
    await this.page.getByLabel("模型名称", { exact: true }).fill("detector-v1");
  }
  async stored() {
    return this.page.evaluate(() =>
      JSON.parse(localStorage.getItem("vsf-frontend-models-v1") || "null"),
    );
  }
  async storage() {
    return this.page.evaluate(() =>
      Object.fromEntries(
        Object.keys(localStorage).map((k) => [k, localStorage.getItem(k)]),
      ),
    );
  }
}

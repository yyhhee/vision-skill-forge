import { expect, type Page } from "@playwright/test";
export class CreationPage {
  constructor(readonly page: Page) {}
  async open(fixture = false) {
    await this.page.goto(`/skills/new${fixture ? "?fixture=02" : ""}`);
    await this.ready();
  }
  async ready() {
    await expect(
      this.page.getByRole("heading", { name: "用一句话描述你的需求" }),
    ).toBeVisible();
    await this.page.evaluate(() => document.fonts.ready);
  }
  async example() {
    await this.page.getByText("演示示例与高级选项", { exact: true }).click();
    await this.page
      .getByRole("button", { name: "使用区域告警演示示例", exact: true })
      .click();
  }
  async generate() {
    await this.page
      .getByRole("button", { name: /^(重新)?生成演示预览$/ })
      .click();
  }
  async preview() {
    await expect(this.page.getByTestId("creation-preview")).toBeVisible();
  }
  async storage() {
    return this.page.evaluate(() =>
      Object.fromEntries(
        Object.keys(localStorage).map((k) => [k, localStorage.getItem(k)]),
      ),
    );
  }
}

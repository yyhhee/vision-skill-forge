import { expect, type Page } from "@playwright/test";
export class LibraryPage {
  constructor(readonly page: Page) {}
  async open(fixture = false) {
    await this.page.goto(`/skills${fixture ? "?fixture=01" : ""}`);
    await this.ready();
  }
  async ready() {
    await expect(
      this.page.getByRole("heading", { name: "我的视觉技能", exact: true }),
    ).toBeVisible();
    await this.page.evaluate(() => document.fonts.ready);
    await this.page.waitForFunction(() =>
      [...document.images].every((i) => i.complete && i.naturalWidth > 0),
    );
  }
  entry(name: string) {
    return this.page.getByRole("article", {
      name: `技能：${name}`,
      exact: true,
    });
  }
  async create(name: string, template = "sequence-demo") {
    await this.page
      .getByRole("button", { name: "新建技能", exact: true })
      .click();
    await this.page.getByText("演示示例与高级选项", { exact: true }).click();
    await this.page.getByRole("button", { name: "从完整模板新建", exact: true }).click();
    await this.page.getByLabel("新技能名称", { exact: true }).fill(name);
    await this.page
      .getByLabel("完整技能模板", { exact: true })
      .selectOption(template);
    await this.page
      .getByRole("button", { name: "创建并编辑", exact: true })
      .click();
    await expect(this.page).toHaveURL(/\/editor/);
    await expect(this.page.getByTestId("workspace-panels")).toBeVisible();
  }
  async backToLibrary() {
    await this.page
      .getByRole("button", { name: "技能库", exact: true })
      .click();
    await this.ready();
  }
  async import(value: unknown, raw = false) {
    await this.page
      .getByLabel("导入完整技能到技能库")
      .setInputFiles({
        name: "skill.json",
        mimeType: "application/json",
        buffer: Buffer.from(raw ? String(value) : JSON.stringify(value)),
      });
  }
  async menu(name: string) {
    await this.page.getByLabel(`更多操作：${name}`, { exact: true }).click();
  }
  async storage() {
    return this.page.evaluate(() =>
      Object.fromEntries(
        Object.keys(localStorage)
          .sort()
          .map((k) => [k, localStorage.getItem(k)]),
      ),
    );
  }
}

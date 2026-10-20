import { expect, type Page, type Download } from "@playwright/test";
import { WorkspacePage } from "./WorkspacePage";

export const archiveKey = "vsf-frontend-versions-v1:regional-alert";
export class VersionsPage {
  constructor(readonly page: Page) {}
  async open(fixture = false, skill = "regional-alert") {
    await this.page.goto(
      `/skills/${skill}/versions${fixture ? "?fixture=12" : ""}`,
    );
    await expect(
      this.page.getByRole("heading", { name: "保存完整技能", exact: true }),
    ).toBeVisible();
    await this.page.evaluate(() => document.fonts.ready);
    await this.page.waitForFunction(() =>
      [...document.images].every((i) => i.complete && i.naturalWidth > 0),
    );
  }
  async fromEditor() {
    await this.page
      .getByRole("button", { name: "更多操作", exact: true })
      .click();
    await this.page
      .getByRole("button", { name: "完整技能与版本", exact: true })
      .click();
    await expect(
      this.page.getByRole("heading", { name: "保存完整技能", exact: true }),
    ).toBeVisible();
  }
  async save(note = "我的完整技能") {
    await this.page.getByLabel("版本说明", { exact: true }).fill(note);
    await this.page
      .getByRole("button", { name: "保存新版本", exact: true })
      .click();
    await expect(this.page.getByRole("status")).toContainText("已保存完整技能");
  }
  async back() {
    await this.page
      .getByRole("button", { name: "返回编辑", exact: true })
      .click();
  }
  async load(number: number) {
    await this.page
      .getByRole("button", { name: `打开并编辑 V${number}`, exact: true })
      .click();
  }
  async importPayload(value: unknown, raw = false) {
    await this.page
      .getByLabel("导入完整技能文件", { exact: true })
      .setInputFiles({
        name: "complete-skill.json",
        mimeType: "application/json",
        buffer: Buffer.from(raw ? String(value) : JSON.stringify(value)),
      });
  }
  async export(number: number): Promise<Download> {
    const download = this.page.waitForEvent("download");
    await this.page
      .getByRole("button", { name: `导出 V${number}`, exact: true })
      .click();
    return download;
  }
  async contents(download: Download) {
    const stream = await download.createReadStream();
    const chunks: Buffer[] = [];
    for await (const chunk of stream!) chunks.push(chunk);
    return JSON.parse(Buffer.concat(chunks).toString());
  }
  async workspace(key = "vsf-frontend-workspace-v1") {
    return this.page.evaluate((k) => JSON.parse(localStorage.getItem(k)!), key);
  }
  async archive(key = archiveKey) {
    return this.page.evaluate((k) => JSON.parse(localStorage.getItem(k)!), key);
  }
}

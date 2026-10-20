import { expect, type Page } from "@playwright/test";
export class HistoryPage {
  constructor(readonly page: Page) {}
  async open(fixture = false) {
    await this.page.goto(`/runs${fixture ? "?fixture=run-history" : ""}`);
    await this.ready();
  }
  async ready() {
    await expect(
      this.page.getByRole("heading", { name: "运行记录", exact: true }),
    ).toBeVisible();
    await expect(
      this.page.getByText("正在读取本地运行归档…", { exact: true }),
    ).toBeHidden();
    await this.page.evaluate(() => document.fonts.ready);
  }
  detail() {
    return this.page.getByRole("complementary", {
      name: "运行结果详情",
      exact: true,
    });
  }
  async seed(count = 1) {
    await this.page.evaluate(async (count) => {
      // @ts-expect-error Browser Vite module; Node must not import JSON dependencies.
      const { exampleRun } = await import("/src/data/runs.ts");
      const runs = Array.from({ length: count }, (_, i) => ({
        ...exampleRun(true),
        id: `record-${i}`,
        createdAt: `2026-10-17T10:${String(26 - i).padStart(2, "0")}:00+08:00`,
      }));
      localStorage.setItem(
        "vsf-frontend-run-v1",
        JSON.stringify({ schemaVersion: 1, runs }),
      );
    }, count);
    await this.page.reload();
    await this.ready();
  }
  async archive() {
    return this.page.evaluate(() =>
      localStorage.getItem("vsf-frontend-run-v1"),
    );
  }
  async exportDetail() {
    const event = this.page.waitForEvent("download");
    await this.detail()
      .getByRole("button", { name: /导出.*JSON/ })
      .click();
    const download = await event,
      stream = await download.createReadStream(),
      chunks: Buffer[] = [];
    for await (const chunk of stream!) chunks.push(chunk);
    return JSON.parse(Buffer.concat(chunks).toString());
  }
}

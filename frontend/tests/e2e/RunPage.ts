import type { Page } from "@playwright/test";
export class RunPage {
  constructor(readonly page: Page) {}
  async setup(fixture = true) {
    await this.page.goto(
      `/skills/regional-alert/validate${fixture ? "?fixture=09" : ""}`,
    );
    await this.ready();
  }
  async monitor() {
    await this.page.goto("/runs/run-regional-r3?state=running&fixture=10");
    await this.ready();
  }
  async results() {
    await this.page.goto("/runs/run-regional-r3?state=completed&fixture=11");
    await this.ready();
  }
  async ready() {
    await this.page.getByTestId("run-media").waitFor();
    await this.page.evaluate(() => document.fonts.ready);
    await this.page.waitForFunction(() =>
      [...document.images].every((i) => i.complete && i.naturalWidth > 0),
    );
  }
  async sampling() {
    await this.page.getByText("抽帧", { exact: true }).click();
  }
  async start() {
    await this.page
      .getByRole("button", { name: "开始模拟验证", exact: true })
      .click();
  }
  async pause() {
    await this.page
      .getByRole("button", { name: "暂停模拟", exact: true })
      .click();
  }
  async finish() {
    await this.page
      .getByRole("button", { name: "继续模拟", exact: true })
      .click();
    await this.page.clock.runFor(12000);
    await this.page
      .getByRole("button", { name: "查看结果与证据", exact: true })
      .click();
  }
}

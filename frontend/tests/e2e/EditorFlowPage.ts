import { expect, type Page } from "@playwright/test";
export class EditorFlowPage {
  constructor(readonly page: Page) {}
  async open(id = "04", normal = false) {
    const query: Record<string, string> = {
      "03": "view=scene",
      "04": "view=linked",
      "05": "view=linked&drawer=condition",
      "06": "view=linked&drawer=time",
      "07": "view=orchestration&drawer=group",
      "08": "view=outputs&drawer=output",
      "15": "view=linked&drawer=issues",
    };
    await this.page.goto(
      `/skills/${id === "07" ? "sequence-demo" : "regional-alert"}/editor?${query[id]}${normal ? "" : `&fixture=${id}`}`,
    );
    await this.page.evaluate(() => document.fonts.ready);
    if (["03", "04", "05", "06", "15"].includes(id))
      await expect(this.page.getByTestId("scene-media")).toBeVisible();
    else
      await expect(this.page.locator(".react-flow__node").last()).toBeVisible();
  }
  async action(name: string) {
    await this.page.getByLabel("编辑工作区").selectOption({ label: name });
  }
  async save() {
    await this.page
      .getByRole("button", { name: "保存到草稿", exact: true })
      .click();
  }
  async close() {
    await this.page
      .getByRole("button", { name: "关闭编辑面板", exact: true })
      .click();
  }
  async draw(points: number[][]) {
    const box = await this.page.getByTestId("scene-media").boundingBox();
    if (!box) throw Error("Missing media");
    for (const [x, y] of points)
      await this.page.mouse.click(
        box.x + box.width * x,
        box.y + box.height * y,
      );
    await this.page
      .getByRole("button", { name: "保存区域", exact: true })
      .click();
  }
}

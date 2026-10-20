import { test, expect } from "@playwright/test";
import { testOrigin } from "../testOrigin";
import { EditorFlowPage } from "./EditorFlowPage";
test.beforeEach(async ({ context }) => {
  await context.route("**/*", (r) =>
    new URL(r.request().url()).origin === testOrigin
      ? r.continue()
      : r.abort(),
  );
});
test("03 resource selection, controlled rename and dependency-protected delete", async ({
  page,
}) => {
  const ui = new EditorFlowPage(page);
  await ui.open("03");
  await page
    .getByRole("button", { name: "编辑资源区域2", exact: true })
    .click();
  await page.getByLabel("名称", { exact: true }).fill("右侧作业区");
  await page.getByRole("button", { name: "保存资源名称" }).click();
  await expect(
    page.getByRole("button", { name: "选择右侧作业区", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "删除区域1", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("被以下条件或规则引用");
  await expect(page.getByTestId("revision-status")).toContainText("R3");
});
test("03 rectangle and direction resources remain genuinely editable and undoable", async ({
  page,
}) => {
  const ui = new EditorFlowPage(page);
  await ui.open("03");
  await page.getByRole("button", { name: "新增区域" }).click();
  await page.getByRole("button", { name: "矩形", exact: true }).click();
  await ui.draw([
    [0.3, 0.2],
    [0.55, 0.4],
  ]);
  await expect(page.getByLabel("标注资源")).toContainText("4个点");
  await page.getByRole("button", { name: "新增区域" }).click();
  await page.getByRole("button", { name: "方向参考", exact: true }).click();
  await ui.draw([
    [0.3, 0.2],
    [0.55, 0.4],
  ]);
  await expect(page.getByLabel("标注资源")).toContainText("2个点");
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  await expect(page.getByLabel("标注资源")).toContainText("尚未完成绘制并保存");
});
test("05 color, part and semantic evidence save together into the same draft", async ({
  page,
}) => {
  const ui = new EditorFlowPage(page);
  await ui.open("05");
  await page.getByLabel("判断部位").selectOption("whole");
  await page.getByLabel("模型语义短语").fill("red object");
  await page.getByLabel("任一满足（OR）").check();
  await page
    .getByRole("button", { name: "已核对，保留当前自定义短语", exact: true })
    .click();
  await ui.save();
  await page.getByRole("button", { name: "红色属性", exact: true }).click();
  await expect(page.getByLabel("判断部位")).toHaveValue("whole");
  await expect(page.getByLabel("模型语义短语")).toHaveValue("red object");
  await expect(page.getByLabel("任一满足（OR）")).toBeChecked();
});
test("06 switches field sets and persists only the chosen branch time", async ({
  page,
}) => {
  const ui = new EditorFlowPage(page);
  await ui.open("06");
  await page.getByLabel("时间模式").selectOption("ratio");
  await expect(page.getByLabel("连续满足（秒）")).toHaveCount(0);
  await page.getByLabel("观察窗口（秒）").fill("20");
  await page.getByLabel("窗口满足比例（%）").fill("70");
  await ui.save();
  await ui.action("时间约束");
  await expect(page.getByLabel("时间模式")).toHaveValue("ratio");
  await expect(page.getByLabel("窗口满足比例（%）")).toHaveValue("70");
  await page.getByLabel("作用分支").selectOption("branch-a");
  await expect(page.getByLabel("时间模式")).toHaveValue("immediate");
});
test("06 supports condition-level time with explicit source and duplicate-timing notice", async ({
  page,
}) => {
  const ui = new EditorFlowPage(page);
  await ui.open("06");
  await ui.save();
  await ui.action("时间约束");
  await page.getByLabel("某个条件", { exact: true }).check();
  await page.getByLabel("作用条件").selectOption("b-count");
  await page.getByLabel("时间模式").selectOption("repeat");
  await page.getByLabel("满足次数", { exact: true }).fill("3");
  await expect(page.getByText(/先计算条件时间/)).toBeVisible();
  await page.getByLabel("按谁分别计时").selectOption("per_region");
  await page.getByLabel("具体计时来源").selectOption("roi-2");
  await ui.save();
  await expect(page.getByTestId("revision-status")).toContainText("R3");
});
test("07 reorder persists stable members, nested groups and anchor configuration", async ({
  page,
}) => {
  const ui = new EditorFlowPage(page);
  await ui.open("07");
  await page.getByRole("button", { name: "下移步骤1", exact: true }).click();
  await page
    .getByLabel("前一步从哪个时刻开始算间隔")
    .selectOption("previous.qualified");
  await page.getByLabel("最长间隔（秒）").fill("15");
  await ui.save();
  await page.getByRole("button", { name: "先A后B", exact: true }).click();
  await expect(page.getByLabel("前一步从哪个时刻开始算间隔")).toHaveValue(
    "previous.qualified",
  );
  await expect(page.getByLabel("最长间隔（秒）")).toHaveValue("15");
  await expect(page.locator(".group-member-list li").first()).toContainText(
    "分支B",
  );
  await expect(page.getByLabel("编辑编排组")).toContainText(
    "（A → B）与C同时满足",
  );
});
test("07 invalid gap is blocked without silently rewriting the user form", async ({
  page,
}) => {
  const ui = new EditorFlowPage(page);
  await ui.open("07");
  await page.getByLabel("最短间隔（秒）").fill("20");
  await ui.save();
  await expect(page.getByRole("dialog")).toContainText("顺序锚点或间隔无效");
  await page.getByRole("button", { name: "返回修改", exact: true }).click();
  await expect(page.getByLabel("最短间隔（秒）")).toHaveValue("20");
});
test("08 controlled source/type and trigger changes persist; no external notification", async ({
  page,
}) => {
  const ui = new EditorFlowPage(page);
  await ui.open("08");
  await page.getByLabel("结果来源", { exact: true }).selectOption("branch-a");
  await page.getByLabel("输出类型", { exact: true }).selectOption("entity_set");
  await page.getByLabel("冷却时间（秒）").fill("10");
  await ui.save();
  await page
    .getByRole("button", { name: "编辑区域告警事件", exact: true })
    .click();
  await expect(page.getByLabel("结果来源", { exact: true })).toHaveValue(
    "branch-a",
  );
  await expect(page.getByLabel("输出类型", { exact: true })).toHaveValue(
    "entity_set",
  );
  await expect(page.getByLabel("冷却时间（秒）")).toHaveValue("10");
  await expect(
    page.getByText("仅本地展示。外部通知未接入，不会发送真实告警。", {
      exact: true,
    }),
  ).toBeVisible();
});
test("15 locate two real issues, repair individually, recheck and applyR4", async ({
  page,
}) => {
  const ui = new EditorFlowPage(page);
  await ui.open("15");
  await expect(page.getByRole("alert")).toContainText("2项问题");
  await page.getByRole("button", { name: "去标注", exact: true }).click();
  await expect(page.getByLabel("名称", { exact: true })).toHaveValue("区域2");
  await page.getByRole("button", { name: "多边形", exact: true }).click();
  await ui.draw([
    [0.5, 0.4],
    [0.7, 0.4],
    [0.7, 0.6],
    [0.5, 0.6],
  ]);
  await expect(page.getByRole("alert")).toContainText("1项问题");
  await page
    .getByRole("button", { name: "保存标注并继续", exact: true })
    .click();
  await page.getByRole("button", { name: "校验并应用", exact: true }).click();
  await page.getByRole("button", { name: "重新选择来源", exact: true }).click();
  await page.getByLabel("结果来源", { exact: true }).selectOption("final-and");
  await ui.save();
  await page.getByRole("button", { name: "校验并应用", exact: true }).click();
  await expect(page.getByTestId("revision-status")).toHaveText(
    "已应用 · 当前运行 R4",
  );
});
test("incomplete draft persists across reload without corrupting applied R3", async ({
  page,
}) => {
  const ui = new EditorFlowPage(page);
  await ui.open("03", true);
  await page.getByRole("button", { name: "新增区域" }).click();
  await expect(page.getByLabel("标注资源")).toContainText("区域3");
  await page.reload();
  await expect(page.getByLabel("标注资源")).toContainText("区域3");
  await expect(
    page.getByText("存储不可用或旧数据无效", { exact: false }),
  ).toHaveCount(0);
  await expect(page.getByTestId("revision-status")).toContainText("R3");
});

test("time-target switching protects unsaved values and continues with the chosen target", async ({
  page,
}) => {
  const ui = new EditorFlowPage(page);
  await ui.open("06");
  await page.getByLabel("作用分支").selectOption("branch-a");
  await expect(
    page.getByRole("dialog", { name: "当前表单尚未保存" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "继续编辑", exact: true }).click();
  await expect(page.getByLabel("连续满足（秒）")).toHaveValue("5");
  await page.getByLabel("作用分支").selectOption("branch-a");
  await page.getByRole("button", { name: "保存后继续", exact: true }).click();
  await expect(page.getByLabel("作用分支")).toHaveValue("branch-a");
  await expect(page.getByLabel("时间模式")).toHaveValue("immediate");
});
test("combined unsaved name and geometry are protected in two steps without losing either", async ({
  page,
}) => {
  const ui = new EditorFlowPage(page);
  await ui.open("03");
  await page.getByRole("button", { name: "多边形", exact: true }).click();
  const box = (await page.getByTestId("scene-media").boundingBox())!;
  for (const [x, y] of [
    [0.3, 0.3],
    [0.45, 0.3],
    [0.45, 0.45],
  ])
    await page.mouse.click(box.x + box.width * x, box.y + box.height * y);
  await page.getByLabel("名称", { exact: true }).fill("已命名作业区");
  await page
    .getByRole("button", { name: "保存标注并继续", exact: true })
    .click();
  await page.getByRole("button", { name: "保存后继续", exact: true }).click();
  await expect(
    page.getByRole("dialog", { name: "当前区域尚未保存" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "保存后继续", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "选择已命名作业区", exact: true }),
  ).toBeVisible();
  await expect(page.getByTestId("revision-status")).toContainText("R3");
});
test("output dependency edges follow the selected business source, not a fixed final node", async ({
  page,
}) => {
  const ui = new EditorFlowPage(page);
  await ui.open("08");
  await page.getByLabel("结果来源", { exact: true }).selectOption("branch-a");
  await ui.save();
  await expect(
    page.getByRole("group", {
      name: "Edge from branch-a to output-alert",
      exact: true,
    }),
  ).toHaveCount(1);
  await expect(
    page.getByRole("group", {
      name: "Edge from final-and to output-alert",
      exact: true,
    }),
  ).toHaveCount(0);
});
for (const size of [
  { width: 1366, height: 768 },
  { width: 760, height: 900 },
]) {
  test(`new editors stay operable at ${size.width}x${size.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(size);
    const ui = new EditorFlowPage(page);
    for (const id of ["03", "05", "06", "07", "08", "15"]) {
      await ui.open(id);
      if (id === "03") {
        await page
          .getByRole("button", { name: "编辑资源区域2", exact: true })
          .scrollIntoViewIfNeeded();
        await page
          .getByRole("button", { name: "编辑资源区域2", exact: true })
          .click();
        await expect(page.getByLabel("名称", { exact: true })).toHaveValue(
          "区域2",
        );
      } else {
        const action = page.getByRole("button", {
          name: id === "15" ? "继续编辑" : "保存到草稿",
          exact: true,
        });
        await expect(action).toBeVisible();
        const box = await action.boundingBox();
        expect(box!.x).toBeGreaterThanOrEqual(0);
        expect(box!.y + box!.height).toBeLessThanOrEqual(size.height + 1);
      }
    }
  });
}

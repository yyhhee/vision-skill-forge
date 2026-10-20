import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  InspectorDrawer,
  createEditorForm,
} from "../../src/components/InspectorDrawer";
import { seedWorkspace } from "../../src/data/document";

describe("controlled business parameter editor", () => {
  it("shows human-readable evidence choices instead of enum codes", () => {
    const doc = seedWorkspace().draft;
    const form = createEditorForm(doc, "a-red", "condition");
    render(
      <InspectorDrawer
        document={doc}
        form={form}
        dirty={false}
        onChange={vi.fn()}
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByLabelText("全部同时满足（AND）")).toBeChecked();
    expect(screen.getByLabelText("颜色")).toHaveValue("red");
    expect(screen.getByLabelText("仅颜色占比")).toBeVisible();
    expect(screen.queryByText("FRACTION_ONLY")).not.toBeInTheDocument();
  });
  it("color changes use a controlled form value, not the document", async () => {
    const doc = seedWorkspace().draft;
    const change = vi.fn();
    const user = userEvent.setup();
    render(
      <InspectorDrawer
        document={doc}
        form={createEditorForm(doc, "a-red", "condition")}
        dirty={false}
        onChange={change}
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    await user.selectOptions(screen.getByLabelText("颜色"), "blue");
    expect(change).toHaveBeenCalledWith(
      expect.objectContaining({ color: "blue" }),
    );
    expect(doc.conditions[1].color).toBe("red");
  });
  it("immediate time mode hides duration and interruption", () => {
    const doc = seedWorkspace().draft;
    render(
      <InspectorDrawer
        document={doc}
        form={createEditorForm(doc, "branch-b", "branch")}
        dirty={false}
        onChange={vi.fn()}
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(screen.queryByLabelText("连续满足（秒）")).not.toBeInTheDocument();
    expect(screen.getByText("区域2内的人员集合，按区域判断")).toBeVisible();
  });
  it("continuous mode shows only relevant fields for this scope", () => {
    const doc = seedWorkspace().draft;
    const form = {
      ...createEditorForm(doc, "branch-b", "branch"),
      timeMode: "continuous",
    };
    render(
      <InspectorDrawer
        document={doc}
        form={form}
        dirty
        onChange={vi.fn()}
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByLabelText("连续满足（秒）")).toHaveValue(5);
    expect(screen.getByLabelText("允许短暂中断（秒）")).toHaveValue(0.5);
    expect(screen.queryByLabelText("观察窗口")).not.toBeInTheDocument();
  });
  it("output source and type are controlled choices, not technical IDs", () => {
    const doc = seedWorkspace().draft;
    render(
      <InspectorDrawer
        document={doc}
        form={createEditorForm(doc, "output-alert", "output")}
        dirty={false}
        onChange={vi.fn()}
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByLabelText("结果来源")).toHaveValue("final-and");
    expect(screen.getByLabelText("输出类型")).toHaveValue("event_list");
    expect(
      screen.queryByRole("textbox", { name: "来源ID" }),
    ).not.toBeInTheDocument();
  });
});

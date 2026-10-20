import type { SkillDocument, TimeRule, Validity } from "./document";

function timeText(rule?: TimeRule, validity?: Validity) {
  let text = "当前画面满足即可";
  if (rule?.mode === "continuous")
    text = `连续 ${rule.durationSeconds} 秒，允许中断 ${rule.allowedGapSeconds ?? 0} 秒`;
  if (rule?.mode === "cumulative")
    text = `${rule.windowSeconds} 秒内累计 ${rule.durationSeconds} 秒`;
  if (rule?.mode === "ratio")
    text = `${rule.windowSeconds} 秒窗口内满足 ${Math.round((rule.fraction ?? 0) * 100)}%`;
  if (rule?.mode === "repeat")
    text = `${rule.windowSeconds} 秒内满足 ${rule.count} 次`;
  if (validity?.mode === "hold") text += `，成立后保持 ${validity.seconds} 秒`;
  if (validity?.mode === "until_end") text += "，有效至事件结束";
  return text;
}
export function versionTimeSummary(doc: SkillDocument) {
  const lines = [...doc.conditions, ...doc.branches]
    .filter(
      (item) =>
        (item.time?.mode && item.time.mode !== "immediate") ||
        (item.validity && item.validity.mode !== "current_frame"),
    )
    .map(
      (item) =>
        `${"label" in item ? item.label : item.name}：${timeText(item.time, item.validity)}`,
    );
  const anchors: Record<string, string> = {
    "previous.start": "前一步开始",
    "previous.qualified": "前一步成立",
    "previous.end": "前一步结束",
  };
  for (const group of doc.groups)
    if (group.operator === "SEQUENCE" && group.transition)
      lines.push(
        `${group.name}：从${anchors[group.transition.from] ?? "未配置锚点"}到下一步开始 ${group.transition.minGapSeconds}–${group.transition.maxGapSeconds} 秒${group.validity?.mode === "hold" ? `，保持 ${group.validity.seconds} 秒` : ""}`,
      );
  return lines.join("；") || "当前画面满足即可，无额外等待";
}

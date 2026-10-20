import fixtures from "../fixtures/mock-fixtures.json";
import { clone, seedWorkspace, type SkillDocument } from "./document";
import { installSkill } from "./skillRepository";
import { draftFile } from "./versions";

export const creationExample = fixtures.creation.acceptedInputs[0];
export const instructionLimit = 300;
export type CreationInput = {
  instruction: string;
  name: string;
  mediaMode: "image" | "video_demo";
};
export const creationSignature = (input: CreationInput) =>
  JSON.stringify(input);
export function previewCreation(input: CreationInput): SkillDocument {
  if (!input.instruction.trim())
    throw new Error("请先描述要识别的目标、条件和期望结果。");
  if (Array.from(input.instruction).length > instructionLimit)
    throw new Error("需求描述不能超过300字。");
  if (!input.name.trim() || input.name.trim().length > 120)
    throw new Error("请填写1–120字的技能名称。");
  if (input.mediaMode !== "image" && input.mediaMode !== "video_demo")
    throw new Error("请选择当前支持的媒体模式。");
  // Exact, disclosed demo lookup, not a natural-language parser or semantic repair.
  if (!fixtures.creation.acceptedInputs.includes(input.instruction.trim()))
    throw new Error(
      "尚未连接 LLM，不能为这段描述生成规则。请选择下方列出的演示示例，或从完整模板新建后手动编辑。",
    );
  const doc = clone(seedWorkspace().draft);
  doc.id = "creation-preview";
  doc.name = input.name.trim();
  doc.instruction = input.instruction.trim();
  doc.mediaMode = input.mediaMode;
  doc.regions = doc.regions.map((r) => ({ ...r, saved: false, points: [] }));
  // This metadata must not claim the seed's hand-located coordinates as generated geometry.
  Object.assign(doc, {
    geometryProvenance: "未生成坐标；需要用户在场景标注中绘制并保存。",
    creationProvenance: "explicit_frontend_demo; no_llm",
  });
  return doc;
}
export function persistCreation(preview: SkillDocument) {
  const document = { ...clone(preview), id: "skill-" + crypto.randomUUID() };
  const result = installSkill(
    JSON.stringify(
      draftFile(
        document,
        "从明确列出的前端演示创建；未调用LLM；区域待手工标注",
      ),
    ),
  );
  if (result.conflict)
    throw new Error("技能身份冲突，未覆盖已有配置，请重试。");
  return result.document.id;
}

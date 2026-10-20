import fixtures from "../fixtures/mock-fixtures.json";
import { validateIssues } from "./validation";

export type Point = [number, number];
export type EvidenceMode = "all" | "any" | "fraction_only" | "semantic_only";
export type TimeRule = {
  mode: string;
  durationSeconds?: number;
  allowedGapSeconds?: number;
  windowSeconds?: number;
  fraction?: number;
  count?: number;
  scope?: { mode: string; source: string };
};
export type Validity = { mode: string; seconds?: number };
export type OrchestrationGroup = {
  id: string;
  name: string;
  operator: string;
  members: string[];
  correlation?: { mode: string; source: string };
  transition?: {
    from: string;
    to: string;
    minGapSeconds: number;
    maxGapSeconds: number;
  };
  validity?: Validity;
};
export type Region = {
  id: string;
  name: string;
  type: string;
  colorIdentity: string;
  saved: boolean;
  points: Point[];
};
export type Condition = {
  id: string;
  label: string;
  kind: string;
  source: string;
  region?: string;
  part?: string;
  color?: string;
  minimumFraction?: number;
  evidenceMode?: EvidenceMode;
  semanticQuery?: string;
  semanticBinding?: {
    mode: "custom" | "generated";
    reviewedContext: EvidenceContext;
  };
  sameEntityRequired?: boolean;
  comparison?: string;
  value?: number;
  time?: TimeRule;
  validity?: Validity;
};
export type EvidenceContext = {
  source: string;
  category: string;
  color: string;
  part: string;
};
export type Branch = {
  id: string;
  name: string;
  resultType: string;
  source: string;
  logic: { operator: string; members: string[] };
  identity: string;
  time: TimeRule;
  validity: Validity;
};
export type SkillDocument = {
  capabilityRefs?: string[];
  id: string;
  schemaVersion: number;
  name: string;
  instruction: string;
  mediaRef: string;
  mediaMode?: "image" | "video_demo";
  regions: Region[];
  entitySources: {
    id: string;
    label: string;
    type: string;
    category: string;
    trackAvailable: boolean;
  }[];
  conditions: Condition[];
  branches: Branch[];
  groups: OrchestrationGroup[];
  final: {
    id: string;
    label: string;
    type: string;
    operator: string;
    members: string[];
  };
  outputs: {
    id: string;
    name: string;
    source: string;
    resultType: string;
    trigger: { mode: string; cooldownSeconds?: number };
    delivery: string;
    evidence?: string;
    showInSummary?: boolean;
  }[];
  runSettings: unknown;
};
export type WorkspaceData = {
  draft: SkillDocument;
  applied: SkillDocument;
  revision: number;
};
export const clone = <T>(value: T): T => structuredClone(value);
export const colorNames: Record<string, string> = {
  red: "红色",
  gray: "灰色",
  blue: "蓝色",
  white: "白色",
  yellow: "黄色",
  black: "黑色",
  green: "绿色",
};
export const colorHex: Record<string, string> = {
  red: "#FB4C65",
  gray: "#6B7280",
  blue: "#4F46E5",
  white: "#94A3B8",
  yellow: "#D97706",
  black: "#1F2937",
  green: "#16A34A",
};
export const modeNames: Record<EvidenceMode, string> = {
  all: "全部同时满足（AND）",
  any: "任一满足（OR）",
  fraction_only: "仅颜色占比",
  semantic_only: "仅模型语义证据",
};
export const seedWorkspace = (fixture = ""): WorkspaceData => ({
  draft: clone(
    fixture === "15"
      ? fixtures.documents["regional-invalid"]
      : fixtures.documents["regional-draft"],
  ) as unknown as SkillDocument,
  applied: clone(
    fixtures.documents["regional-applied"],
  ) as unknown as SkillDocument,
  revision: 3,
});
export function validateDocument(document: SkillDocument): string[] {
  return validateIssues(document).map((issue) => issue.message);
}
export function updateCondition(
  document: SkillDocument,
  updated: Condition,
): SkillDocument {
  return {
    ...document,
    conditions: document.conditions.map((c) =>
      c.id === updated.id ? clone(updated) : c,
    ),
  };
}
export function applyDraft(data: WorkspaceData): WorkspaceData {
  const errors = validateDocument(data.draft);
  if (errors.length) throw new Error(errors.join("\n"));
  return {
    draft: clone(data.draft),
    applied: clone(data.draft),
    revision: data.revision + 1,
  };
}
export function conditionLabel(condition: Condition): string {
  if (condition.kind === "visible_color") return condition.label;
  if (condition.kind === "count") return `人数 ≥ ${condition.value}`;
  return condition.label;
}
export function branchRegion(
  document: SkillDocument,
  branchId: string,
): string | undefined {
  const branch = document.branches.find((b) => b.id === branchId);
  return document.conditions.find(
    (c) => branch?.logic.members.includes(c.id) && c.kind === "inside",
  )?.region;
}
export function conditionBranch(
  document: SkillDocument,
  conditionId: string,
): Branch | undefined {
  return document.branches.find((b) => b.logic.members.includes(conditionId));
}

import {
  BellIcon,
  MapPinIcon,
  TShirtIcon,
  PantsIcon,
  UsersIcon,
  ImageIcon,
  ShareNetworkIcon,
  XIcon,
} from "@phosphor-icons/react";
import { Button, IconButton } from "../ui";
import { RunMedia } from "../runs/RunMedia";
import {
  entryThumbnail,
  workspaceDirty,
  type LibraryEntry,
} from "../../data/libraryEntries";
import { ruleSummary } from "../../data/ruleSummary";
import { colorHex } from "../../data/document";

export function SkillDetail({
  entry,
  onClose,
  onEdit,
  onRuns,
}: {
  entry: LibraryEntry;
  onClose: () => void;
  onEdit: () => void;
  onRuns: () => void;
}) {
  const doc = entry.data?.draft;
  const image = entryThumbnail(entry);
  return (
    <aside
      className="panel library-detail"
      aria-label={`技能详情：${entry.name}`}
    >
      <header>
        <h2>{entry.name}</h2>
        <IconButton label="关闭技能详情" icon={XIcon} onClick={onClose} />
      </header>
      <div className="library-detail-body">
        <div className="library-detail-media">
          {doc?.mediaRef === "construction-poster" ? (
            <RunMedia document={doc} time={12} controls={false} />
          ) : image ? (
            <img src={image} alt={`${entry.name}演示缩略图，不是识别结果`} />
          ) : (
            <p>
              <ImageIcon size={26} />
              素材未接入，配置仍保留
            </p>
          )}
        </div>
        <section>
          <h3>技能说明</h3>
          <p>{entry.instruction}</p>
        </section>
        {doc && entry.data ? (
          <>
            <section>
              <h3>版本信息</h3>
              <div className="library-version-cards">
                <div>
                  <span>当前运行版本</span>
                  <strong>
                    {entry.data.revision > 0
                      ? `R${entry.data.revision}`
                      : "尚未应用"}
                  </strong>
                  <small>
                    {entry.data.revision > 0
                      ? "只在校验并应用后改变"
                      : "导入或新建不会自动生效"}
                  </small>
                </div>
                <div>
                  <span>当前草稿</span>
                  <strong
                    className={
                      workspaceDirty(entry.data) ? "library-draft-label" : ""
                    }
                  >
                    {workspaceDirty(entry.data) ? "有修改" : "与运行一致"}
                  </strong>
                  <small>草稿与保存版本 V 独立</small>
                </div>
              </div>
            </section>
            <section>
              <h3>规则概览</h3>
              <div className="library-rule-summary">
                {doc.branches.map((branch, i) => (
                  <div
                    className={`library-branch ${i % 2 ? "teal" : "orange"}`}
                    key={branch.id}
                  >
                    <ShareNetworkIcon size={29} />
                    <div>
                      <strong>{branch.name}</strong>
                      <small>
                        {branch.logic.operator === "AND"
                          ? "全部条件满足"
                          : branch.logic.operator === "OR"
                            ? "任一条件满足"
                            : "条件不满足"}
                      </small>
                      <ul>
                        {branch.logic.members.map((id) => {
                          const condition = doc.conditions.find(
                            (c) => c.id === id,
                          );
                          const Icon =
                            condition?.kind === "inside"
                              ? MapPinIcon
                              : condition?.kind === "count"
                                ? UsersIcon
                                : condition?.part === "upper"
                                  ? TShirtIcon
                                  : condition?.part === "lower"
                                    ? PantsIcon
                                    : ImageIcon;
                          return (
                            <li key={id}>
                              <Icon
                                size={20}
                                weight="fill"
                                style={{
                                  color:
                                    colorHex[condition?.color ?? ""] ??
                                    "#4f46e5",
                                }}
                              />
                              {condition?.label ?? "待修正来源"}
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  </div>
                ))}
                {doc.groups.length > 0 && (
                  <p>{doc.groups.length} 个编排组 · 保留顺序及嵌套关系</p>
                )}
                <div className="library-output">
                  <BellIcon size={30} />
                  <div>
                    <strong>
                      {doc.outputs.map((o) => o.name).join("、") ||
                        "未配置输出"}
                    </strong>
                    <small>
                      最终组合：{doc.final.operator} · 来源取自完整配置
                    </small>
                  </div>
                </div>
              </div>
              <details>
                <summary>查看完整规则说明</summary>
                <ul>
                  {ruleSummary(doc).map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </details>
            </section>
          </>
        ) : (
          <div className="library-note">
            <strong>{entry.error ? "缓存不可读取" : "仅有示例说明"}</strong>
            <p>
              {entry.error ??
                "此项尚未提供完整可执行配置，不会用区域告警规则冒充。可导入对应的完整技能 JSON。"}
            </p>
          </div>
        )}
      </div>
      <footer>
        {doc ? (
          <>
            <Button variant="primary" onClick={onEdit}>
              继续编辑
            </Button>
            <Button onClick={onRuns}>查看运行记录</Button>
          </>
        ) : (
          <Button onClick={onClose}>返回技能列表</Button>
        )}
      </footer>
    </aside>
  );
}

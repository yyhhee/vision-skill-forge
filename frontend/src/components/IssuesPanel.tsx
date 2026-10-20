import {
  CheckCircleIcon,
  InfoIcon,
  WarningCircleIcon,
  XIcon,
} from "@phosphor-icons/react";
import type { ValidationIssue } from "../data/validation";
import { Button, IconButton } from "./ui";
export function IssuesPanel({
  issues,
  revision,
  onLocate,
  onClose,
  onRecheck,
  onSnapshot,
}: {
  issues: ValidationIssue[];
  revision: number;
  onLocate: (issue: ValidationIssue) => void;
  onClose: () => void;
  onRecheck: () => void;
  onSnapshot: () => void;
}) {
  return (
    <aside className="inspector issues-panel" aria-label="待处理问题">
      <header>
        <h2>{issues.length ? "待处理问题" : "校验通过"}</h2>
        <IconButton icon={XIcon} label="关闭问题面板" onClick={onClose} />
      </header>
      <div className="inspector-body">
        {issues.length === 0 ? (
          <div className="notice">
            <CheckCircleIcon size={24} />
            <span>
              当前草稿未发现结构或配置问题。点击“校验并应用”生成新的本地运行快照。
            </span>
          </div>
        ) : (
          issues.map((issue, index) => (
            <article className="issue-card" key={issue.id}>
              <h3>
                <span>{index + 1}</span>
                {issue.message}
              </h3>
              <p>{issue.detail}</p>
              <Button variant="primary" onClick={() => onLocate(issue)}>
                {issue.kind === "region"
                  ? "去标注"
                  : issue.kind === "output"
                    ? "重新选择来源"
                    : "定位并修改"}
              </Button>
            </article>
          ))
        )}
        <details>
          <summary>专业错误详情（展开查看）</summary>
          <pre>{JSON.stringify(issues, null, 2)}</pre>
        </details>
        <Button onClick={onSnapshot} icon={InfoIcon}>
          查看 R{revision} 的已应用配置
        </Button>
        <div className="notice">
          <WarningCircleIcon size={20} />
          <span>
            草稿已保留；运行版本仍为 R{revision}
            。此处只检查前端配置，不验证模型效果。
          </span>
        </div>
      </div>
      <footer className="issue-footer">
        <Button onClick={onRecheck}>重新校验</Button>
        <Button variant="primary" onClick={onClose}>
          继续编辑
        </Button>
      </footer>
    </aside>
  );
}

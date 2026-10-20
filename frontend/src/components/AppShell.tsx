import {
  CubeIcon,
  PlayCircleIcon,
  StackIcon,
  GearIcon,
  PlayIcon,
  DotsThreeVerticalIcon,
  CheckCircleIcon,
  CircleIcon,
} from "@phosphor-icons/react";
import { Button, IconButton } from "./ui";
import type { PropsWithChildren, ReactNode } from "react";

const navigation = [
  { label: "技能库", icon: CubeIcon },
  { label: "运行记录", icon: PlayCircleIcon },
  { label: "模型接入", icon: StackIcon },
  { label: "能力管理", icon: GearIcon },
];
export function AppShell({
  children,
  dirty,
  revision,
  onApply,
  onRun,
  onMenu,
  onNavigate,
  title = "区域告警",
  applyLabel = "校验并应用",
  actions,
  statusLabel,
  activeNavigation = "技能库",
  showRevision = true,
  className,
}: PropsWithChildren<{
  dirty: boolean;
  revision: number;
  onApply: () => void;
  onRun: () => void;
  onMenu: () => void;
  onNavigate: (label: string) => void;
  title?: string;
  applyLabel?: string;
  actions?: ReactNode;
  statusLabel?: string;
  activeNavigation?: string;
  showRevision?: boolean;
  className?: string;
}>) {
  return (
    <div className={className ? `app-shell ${className}` : "app-shell"}>
      <header className="topbar">
        <div className="brand-mark">
          <img
            src="/assets/brand/vision-forge-mark.png"
            width="30"
            height="30"
            alt="Vision Skill Forge品牌标记"
          />
        </div>
        <strong className="brand-name">Vision Skill Forge</strong>
        <div className="breadcrumb">
          <span>{activeNavigation}</span>
          <span>/</span>
          <strong>{title === "区域联合告警" ? "区域告警" : title}</strong>
        </div>
        {showRevision && (
          <span
            className={`revision-pill ${dirty ? "unapplied" : "applied"}`}
            data-testid="revision-status"
          >
            {dirty ? (
              <CircleIcon size={15} weight="bold" />
            ) : (
              <CheckCircleIcon size={16} />
            )}
            {statusLabel ??
              (revision === 0
                ? "草稿 · 尚未应用"
                : dirty
                  ? `草稿未应用 · 当前运行 R${revision}`
                  : `已应用 · 当前运行 R${revision}`)}
          </span>
        )}
        <div className="topbar-actions">
          {actions ?? (
            <>
              <Button icon={PlayIcon} onClick={onRun}>
                测试运行
              </Button>
              <Button variant="primary" onClick={onApply}>
                {applyLabel}
              </Button>
              <IconButton
                label="更多操作"
                icon={DotsThreeVerticalIcon}
                onClick={onMenu}
              />
            </>
          )}
        </div>
      </header>
      <aside className="sidebar">
        <nav aria-label="主导航">
          {navigation.map(({ label, icon: IconComponent }) => (
            <button
              key={label}
              className={`nav-item ${label === activeNavigation ? "active" : ""}`}
              onClick={() => onNavigate(label)}
            >
              <IconComponent size={28} weight="regular" />
              <span>{label}</span>
            </button>
          ))}
        </nav>
      </aside>
      {children}
      <footer className="app-footer">前端演示 · 模拟数据 · 未连接后端</footer>
    </div>
  );
}

import {
  ScanIcon,
  PaletteIcon,
  UsersThreeIcon,
  ShareNetworkIcon,
  MapPinAreaIcon,
  ChartPieIcon,
  CubeIcon,
  CaretRightIcon,
  CaretDownIcon,
  FileTextIcon,
  CodeIcon,
  TrashIcon,
} from "@phosphor-icons/react";
import {
  catalog,
  enabled,
  kindNames,
  type Capability,
  type CapabilityRegistry,
} from "../../data/capabilities";
import type { CapabilityUse } from "../../data/capabilityUsage";
import { Button } from "../ui";
export const capabilityIcon = (id: string) =>
  ({
    detect: ScanIcon,
    "color-review": PaletteIcon,
    "instance-dedup": UsersThreeIcon,
    "temporal-composition": ShareNetworkIcon,
    "color-fraction": ChartPieIcon,
    "same-subject": UsersThreeIcon,
  })[id] ?? MapPinAreaIcon;
export function CapabilityDetail({
  item,
  registry,
  uses,
  auditError,
  select,
  openSkill,
  remove,
}: {
  item: Capability;
  registry: CapabilityRegistry;
  uses: CapabilityUse[];
  auditError: string;
  select: (id: string) => void;
  openSkill: (id: string) => void;
  remove: () => void;
}) {
  const Icon = capabilityIcon(item.id),
    all = catalog(registry);
  return (
    <section className="panel capability-detail" aria-label="能力详情">
      <header>
        <Icon size={46} />
        <div>
          <h2>{item.name}</h2>
          <span className="capability-origin">
            {item.builtin ? "内置" : "用户自定义"} · {kindNames[item.kind]}
          </span>
        </div>
      </header>
      <p className="capability-description">{item.description}</p>
      {!item.builtin && (
        <p className="capability-metadata-only">
          仅安装能力清单 · 编译器／执行器未接入。启用后也不可执行。
        </p>
      )}
      <h3>基本信息</h3>
      <dl className="capability-facts">
        <dt>输入</dt>
        <dd>{item.input}</dd>
        <dt>输出</dt>
        <dd>{item.output}</dd>
        <dt>可调整</dt>
        <dd>{item.parameters.join("、") || "无公开参数"}</dd>
      </dl>
      <h3>依赖的能力</h3>
      <div className="capability-dependencies">
        {item.uses.length ? (
          item.uses.map((id) => {
            const dep = all.find((c) => c.id === id)!,
              DepIcon = capabilityIcon(id);
            return (
              <button key={id} onClick={() => select(id)}>
                <DepIcon size={25} />
                <span>{dep.name}</span>
                <em className={enabled(registry, id) ? "on" : "off"}>
                  {enabled(registry, id) ? "已启用" : "已停用"}
                </em>
              </button>
            );
          })
        ) : (
          <p className="capability-empty-inline">不依赖其它能力</p>
        )}
      </div>
      <h3>被以下技能使用</h3>
      <div className="capability-usage">
        {auditError ? (
          <p role="alert">{auditError}</p>
        ) : uses.length ? (
          uses.map((row) => (
            <button
              key={row.id}
              onClick={() => openSkill(row.id)}
              title={row.contexts.join("、")}
            >
              <CubeIcon size={25} />
              <span>{row.name}</span>
              <CaretRightIcon size={19} />
            </button>
          ))
        ) : (
          <p className="capability-empty-inline">
            当前草稿、运行版本与保存版本中暂无引用
          </p>
        )}
      </div>
      <details className="capability-disclosure">
        <summary>
          <FileTextIcon size={23} />
          提供给编排模型的能力说明
          <CaretDownIcon size={18} />
        </summary>
        <p>{item.plannerHint}</p>
        <p>当前仅供查看，未连接编排模型。能力描述不能覆盖系统约束。</p>
      </details>
      <details className="capability-disclosure">
        <summary>
          <CodeIcon size={23} />
          开发者接口
          <CaretDownIcon size={18} />
        </summary>
        <p>
          标识：<code>{item.id}</code> · 清单格式 v1
        </p>
        <p>
          {item.builtin
            ? "已映射到现有前端配置能力；模型推理仍未接入。"
            : "仅安装声明清单，编译器／执行器未接入。启用不等于可执行，不加载脚本。"}
        </p>
      </details>
      {item.builtin ? (
        <div className="capability-locked">
          <TrashIcon size={23} />
          内置能力不可删除；可启用或停用。
        </div>
      ) : (
        <div className="capability-delete">
          <Button icon={TrashIcon} variant="danger" onClick={remove}>
            删除自定义能力
          </Button>
          <p>删除前检查技能、保存版本和其它能力引用。</p>
        </div>
      )}
    </section>
  );
}

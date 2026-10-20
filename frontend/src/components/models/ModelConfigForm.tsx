import { QuestionIcon } from "@phosphor-icons/react";
import { Button } from "../ui";
import {
  outputNames,
  type ModelConnection,
  type ModelRole,
} from "../../data/modelConnections";
export function ModelConfigForm({
  form,
  role,
  blocked,
  update,
  onSave,
  onCheck,
}: {
  form: ModelConnection;
  role: ModelRole;
  blocked: boolean;
  update: (patch: Partial<ModelConnection>) => void;
  onSave: () => void;
  onCheck: () => void;
}) {
  const capabilities =
    role === "vision"
      ? [
          ["detection", "图像检测"],
          ["multi_category", "多类别请求"],
        ]
      : [["structured_draft", "结构化草稿输出"]];
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSave();
      }}
      className="model-form"
      noValidate
    >
      <fieldset disabled={blocked}>
        <div className="model-fields">
          <label>
            显示名称
            <input
              value={form.name}
              maxLength={80}
              onChange={(e) => update({ name: e.target.value })}
            />
          </label>
          <label>
            接入协议
            <select
              value={form.adapter}
              onChange={(e) =>
                update({
                  adapter: e.target.value as ModelConnection["adapter"],
                })
              }
            >
              <option value="openai-compatible">OpenAI兼容</option>
              <option value="http-standard">HTTP标准适配</option>
            </select>
          </label>
          <label>
            服务地址
            <input
              value={form.endpoint}
              placeholder="https://your-model.example/api"
              type="url"
              autoComplete="off"
              spellCheck={false}
              onChange={(e) => update({ endpoint: e.target.value })}
            />
          </label>
          <label>
            模型名称
            <input
              value={form.modelName}
              maxLength={160}
              onChange={(e) => update({ modelName: e.target.value })}
            />
          </label>
          <label>
            访问凭证
            <input
              disabled
              placeholder="未接后端，不接收或保存真实密钥"
              aria-label="访问凭证（当前不可用）"
            />
          </label>
        </div>
        <div className="model-capabilities">
          <h3>能力声明</h3>
          <p>声明该模型的输出能力，需与实际接口保持一致。</p>
          <div className="model-capability-options">
            {capabilities.map(([key, label]) => (
              <label key={key}>
                <input
                  type="checkbox"
                  checked={form.capabilities.includes(key)}
                  onChange={(e) =>
                    update({
                      capabilities: e.target.checked
                        ? [...form.capabilities, key]
                        : form.capabilities.filter((c) => c !== key),
                    })
                  }
                />
                {label}
              </label>
            ))}
          </div>
        </div>
        <div className="model-fields model-output-fields">
          <label>
            输出规范
            <select
              aria-label="输出规范"
              value={form.output}
              onChange={(e) =>
                update({
                  output: e.target.value as ModelConnection["output"],
                })
              }
            >
              <option
                value={role === "planner" ? "business_draft" : "boxes_classes"}
              >
                {
                  outputNames[
                    role === "planner" ? "business_draft" : "boxes_classes"
                  ]
                }
              </option>
            </select>
          </label>
          {role === "vision" && (
            <label>
              坐标
              <select
                aria-label="坐标"
                value={form.coordinates}
                onChange={(e) =>
                  update({
                    coordinates: e.target
                      .value as ModelConnection["coordinates"],
                  })
                }
              >
                <option value="normalized">原始画面归一化</option>
                <option value="pixels">原始画面像素</option>
              </select>
            </label>
          )}
        </div>
        {role === "vision" && (
          <details className="model-mapping">
            <summary>
              可选映射配置
              <QuestionIcon size={20} />
            </summary>
            <p>仅声明响应字段路径，不执行表达式；无需映射时取消勾选。</p>
            <label>
              <input
                type="checkbox"
                checked={!!form.mapping}
                onChange={(e) => {
                  update({
                    mapping: e.target.checked
                      ? { boxes: "boxes", category: "label", score: "score" }
                      : undefined,
                  });
                }}
              />
              自定义响应字段
            </label>
            {form.mapping && (
              <div className="model-fields">
                {(
                  [
                    ["boxes", "目标框字段"],
                    ["category", "类别字段"],
                    ["score", "置信度字段"],
                  ] as const
                ).map(([key, label]) => (
                  <label key={key}>
                    {label}
                    <input
                      value={form.mapping![key]}
                      onChange={(e) =>
                        update({
                          mapping: {
                            ...form.mapping!,
                            [key]: e.target.value,
                          },
                        })
                      }
                    />
                  </label>
                ))}
              </div>
            )}
          </details>
        )}
      </fieldset>
      <footer className="model-save">
        <div>
          <Button onClick={onCheck} disabled={blocked}>
            检查配置
          </Button>
          <Button variant="primary" type="submit" disabled={blocked}>
            保存配置
          </Button>
        </div>
        <p>仅保存配置；连接未验证，不会改变现有运行。</p>
      </footer>
    </form>
  );
}

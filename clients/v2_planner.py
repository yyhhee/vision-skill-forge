from __future__ import annotations

import json
import os
from dataclasses import dataclass

from dotenv import load_dotenv
from openai import OpenAI

from core.registry import OperatorRegistry
from core.schema import SkillPackage
from core.semantic import SemanticNormalizer, SemanticValidationError, WorkflowCompiler
from core.visual_catalog import ATTRIBUTE_CATALOG, CARRIER_TEXT_ALIASES, COLOR_ALIASES


@dataclass
class PackageCompileResult:
    package: SkillPackage | None
    attempts: int
    degraded: bool
    errors: list[str]
    raw_outputs: list[str]
    strategy: str


class DeepSeekSemanticPlanner:
    def __init__(
        self,
        registry: OperatorRegistry,
        *,
        client=None,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        thinking: bool | None = None,
        reasoning_effort: str | None = None,
    ):
        load_dotenv()
        self.registry = registry
        self.model = model or os.getenv("PLANNER_MODEL", "deepseek-v4-flash")
        if thinking is None:
            thinking = os.getenv("PLANNER_THINKING", "enabled").lower() not in {
                "0", "false", "off", "disabled",
            }
        self.thinking = thinking
        self.reasoning_effort = reasoning_effort or os.getenv(
            "PLANNER_REASONING_EFFORT", "high"
        )
        if client is None:
            key = api_key or os.getenv("PLANNER_API_KEY")
            if not key:
                raise ValueError("PLANNER_API_KEY is not configured")
            client = OpenAI(
                base_url=base_url or os.getenv("PLANNER_BASE_URL", "https://api.deepseek.com"),
                api_key=key,
                timeout=120.0,
            )
        self.client = client
        self.normalizer = SemanticNormalizer()
        self.compiler = WorkflowCompiler(registry)

    def _completion_options(self) -> dict:
        options = {"extra_body": {"thinking": {
            "type": "enabled" if self.thinking else "disabled"
        }}}
        if self.thinking:
            options["reasoning_effort"] = self.reasoning_effort
        else:
            options["temperature"] = 0.0
        return options

    @staticmethod
    def _system_prompt() -> str:
        ontology = {
            "colors": sorted(set(COLOR_ALIASES.values())),
            "known_carriers": sorted(set(CARRIER_TEXT_ALIASES.values())),
            "attribute_dimensions": sorted(ATTRIBUTE_CATALOG),
        }
        return (
            "你是通用视觉技能的语义抽取器，只输出语义账本 JSON，不负责检测，"
            "不输出工作流节点、不输出操作符、不输出 Python 或任何可执行代码。"
            "必须逐字保留每个目标和条件在用户原句中的连续 source_span；每个条件还要给出包含该 span 的 source 分句。"
            "输出 schema："
            '{"mode":"direct_grounding|entity_query|workflow",'
            '"target":{"concept":"规范英文基础实体","source_span":"原文连续片段",'
            '"phrases":["肯定式英文基础实体"],'
            '"classes":[{"label":"具体类别显示名","phrases":["肯定式英文"]}]},'
            '"constraints":[{"kind":"color|shape|size|material|position|quantity|state|wearable|pose|appearance|entity_exclusion|spatial_relation|motion|direction_relation|region_requirement|temporal",'
            '"value":"目录值或开放肯定式英文值","source":"原文机械分句",'
            '"source_span":"最短连续原子条件",'
            '"carrier":"可选属性载体原文或规范名","carrier_span":"可选原文载体",'
            '"phrases":["肯定式英文可见证据"],"temporal":false}],'
            '"logic":"all|any","unresolved":[{"source_span":"原文","reason":"原因"}]}。'
            "不要输出最终 polarity；否定和排除由确定性程序根据原文计算。"
            "颜色修饰衣物、部件或附属物时 carrier 与 carrier_span 必填；颜色直接修饰基础实体才可省略。"
            "target.phrases 永远只写去掉颜色、穿戴、姿态和状态后的基础实体；颜色 carrier 若就是目标基础实体则省略。"
            "当用户明确列举多个可见类别并要求标注具体类型时，写入 target.classes；"
            "每类保留独立 label 和肯定式 phrases。普通单类目标 classes 为空数组。"
            "carrier 优先用目录规范名；目录没有时允许填写开放英文可见部件，例如 reflective vest，禁止为此丢入 unresolved。"
            "不能无损理解的词保留在 unresolved，禁止遗漏、猜测或压缩条件。"
            "Grounding phrases 只能用肯定式可见描述，禁止 not/without/exclude。"
            "原文每个排除/去除/剔除/负样本分句都必须输出 constraint，且 source 必须保留该集合否定词，排除分句不得遗漏。"
            "排除独立目标类别使用 entity_exclusion，value 与 phrases 写被排除类别的肯定英文实体；"
            "排除/去除的是基础主体的穿戴、姿态、状态或外观时，仍使用对应谓词 kind，"
            "不能把‘戴帽子的人/穿背心的人’误写成独立实体类别。"
            "原子无/未/没有/不条件的 phrases 必须描述剥离否定词后的同一正谓词，"
            "例如臀部无支撑应输出 support under hips，而不是 hips suspended；程序随后统一取反。"
            "wearable/pose/state/appearance 等描述主体整体是否满足条件时，"
            "phrases 必须显式包含基础实体并返回同一主体的完整框，例如 person wearing safety helmet，"
            "不要只写 safety helmet 这样的局部部件框；颜色载体仍由 color.carrier 单独表达。"
            "通用结构化值契约："
            "quantity 可只报告计数 {\"measure\":\"count\"}，也可比较 "
            "{\"measure\":\"count\",\"operator\":\">=\",\"value\":3}；"
            "数量比较符已给出但数值缺失时，不得丢弃 quantity；"
            "用 value=1 作为待确认占位值，程序会在 03 阻止运行并要求用户补齐。"
            "需要按多个命名区域分别计数时追加 group_by=named_region 和 region_role，"
            "且必须同时输出相同 region_role 的 region_requirement；"
            "用户说固定区域、指定区域、标注区域、区域内并要求计数或速度时，"
            "必须输出 manual region_requirement，并让对应 quantity/motion 使用 group_by=named_region；"
            "不要把这类条件默认为全画面，也不要把技能显示名称当作目标类别标签。"
            "motion 为 {\"measure\":\"speed\",\"operator\":\"<\","
            "\"threshold\":2,\"unit\":\"pixels_per_second\",\"aggregation\":\"per_track\"}；"
            "按命名区域聚合速度时使用 aggregation=region_mean|region_median，"
            "并追加 group_by=named_region 与 region_role；"
            "direction_relation 的 relation=aligned|opposite，reference_scope=global|per_named_region，"
            "reference_source=whole_video_majority|manual|image_axis；image_axis 时另给 "
            "image_axis=left|right|up|down|up_left|up_right|down_left|down_right；"
            "region_requirement 为 {\"source\":\"manual\",\"cardinality\":\"one|many\","
            "\"semantic_role\":\"通用英文角色\",\"allowed_shapes\":[\"rectangle\",\"polygon\"]}。"
            "徘徊/逗留/停留/滞留（在某区域内持续出现）必须拆成两条 constraint，且 mode 必须是 workflow："
            "① spatial_relation，value={\"relation\":\"inside_roi\",\"region\":{\"source\":\"manual\","
            "\"semantic_role\":\"区域英文角色\",\"shape\":\"polygon\",\"allowed_shapes\":[\"rectangle\",\"polygon\"]}}，"
            "source_span 取'在…区域/区域内'片段；"
            "② temporal，value={\"type\":\"persist\",\"seconds\":原文时长秒数（原文未给时长默认 1.0）}，"
            "source_span 取'徘徊/逗留/停留…'片段，temporal=true。"
            "已按此规则输出 spatial_relation 时不要再重复输出 region_requirement。"
            "禁止用 motion 表达徘徊/逗留/停留，motion 只用于速度数值比较。"
            "spatial_relation 的 region 必须是字典，禁止写字符串。"
            "'在画面中/视频里/整个画面/视野内'等全域限定不是人工区域，禁止为其创建 manual 区域；"
            "需要保留该限定时使用 region={\"source\":\"full_frame\"}，只是场景铺垫时直接省略该条件。"
            "只读执行上下文若提供，只能用于媒体可行性和采样风险理解；禁止把其中参数写入语义账本。"
            "不输出 resize、抽帧、切片、去重、输出尺寸/FPS，不输出 ROI 坐标、方向向量或节点。"
            f"规范目录仅用于映射，不限制开放实体：{json.dumps(ontology, ensure_ascii=False, separators=(',', ':'))}"
        )

    def compile(
        self,
        instruction: str,
        *,
        requested_accept: list[str],
        skill_id: str,
        display_name: str,
        execution_context: dict | None = None,
    ) -> PackageCompileResult:
        text = instruction.strip()
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": json.dumps({
                "instruction": text,
                "requested_accept": requested_accept,
                **(
                    {"execution_context": execution_context}
                    if execution_context is not None
                    else {}
                ),
            }, ensure_ascii=False)},
        ]
        errors: list[str] = []
        raw_outputs: list[str] = []
        retry_without_thinking = False
        for attempt in range(1, 4):
            completion_options = self._completion_options()
            if retry_without_thinking:
                completion_options = {
                    "extra_body": {"thinking": {"type": "disabled"}},
                    "temperature": 0.0,
                }
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
                max_tokens=8192,
                **completion_options,
            )
            raw = response.choices[0].message.content or ""
            raw_outputs.append(raw)
            try:
                if not raw.strip():
                    retry_without_thinking = True
                    raise SemanticValidationError("LLM returned an empty semantic ledger")
                ledger = json.loads(raw)
                semantic_ir = self.normalizer.normalize_ledger(ledger, text)
                package = self.compiler.compile(
                    semantic_ir,
                    original_instruction=text,
                    requested_accept=requested_accept,
                    skill_id=skill_id,
                    display_name=display_name,
                )
                return PackageCompileResult(
                    package, attempt, False, errors, raw_outputs,
                    "semantic_ir+deterministic_workflow",
                )
            except Exception as exc:
                errors.append(str(exc))
                if attempt >= 2 and (not retry_without_thinking or not raw.strip()):
                    break
                repair_messages = [{"role": "user", "content": (
                        f"上一次语义账本无效：{exc}。"
                        "请逐项核对 source/source_span 均来自原句，保留全部条件和 unresolved，"
                        "仍然只返回完整语义账本 JSON。"
                    )}]
                if raw.strip():
                    repair_messages.insert(0, {"role": "assistant", "content": raw})
                messages.extend(repair_messages)
        return PackageCompileResult(
            None, len(raw_outputs), False, errors, raw_outputs, "needs_review"
        )


__all__ = ["DeepSeekSemanticPlanner", "PackageCompileResult"]

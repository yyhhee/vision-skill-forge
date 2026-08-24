from __future__ import annotations

import json
import os
from dataclasses import dataclass

from dotenv import load_dotenv
from openai import OpenAI

from core.registry import OperatorRegistry
from core.business_rule_draft import NaturalLanguageBusinessDraft
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
    business_draft: dict | None = None


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
    def _parse_json_object(raw: str) -> dict:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].lstrip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        if not text.startswith("{") or not text.endswith("}"):
            start, end = text.find("{"), text.rfind("}")
            if start >= 0 and end > start:
                text = text[start : end + 1]
        value = json.loads(text)
        if not isinstance(value, dict):
            raise SemanticValidationError("LLM returned a non-object semantic ledger")
        return value

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
            "同时输出顶层 business_rule，作为可审核业务草稿；它不是执行图。schema 为："
            '{"schema_version":"1.0","media_requirement":"image|video|both",'
            '"branches":[{"key":"英文稳定键","name":"用户业务名","media_type":"image|video",'
            '"logic":"AND|OR|N_OF_M","required_count":null,'
            '"conditions":[{"key":"英文键","name":"业务条件或条件组名",'
            '"operator":"ATOM|AND|OR|NOT|N_OF_M","capability_id":"ATOM时填写业务能力ID",'
            '"parameters":{},"negated":false,"children":["递归使用同一结构"],"required_count":null}],'
            '"time":{"mode":"immediate|continuous|cumulative|ratio",'
            '"duration_seconds":null,"observation_window_seconds":null,'
            '"required_ratio":1.0,"allowed_gap_seconds":0.0,'
            '"identity_scope":"global|object|track|pair|region"}}],'
            '"resources":[{"key":"英文键","name":"待标注业务名",'
            '"resource_type":"region|direction","semantic_role":"英文角色",'
            '"media_types":["image|video"],"minimum_items":1,"paired_region_key":null}],'
            '"patterns":[{"key":"英文键","name":"业务名","media_type":"video",'
            '"mode":"all_active|all_completed|all_completed_within_window|any|n_of_m|sequence|absence|repeat",'
            '"branch_keys":["分支key"],"window_seconds":null,"required_count":null,'
            '"correlation_scope":"global|object|track|pair|region"}],'
            '"final_decision":{"name":"最终结果名","decision_type":"event_decision|detection_summary|measurement_decision|state_summary|timeline_summary",'
            '"source_refs":["branch:key或event:key"],"combination":"AND|OR|N_OF_M","required_count":null},'
            '"results":[{"key":"英文键","name":"用户要看的结果名",'
            '"source_ref":"condition:branchKey.conditionKey|branch:key|event:key|final:primary",'
            '"result_kind":"decision|boolean|count|value|entities|tracks|events|duration|timeline|media",'
            '"unit":null,"evidence_policy":"required|optional|none",'
            '"save_policy":"always|on_change|on_match|never","show_in_overview":true}],'
            '"trigger_policy":{"mode":"none|once|repeat|on_change","cooldown_seconds":0,'
            '"severity":"info|low|medium|high|critical",'
            '"outputs":["event_record","annotated_media","notification"]},'
            '"pending_decisions":[{"key":"英文键","kind":"count_threshold|duration|time_window|comparison_operator|direction_reference|correlation|generic",'
            '"prompt":"给用户的问题","reason":"为什么不确定","recommended_value":null,'
            '"affected_refs":["condition:branchKey.conditionKey"],"required_before":"run"}]}。'
            "业务能力 ID 只可使用：target.detect、target.filter_class、attribute.color、"
            "attribute.geometry、subject.same_attributes、subject.missing_equipment、"
            "spatial.membership、spatial.association、measure.count、measure.statistic、"
            "motion.track、motion.direction、motion.wrong_way、motion.speed、state.current、"
            "state.transition、event.detect_or_compose。时间约束写在 branch.time，跨分支关系写 patterns，"
            "不要把 temporal.*、logic.group 或 output.business_result 当普通条件。"
            "parameters 中的来源用 condition:key 或 condition:branchKey.conditionKey；"
            "区域/方向用 resource:key，全画面用 full_frame。"
            "target.detect 参数为 targets/phrases/business_label；attribute.color 为 source/part/color/minimum_fraction；"
            "subject.same_attributes 为 subject/attributes/minimum_overlap；spatial.membership 为 source/scope/membership/minimum_overlap/inside；"
            "measure.count 为 source/scope/group_by/operator/threshold；motion.wrong_way 为 source/scope/reference/minimum_reverse_angle/minimum_displacement；"
            "event.detect_or_compose 为 source/scope/method/event_label。"
            "同一人的多项属性必须增加 subject.same_attributes，不能只用 AND。"
            "每个能够独立保存结果、展示证据或单独持续计时的业务判断必须建立独立 branch；"
            "例如‘区域1指定着装人员 AND 区域2人数大于2’要建立两个同媒体分支，最终判定再 AND，"
            "但同一人的目标检测、颜色属性和 same_attributes 必须留在同一分支内。"
            "任何 source/subject/object/attributes/equipment 都必须引用 condition:key 或 branch:key，"
            "不得写 full_frame；full_frame 仅可作为 scope。人数统计必须先建立对应 target.detect，"
            "再由 measure.count.source 引用该检测条件。"
            "target.detect.business_label 是结果框面向用户显示的名称：普通人员可写‘人员’，"
            "指定多属性人员应写完整业务名称，例如‘红色上衣、灰色裤子人员’。"
            "顶层用户消息中的 requested_skill_display_name 是用户确认的最终结果/告警名称，"
            "final_decision.name 必须与它完全一致。"
            "嵌套逻辑必须使用 conditions 的递归 operator/children 表达；"
            "NOT 使用一个 child，N_OF_M 同时填写 required_count；不要把逻辑符写进条件名称冒充组合。"
            "未给出的数量、比较符、持续时间、时间窗、区域数量或方向不得猜测：参数可用推荐占位，"
            "但必须同时写 pending_decisions；不得输出字符串 XX 作为数值。"
            "图片分支不得使用轨迹、方向、持续或复杂时序；有任一此类语义时 media_requirement 必须为 video。"
            "‘发出告警/报警/事件通知’只描述输出与触发策略，不是 temporal、motion 或轨迹语义，"
            "不得因此把静态检测任务限定为视频；只有原文明确持续、时间窗、顺序、轨迹、速度或方向时才要求视频。"
            "both 必须分别给出可审核的 image 与 video 分支；每次运行仍只使用一个媒体源。"
            "图片分支和视频分支是同一技能的两种可选执行流程，绝不能放入同一个 pattern；"
            "patterns 只允许编排同一视频流程内的多个视频分支。both 的 final_decision 可同时列出"
            "图片和视频来源，后端会按本次媒体自动选择同媒体来源。"
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
                "requested_skill_display_name": display_name,
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
                ledger = self._parse_json_object(raw)
                business_payload = ledger.pop("business_rule", None)
                semantic_ir = self.normalizer.normalize_ledger(ledger, text)
                package = self.compiler.compile(
                    semantic_ir,
                    original_instruction=text,
                    requested_accept=requested_accept,
                    skill_id=skill_id,
                    display_name=display_name,
                )
                business_draft = (
                    NaturalLanguageBusinessDraft.model_validate(
                        business_payload
                    ).model_dump(mode="json")
                    if business_payload is not None
                    else None
                )
                if business_draft is not None:
                    expected_media = (
                        "both"
                        if set(package.input.accept) == {"image", "video"}
                        else package.input.accept[0]
                    )
                    if business_draft["media_requirement"] != expected_media:
                        raise SemanticValidationError(
                            "business_rule 的媒体流程必须与确定性语义编译结果一致："
                            f"应为 {expected_media}，实际为 "
                            f"{business_draft['media_requirement']}。"
                        )
                return PackageCompileResult(
                    package, attempt, False, errors, raw_outputs,
                    "semantic_ir+deterministic_workflow",
                    business_draft,
                )
            except Exception as exc:
                public_error = (
                    "LLM 返回的配置无法读取，系统已自动重试；请勿填写 JSON。"
                    if isinstance(exc, json.JSONDecodeError)
                    else str(exc)
                )
                errors.append(public_error)
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

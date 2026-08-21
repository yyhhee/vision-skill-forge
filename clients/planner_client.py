from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from dotenv import load_dotenv
from openai import OpenAI

from core.registry import OperatorRegistry
from core.schema import VisualSkillSpec
from core.validator import assert_valid_skill
from core.visual_catalog import (
    ATTRIBUTE_CATALOG, CARRIER_ALIASES, CARRIER_CATALOG, COLOR_MIN_FRACTIONS,
    COLOR_NAMES, COUNT_OPERATORS,
    SPATIAL_RELATIONS, SPATIAL_RELATION_MARKERS, SPATIAL_RELATION_PATTERNS,
)


@dataclass
class CompileResult:
    spec: VisualSkillSpec
    attempts: int
    degraded: bool
    errors: list[str]
    raw_outputs: list[str]
    strategy: str = "llm"


class DeepSeekPlanner:
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
                "0", "false", "off", "disabled"
            }
        self.thinking = thinking
        self.reasoning_effort = reasoning_effort or os.getenv("PLANNER_REASONING_EFFORT", "high")
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

    def _completion_options(self) -> dict:
        options = {"extra_body": {"thinking": {
            "type": "enabled" if self.thinking else "disabled"
        }}}
        if self.thinking:
            options["reasoning_effort"] = self.reasoning_effort
        else:
            options["temperature"] = 0.0
        return options

    def _system_prompt(self) -> str:
        catalog = json.dumps(self.registry.planner_catalog(), ensure_ascii=False, separators=(",", ":"))
        example = {
            "version": "0.1",
            "name": "red_vehicle_detector",
            "display_name": "红色车辆检测",
            "original_instruction": "检测红色车辆",
            "compile_status": "compiled",
            "input": {"accept": ["image"]},
            "nodes": [
                {"id": "image", "op": "media.image@1.0", "inputs": {"media": "$input"}, "params": {}, "enabled": True},
                {"id": "objects", "op": "rex.ground@1.0", "inputs": {"frames": "$image"},
                 "params": {"targets": [{"label": "红色车辆", "phrases": ["red vehicle"]}]}, "enabled": True},
                {"id": "draw", "op": "output.draw@1.0", "inputs": {"frames": "$image", "objects": "$objects"},
                 "params": {}, "enabled": True},
            ],
            "outputs": {"media": "$draw", "objects": "$objects"},
        }
        return (
            "你是视觉技能编译器，不负责识别。只输出一个 json 对象，不要 Markdown。"
            "只能使用下列固定带版本操作符；所有 inputs 使用 $节点ID 引用。"
            "图片必须显式 media.image，视频必须显式 media.video 和 video.sample；"
            "预处理、ROI、跟踪、规则和输出都必须显式成为节点。"
            "输出必须符合 VisualSkillSpec 0.1，compile_status=compiled。"
            "顶层字段必须且只能是 version,name,display_name,original_instruction,compile_status,input,nodes,outputs；"
            "input 必须写成 {\"accept\":[\"image\"]} 或 {\"accept\":[\"video\"]}；"
            "每个 node 的字段必须且只能是 id,op,inputs,params,enabled。所有操作符参数必须放入 params，"
            "绝对不要使用 parameters、type、targets 等额外 node 顶层字段。name 必须以英文字母开头。"
            "复杂可见属性优先压缩成一个复合 grounding phrase；无法可靠组合时也必须生成最小可执行直接 Grounding。"
            "任何缺失、未具备或排除条件都必须改写为其肯定式可见证据，"
            "再通过固定空间关系、集合逻辑和过滤算子表达；禁止直接 Grounding 否定短语。"
            f"合法 JSON 示例：{json.dumps(example, ensure_ascii=False, separators=(',', ':'))}"
            f"操作符目录 JSON：{catalog}"
        )

    def compile(self, instruction: str, media_type: str) -> CompileResult:
        if media_type not in {"image", "video"}:
            raise ValueError("media_type must be image or video")
        entity_result = self._compile_entity_query(instruction, media_type)
        if entity_result is not None:
            return entity_result
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {
                "role": "user",
                "content": (
                    "请把以下自然语言编译为 json VisualSkillSpec。"
                    f"媒体类型：{media_type}。指令：{instruction}"
                ),
            },
        ]
        errors = []
        raw_outputs = []
        for attempt in range(1, 3):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
                max_tokens=8192,
                **self._completion_options(),
            )
            raw = response.choices[0].message.content or ""
            raw_outputs.append(raw)
            try:
                spec = VisualSkillSpec.model_validate_json(raw)
                assert_valid_skill(spec, self.registry)
                return CompileResult(spec, attempt, False, errors, raw_outputs)
            except Exception as exc:
                error = str(exc)
                errors.append(error)
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {
                        "role": "user",
                        "content": f"上一次输出无效：{error}。请修复并只返回完整 json。",
                    }
                )
        return CompileResult(self._fallback(instruction, media_type), 2, True, errors, raw_outputs)

    def _compile_entity_query(
        self, instruction: str, media_type: str
    ) -> CompileResult | None:
        catalog = json.dumps({
            "attributes": ATTRIBUTE_CATALOG,
            "spatial_relations": SPATIAL_RELATIONS,
            "count_operators": COUNT_OPERATORS,
        }, ensure_ascii=False, separators=(",", ":"))
        forced_mode = "workflow" if self._has_relative_spatial_relation(instruction) else None
        system = (
            "你是通用视觉技能编译器的原子约束提取器，不是检测器，不生成执行节点。只输出 JSON。"
            "当结果是一个可用框定位的实体集合时 mode=entity_query；计数、空间、多实体关系、时间或顺序任务才 mode=workflow。"
            "entity_query schema: "
            '{"mode":"entity_query","label":"中文结果标签",'
            '"entity":{"zh":"不含属性的基础实体","en":"单个英文基础实体名",'
            '"kind":"person|vehicle|object|other"},'
            '"required":[predicate...],"absent":[predicate...]}; '
            'predicate schema: {"sources":["对应的机械分句原文"],"source_span":"该原子条件在分句中的最短连续原文",'
            '"kind":"visual_attribute|geometry|support_relation",'
            '"dimension":"color|shape|size|material|position|state|wearable|pose|appearance",'
            '"value":"目录值或肯定式可见属性值","phrases":["1至2个肯定式英文属性片段"],'
            '"carrier":"可选的英文属性载体基础实体，如 clothing|helmet|vehicle body|object",'
            '"region":"whole|head|upper_body|lower_body"}. '
            "必须覆盖原句中每一个可见条件，任何条件都不能省略或泛化。entity 永远只写基础实体，严禁包含颜色、穿戴或姿态。"
            "用户消息包含 instruction 和 clauses。clauses 是机械分句账本；每个 clause 必须至少完整出现在一个 predicate.sources 中，"
            "不允许把两个 clause 拼成一个 source，也不允许遗漏。一个 clause 同时含多个原子条件时，必须让它分别出现在不同 kind 的 predicate.sources 中；"
            "每个原子视觉维度独立成为一个 predicate；禁止把多个维度压成一个 phrase。"
            "每个 predicate 的 source_span 必须是 sources[0] 中的最短连续原子条件原文，不包含排除/去除/正样本/负样本等外层集合操作词。"
            "字段极性由两层否定异或决定：原子否定看 source_span 中的无/未/没有/没/不/非/缺失；外层否定看 source 中的排除/去除/剔除/负样本。"
            "两层恰有一层否定则放 absent，两层都有或都没有则放 required。"
            "同一维度中描述同一状态的多个证据应合并成一个保持全部证据的 phrase。"
            "颜色、大小、画面位置必须只填写目录标准 value；形状、材质、状态、穿戴、姿态、外观填写肯定式英文 value/phrases。"
            "颜色修饰的不是基础实体整体而是可单独定位的部件、衣物或附属物时，必须填写 carrier 为该属性载体的英文基础实体；"
            "颜色直接修饰基础实体整体时不填写 carrier。"
            "每个 pose phrase 必须是包含基础实体和明确姿态动作词的完整描述；人员姿态动作词例如 standing, "
            "walking, running, sitting, squatting, crouching, kneeling, lying, bending, falling, climbing。"
            "禁止只写 person with 加身体属性。"
            "任何使用 supported/supporting/support 的姿态短语必须明确可见支撑来源，例如 by an object, "
            "on a seat, on a surface, under the body；禁止只写某部位 supported。"
            "涉及有支撑/无支撑/由某物支撑时优先使用 support_relation predicate；除 sources/region/kind 外，"
            "必须填写 action（person 只能从 standing/walking/running/sitting/squatting/crouching/kneeling/lying/"
            "bending/falling/climbing/jumping 中选择）、subject_part（英文主体部位）、relation=supported_by、"
            "object（不带 a/an/the 的单个英文支撑物基础名），且不填写 phrases。"
            "无、未、没有、不带、无支撑等否定可见条件必须放 absent，并改写成该条件存在时的肯定式 grounding 反例。"
            "absent 中的 pose 必须使用与 required pose 互斥的可见动作状态，不能重复 required 的动作词。"
            "所有 grounding phrases 禁止出现 not/without/unsupported/exclude/except/rather than。"
            "workflow 必须输出 typed intent，不输出执行节点："
            '{"mode":"workflow","goal":"spatial_filter|count_filter|relation_filter|event",'
            '"entities":[{"id":"英文ID","zh":"中文","en":"英文基础实体",'
            '"attributes":[{"dimension":"属性维度","value":"目录值或肯定式英文属性",'
            '"phrases":["肯定式英文属性片段"],"region":"whole|head|upper_body|lower_body"}]}],'
            '"relations":[{"type":"目录空间关系","subject":"实体ID","object":"实体ID或manual_roi"}],'
            '"aggregation":{"type":"count","operator":"目录比较符","value":数字}|null}。'
            "不要输出任务专用策略名或任务专用规则。"
            f"唯一允许的通用目录：{catalog}"
        )
        clauses = [part.strip() for part in re.split(r"[，,、；;。]+", instruction) if part.strip()]
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(
                {"instruction": instruction, "clauses": clauses}, ensure_ascii=False
            )},
        ]
        raw_outputs = []
        errors = []
        for attempt in range(1, 3):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
                max_tokens=8192,
                **self._completion_options(),
            )
            raw = response.choices[0].message.content or ""
            raw_outputs.append(raw)
            try:
                intent = json.loads(raw)
                if forced_mode == "workflow" and intent.get("mode") != "workflow":
                    raise ValueError("multi-entity relative spatial language must use typed workflow")
                if intent.get("mode") == "workflow":
                    self._validate_workflow_intent(intent)
                    spec = self._workflow_skill(instruction, media_type, intent)
                    return CompileResult(
                        spec, attempt, False, errors, raw_outputs, "llm_intent:workflow"
                    )
                if intent.get("mode") != "entity_query":
                    return None
                self._normalize_catalog_colors(intent, clauses)
                self._validate_entity_query_intent(intent, clauses)
                spec = self._entity_query_skill(instruction, media_type, intent)
                return CompileResult(
                    spec, attempt, False, errors, raw_outputs, "llm_intent:entity_query"
                )
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                errors.append(str(exc))
                messages.extend([
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": (
                        f"该原子约束账本无效：{exc}。请逐段核对原句，修复同一 JSON schema。"
                        "否定/缺失条件必须移入 absent 并改成肯定式反例；不要生成工作流节点。"
                        "若错误涉及 pose，请在保持 clauses 覆盖不变的前提下，为每个 pose phrase 加入"
                        "明确姿态动作词及其可见证据，不能只写 person with 身体属性。"
                        "absent pose 必须改写为与 required pose 动作互斥的互斥反例状态，不能复用相同动作词。"
                        "clauses 的固定极性由中文否定标记决定：含无/未/没有/不/排除的 clause 只能放 absent。"
                    )},
                ])
        degraded = self._fallback(instruction, media_type)
        return CompileResult(
            degraded,
            2,
            True,
            errors,
            raw_outputs,
            "llm_intent:entity_query_degraded",
        )

    @staticmethod
    def _has_relative_spatial_relation(instruction: str) -> bool:
        return any(re.search(pattern, instruction, re.I) for pattern in SPATIAL_RELATION_PATTERNS)

    @staticmethod
    def _normalize_catalog_colors(intent: dict, clauses: list[str]) -> None:
        markers = {
            "白": "white", "黑": "black", "灰": "gray", "红": "red",
            "橙": "orange", "黄": "yellow", "绿": "green", "青": "cyan",
            "蓝": "blue", "紫": "purple", "粉": "pink", "棕": "brown", "褐": "brown",
        }
        existing_colors_by_clause = {
            clause: {
                item.get("value") or (item.get("phrases") or [None])[0]
                for field in ("required", "absent")
                for item in (intent.get(field) or [])
                if isinstance(item, dict) and (item.get("dimension") == "color"
                                               or item.get("kind") == "color")
                and clause in item.get("sources", [])
            }
            for clause in clauses
        }
        for field in ("required", "absent"):
            predicates = intent.get(field)
            if not isinstance(predicates, list):
                continue
            source_templates = {
                clause: next((item for item in predicates if isinstance(item, dict)
                              and clause in item.get("sources", [])), None)
                for clause in clauses
            }
            normalized_predicates = []
            for predicate in predicates:
                if not isinstance(predicate, dict):
                    normalized_predicates.append(predicate)
                    continue
                if predicate.get("dimension") == "color" or predicate.get("kind") == "color":
                    canonical = predicate.get("value")
                    if canonical not in COLOR_NAMES:
                        canonical = next((color for color in COLOR_NAMES if any(
                            re.search(rf"\b{re.escape(color)}\b", phrase, re.I)
                            for phrase in predicate.get("phrases", [])
                        )), canonical)
                    predicate["value"] = canonical
                    predicate["phrases"] = [canonical]
                    if isinstance(predicate.get("carrier"), str):
                        predicate["carrier"] = CARRIER_ALIASES.get(
                            predicate["carrier"].strip().lower(), predicate["carrier"].strip().lower()
                        )
                    normalized_predicates.append(predicate)
                    continue
                phrases = predicate.get("phrases")
                if isinstance(phrases, list):
                    cleaned = []
                    for phrase in phrases:
                        phrase = re.sub(
                            rf"\b({'|'.join(map(re.escape, COLOR_NAMES))})\b", "", phrase,
                            flags=re.I,
                        )
                        phrase = re.sub(r"\s+", " ", phrase).strip()
                        if phrase.lower() not in {"wearing clothing", "wearing clothes", "clothing", "clothes"}:
                            cleaned.append(phrase)
                    if not cleaned:
                        continue
                    predicate["phrases"] = cleaned
                    if isinstance(predicate.get("value"), str):
                        predicate["value"] = re.sub(
                            rf"\b({'|'.join(map(re.escape, COLOR_NAMES))})\b", "",
                            predicate["value"], flags=re.I,
                        ).strip()
                normalized_predicates.append(predicate)
            predicates[:] = normalized_predicates
            carrier_sources = {
                source
                for predicate in predicates
                if isinstance(predicate, dict) and predicate.get("dimension") == "color"
                and predicate.get("carrier")
                for source in predicate.get("sources", [])
            }
            predicates[:] = [
                predicate for predicate in predicates
                if not (
                    isinstance(predicate, dict) and predicate.get("dimension") == "wearable"
                    and any(source in carrier_sources for source in predicate.get("sources", []))
                    and any(token in " ".join(predicate.get("phrases", [])).lower()
                            for token in ("shirt", "jacket", "coat", "clothing", "clothes",
                                          "pants", "trousers", "shorts", "skirt"))
                )
            ]
            for clause in clauses:
                template = source_templates[clause]
                for marker, color in markers.items():
                    if marker not in clause or color in existing_colors_by_clause[clause] or template is None:
                        continue
                    predicates.append({
                        "sources": [clause], "source_span": marker,
                        "kind": "visual_attribute", "dimension": "color", "value": color,
                        "phrases": [color], "region": template.get("region", "whole"),
                    })
                    existing_colors_by_clause[clause].add(color)

    @staticmethod
    def _validate_workflow_intent(intent: dict) -> None:
        if intent.get("goal") not in {"spatial_filter", "count_filter", "relation_filter", "event"}:
            raise ValueError("unsupported workflow goal")
        entities = intent.get("entities")
        if (not isinstance(entities, list) or not entities
                or not all(isinstance(item, dict) and all(
                    isinstance(item.get(key), str) and item[key].strip()
                    for key in ("id", "zh", "en")
                ) for item in entities)):
            raise ValueError("workflow entities are required")
        entity_ids = {item["id"] for item in entities}
        for entity in entities:
            attributes = entity.setdefault("attributes", [])
            if not isinstance(attributes, list):
                raise ValueError("workflow entity attributes must be a list")
            for attribute in attributes:
                if not isinstance(attribute, dict) or attribute.get("dimension") not in ATTRIBUTE_CATALOG:
                    raise ValueError("invalid workflow entity attribute dimension")
                if not isinstance(attribute.get("value"), str) or not attribute["value"].strip():
                    raise ValueError("workflow entity attribute value is required")
                attribute.setdefault("region", "whole")
                if attribute["region"] not in {"whole", "head", "upper_body", "lower_body"}:
                    raise ValueError("invalid workflow entity attribute region")
                phrases = attribute.setdefault("phrases", [attribute["value"]])
                if not isinstance(phrases, list) or not phrases or not all(
                    isinstance(phrase, str) and phrase.strip() for phrase in phrases
                ):
                    raise ValueError("workflow entity attribute phrases are required")
                if attribute["dimension"] == "color" and attribute["value"] not in COLOR_NAMES:
                    raise ValueError("invalid workflow color attribute")
        relations = intent.get("relations", [])
        if not isinstance(relations, list):
            raise ValueError("workflow relations must be a list")
        for relation in relations:
            if (not isinstance(relation, dict)
                    or relation.get("type") not in SPATIAL_RELATIONS
                    or relation.get("subject") not in entity_ids
                    or not isinstance(relation.get("object"), str)):
                raise ValueError("invalid typed spatial relation")
            if relation["object"] != "manual_roi" and relation["object"] not in entity_ids:
                raise ValueError("spatial relation object must reference an entity or manual_roi")
        aggregation = intent.get("aggregation")
        if aggregation is not None and (
            not isinstance(aggregation, dict)
            or aggregation.get("type") != "count"
            or aggregation.get("operator") not in COUNT_OPERATORS
            or not isinstance(aggregation.get("value"), (int, float))
        ):
            raise ValueError("invalid count aggregation")

    def _workflow_skill(self, instruction: str, media_type: str, intent: dict) -> VisualSkillSpec:
        if media_type == "image":
            nodes = [{"id": "media", "op": "media.image@1.0",
                      "inputs": {"media": "$input"}, "params": {}}]
            frame_ref = "$media"
        else:
            nodes = [
                {"id": "media", "op": "media.video@1.0", "inputs": {"media": "$input"}, "params": {}},
                {"id": "frames", "op": "video.sample@1.0", "inputs": {"video": "$media"}, "params": {"fps": 2.0}},
            ]
            frame_ref = "$frames"
        entity_refs = {}
        for entity in intent["entities"]:
            node_id = f"entity_{re.sub(r'[^A-Za-z0-9_]+', '_', entity['id'])}"
            nodes.append({
                "id": node_id, "op": "rex.ground@1.0", "inputs": {"frames": frame_ref},
                "params": {"targets": [{"label": entity["zh"], "phrases": [entity["en"]]}]},
            })
            current_entity_ref = f"${node_id}"
            for index, attribute in enumerate(entity.get("attributes", []), start=1):
                dimension = attribute["dimension"]
                condition_id = f"{node_id}_attribute_{index}"
                if dimension == "color":
                    regions = {
                        "whole": [0.0, 0.0, 1.0, 1.0], "head": [0.0, 0.0, 1.0, 0.35],
                        "upper_body": [0.0, 0.15, 1.0, 0.7], "lower_body": [0.0, 0.45, 1.0, 1.0],
                    }
                    nodes.append({
                        "id": condition_id, "op": "visual.color_fraction@1.0",
                        "inputs": {"frames": frame_ref, "objects": current_entity_ref},
                        "params": {"color": attribute["value"],
                                   "subject_region": regions[attribute["region"]],
                                   "min_fraction": COLOR_MIN_FRACTIONS[attribute["value"]]},
                    })
                elif dimension in {"size", "position"}:
                    nodes.append({
                        "id": condition_id, "op": "visual.geometry@1.0",
                        "inputs": {"objects": current_entity_ref},
                        "params": {"dimension": dimension, "value": attribute["value"],
                                   "size_mode": "relative", "small_max_area": 0.02,
                                   "large_min_area": 0.12, "position_margin": 0.33},
                    })
                else:
                    evidence_id = f"{condition_id}_objects"
                    nodes.extend([
                        {"id": evidence_id, "op": "rex.ground@1.0", "inputs": {"frames": frame_ref},
                         "params": {"targets": [{"label": entity["zh"], "phrases": [
                             f"{entity['en']} {phrase}" for phrase in attribute["phrases"]
                         ]}]}},
                        {"id": condition_id, "op": "spatial.associate@1.0",
                         "inputs": {"subjects": current_entity_ref, "objects": f"${evidence_id}"},
                         "params": {"relation": "overlap", "threshold": 0.5}},
                    ])
                filtered_id = f"{node_id}_filtered_{index}"
                nodes.append({"id": filtered_id, "op": "filter.apply@1.0",
                              "inputs": {"objects": current_entity_ref,
                                         "condition": f"${condition_id}"}, "params": {}})
                current_entity_ref = f"${filtered_id}"
            entity_refs[entity["id"]] = current_entity_ref
        primary_id = intent["entities"][0]["id"]
        current_ref = entity_refs[primary_id]
        for index, relation in enumerate(intent.get("relations", []), start=1):
            if relation["subject"] != primary_id:
                raise ValueError("demo workflow relations must use the first entity as subject")
            relation_type = relation["type"]
            condition_id = f"relation_{index}"
            if relation["object"] == "manual_roi":
                roi_id = "manual_roi"
                if not any(node["id"] == roi_id for node in nodes):
                    nodes.append({
                        "id": roi_id, "op": "region.manual@1.0", "inputs": {},
                        "params": {"shape": "rectangle", "points": [[0.0, 0.0], [1.0, 1.0]]},
                    })
                nodes.append({
                    "id": condition_id, "op": "spatial.inside@1.0",
                    "inputs": {"objects": current_ref, "region": "$manual_roi"},
                    "params": {"mode": "center", "overlap_threshold": 0.5},
                })
                condition_ref = f"${condition_id}"
                if relation_type == "outside_roi":
                    not_id = f"relation_{index}_not"
                    nodes.append({"id": not_id, "op": "logic.not@1.0",
                                  "inputs": {"condition": condition_ref}, "params": {}})
                    condition_ref = f"${not_id}"
            else:
                relation_map = {
                    "inside": "inside", "contains": "contains", "near": "near",
                    "overlap": "overlap", "left_of": "left_of", "right_of": "right_of",
                    "above": "above", "below": "below",
                }
                nodes.append({
                    "id": condition_id, "op": "spatial.associate@1.0",
                    "inputs": {"subjects": current_ref, "objects": entity_refs[relation["object"]]},
                    "params": {"relation": relation_map[relation_type], "threshold": 0.1},
                })
                condition_ref = f"${condition_id}"
            filtered_id = f"spatial_filtered_{index}"
            nodes.append({
                "id": filtered_id, "op": "filter.apply@1.0",
                "inputs": {"objects": current_ref, "condition": condition_ref}, "params": {},
            })
            current_ref = f"${filtered_id}"
        outputs = {"objects": current_ref}
        aggregation = intent.get("aggregation")
        if aggregation:
            nodes.extend([
                {"id": "count", "op": "measure.count@1.0",
                 "inputs": {"objects": current_ref}, "params": {}},
                {"id": "count_condition", "op": "logic.compare@1.0",
                 "inputs": {"left": "$count"},
                 "params": {"operator": aggregation["operator"], "value": aggregation["value"]}},
            ])
            outputs["condition"] = "$count_condition"
        nodes.append({"id": "draw", "op": "output.draw@1.0",
                      "inputs": {"frames": frame_ref, "objects": current_ref}, "params": {}})
        outputs["media"] = "$draw"
        spec = VisualSkillSpec.model_validate({
            "version": "0.1", "name": "typed_visual_workflow",
            "display_name": instruction[:80], "original_instruction": instruction,
            "compile_status": "compiled", "input": {"accept": [media_type]},
            "nodes": nodes, "outputs": outputs,
        })
        assert_valid_skill(spec, self.registry)
        return spec

    @staticmethod
    def _validate_entity_query_intent(intent: dict, clauses: list[str] | None = None) -> None:
        if not isinstance(intent.get("label"), str) or not intent["label"].strip():
            raise ValueError("entity_query label is required")
        forbidden = re.compile(
            r"\b(not|without|unsupported|exclude|excluding|except)\b|rather than", re.I
        )
        colors = set(COLOR_NAMES)
        entity = intent.get("entity")
        if (not isinstance(entity, dict)
                or entity.get("kind") not in {"person", "vehicle", "object", "other"}
                or not isinstance(entity.get("en"), str) or not entity["en"].strip()
                or not isinstance(entity.get("zh"), str) or not entity["zh"].strip()):
            raise ValueError("entity_query requires a base entity")
        for field in ("required", "absent"):
            predicates = intent.get(field)
            if not isinstance(predicates, list):
                raise ValueError(f"entity_query {field} must be a list")
            for predicate in predicates:
                if not isinstance(predicate, dict):
                    raise ValueError("predicate must be an object")
                legacy_dimensions = {
                    "pose": "pose", "wearable": "wearable", "color": "color",
                    "visible_attribute": "appearance",
                }
                if predicate.get("kind") in legacy_dimensions:
                    predicate["dimension"] = legacy_dimensions[predicate["kind"]]
                dimension = predicate.get("dimension")
                if dimension in {"size", "position"}:
                    predicate["kind"] = "geometry"
                elif predicate.get("kind") != "support_relation":
                    predicate["kind"] = "visual_attribute"
                if predicate.get("kind") not in {
                    "visual_attribute", "geometry", "support_relation"
                }:
                    raise ValueError("unsupported predicate kind")
                if predicate["kind"] != "support_relation":
                    if dimension not in ATTRIBUTE_CATALOG:
                        raise ValueError("unsupported visual attribute dimension")
                    if not isinstance(predicate.get("value"), str) or not predicate["value"].strip():
                        phrases = predicate.get("phrases")
                        if isinstance(phrases, list) and phrases:
                            predicate["value"] = phrases[0]
                        else:
                            raise ValueError("visual attribute value is required")
                predicate.setdefault("region", "whole")
                if predicate.get("region") not in {"whole", "head", "upper_body", "lower_body"}:
                    raise ValueError("unsupported predicate region")
                sources = predicate.get("sources")
                if (not isinstance(sources, list) or not sources
                        or not all(isinstance(source, str) and source.strip() for source in sources)):
                    raise ValueError("predicate sources are required")
                source_span = predicate.get("source_span", sources[0])
                if (not isinstance(source_span, str) or not source_span.strip()
                        or source_span.strip() not in sources[0]):
                    raise ValueError("predicate source_span must be a non-empty substring of sources[0]")
                predicate["source_span"] = source_span.strip()
                if predicate["kind"] == "support_relation":
                    if (not isinstance(predicate.get("action"), str)
                            or not predicate["action"].strip()
                            or not isinstance(predicate.get("subject_part"), str)
                            or not predicate["subject_part"].strip()
                            or predicate.get("relation") != "supported_by"
                            or not isinstance(predicate.get("object"), str)
                            or not predicate["object"].strip()):
                        raise ValueError("invalid structured support_relation predicate")
                    if entity["kind"] == "person" and predicate["action"] not in {
                        "standing", "walking", "running", "sitting", "squatting", "crouching",
                        "kneeling", "lying", "bending", "falling", "climbing", "jumping",
                    }:
                        raise ValueError("support_relation action must use a controlled posture action")
                    if re.match(r"^(a|an|the)\s+", predicate["object"].strip(), re.I):
                        raise ValueError("support_relation object must not include an article")
                    if predicate["object"].strip().lower() in {"nothing", "none", "no object"}:
                        raise ValueError(
                            "support_relation must name affirmative counterexample support object"
                        )
                    continue
                phrases = predicate.get("phrases")
                if (not isinstance(phrases, list) or not 1 <= len(phrases) <= 2
                        or not all(isinstance(phrase, str) and phrase.strip() for phrase in phrases)):
                    raise ValueError("predicate sources and phrases are required")
                if predicate.get("dimension") == "color":
                    if len(phrases) != 1 or phrases[0] not in colors:
                        raise ValueError("invalid color predicate")
                    carrier = predicate.get("carrier")
                    if carrier is not None and (
                        not isinstance(carrier, str) or not carrier.strip()
                        or forbidden.search(carrier)
                    ):
                        raise ValueError("color carrier must be an affirmative base entity")
                elif predicate.get("dimension") == "position" and any(
                    re.search(r"\b(left|right)\s+of\b|\b(above|below|near|inside|overlap|contains)\b", phrase, re.I)
                    for phrase in phrases
                ):
                    raise ValueError("relative position must use typed workflow")
                elif any(forbidden.search(phrase) for phrase in phrases):
                    raise ValueError("grounding phrases must be affirmative")
                elif predicate.get("dimension") == "pose" and any(
                    not re.search(rf"\b{re.escape(entity['en'])}\b", phrase, re.I)
                    for phrase in phrases
                ):
                    raise ValueError(
                        "pose phrases must be complete independently detectable descriptions "
                        f"containing the base entity {entity['en']}"
                    )
                elif predicate.get("dimension") == "pose" and entity["kind"] == "person" and any(
                    not re.search(
                        r"\b(standing|walking|running|sitting|seated|squatting|crouching|"
                        r"kneeling|lying|bending|falling|climbing|jumping)\b",
                        phrase,
                        re.I,
                    )
                    for phrase in phrases
                ):
                    raise ValueError(
                        "person pose phrases must contain an explicit posture or action state"
                    )
                elif predicate.get("dimension") == "pose" and any(
                    re.search(r"\bsupported\b", phrase, re.I)
                    and not re.search(
                        r"\b(by|on|under)\b\s+(an?\s+)?(object|seat|chair|bench|surface|body|buttocks)",
                        phrase,
                        re.I,
                    )
                    for phrase in phrases
                ):
                    raise ValueError(
                        "supported pose phrases must name a visible support source"
                    )
        if clauses is not None:
            used_sources = [
                source
                for field in ("required", "absent")
                for predicate in intent[field]
                for source in predicate["sources"]
            ]
            if set(used_sources) != set(clauses):
                raise ValueError(
                    f"predicate sources must cover every clause without invented sources; expected {clauses}"
                )
            source_atoms = [
                (source, predicate["kind"], predicate.get("dimension"), predicate["source_span"].strip())
                for field in ("required", "absent")
                for predicate in intent[field]
                for source in predicate["sources"]
            ]
            if len(source_atoms) != len(set(source_atoms)):
                raise ValueError("a clause may repeat only for distinct atomic predicates")
            color_markers = {
                "白": "white", "黑": "black", "灰": "gray", "红": "red",
                "橙": "orange", "黄": "yellow", "绿": "green", "青": "cyan",
                "蓝": "blue", "紫": "purple", "粉": "pink", "棕": "brown", "褐": "brown",
            }
            for clause in clauses:
                expected_colors = {
                    color for marker, color in color_markers.items() if marker in clause
                }
                actual_colors = {
                    predicate["phrases"][0]
                    for field in ("required", "absent")
                    for predicate in intent[field]
                    if predicate.get("dimension") == "color" and clause in predicate["sources"]
                }
                if expected_colors - actual_colors:
                    raise ValueError(
                        f"compound clause requires separate color predicates: {clause}"
                    )
            atom_negative_markers = ("无", "未", "没有", "没", "不", "非", "缺失")
            outer_negative_markers = ("排除", "去除", "剔除", "负样本")
            normalized = {"required": [], "absent": []}
            for field in ("required", "absent"):
                for predicate in list(intent[field]):
                    source = predicate["sources"][0]
                    span = predicate["source_span"]
                    span_start = source.find(span)
                    prefix = source[:span_start]
                    for marker in ("没有", "未", "没", "无", "不", "非", "缺失"):
                        if prefix.endswith(marker) and not span.startswith(marker):
                            span = marker + span
                            predicate["source_span"] = span
                            break
                    atom_negative = any(
                        marker in span for marker in atom_negative_markers
                    )
                    outer_negative = any(
                        marker in source
                        for source in predicate["sources"]
                        for marker in outer_negative_markers
                    )
                    expected = "absent" if atom_negative ^ outer_negative else "required"
                    if atom_negative and outer_negative and expected == "required":
                        positive_span = re.sub(r"^(没有|未|没|无|不|非|缺失)", "", span)
                        if positive_span and span in intent["label"]:
                            intent["label"] = intent["label"].replace(span, positive_span)
                    normalized[expected].append(predicate)
            for field in ("required", "absent"):
                unique = []
                seen = set()
                for predicate in normalized[field]:
                    semantic_key = (
                        predicate["kind"], predicate.get("dimension"), predicate.get("value"),
                        predicate["region"],
                        tuple(predicate.get("phrases", [])),
                        predicate.get("action"), predicate.get("subject_part"),
                        predicate.get("relation"), predicate.get("object"),
                    )
                    if semantic_key not in seen:
                        seen.add(semantic_key)
                        unique.append(predicate)
                intent[field] = unique
        pose_actions = re.compile(
            r"\b(standing|walking|running|sitting|seated|squatting|crouching|"
            r"kneeling|lying|bending|falling|climbing|jumping)\b",
            re.I,
        )
        required_actions = {
            action.lower()
            for predicate in intent["required"] if predicate.get("dimension") == "pose"
            for phrase in predicate["phrases"]
            for action in pose_actions.findall(phrase)
        }
        absent_actions = {
            action.lower()
            for predicate in intent["absent"] if predicate.get("dimension") == "pose"
            for phrase in predicate["phrases"]
            for action in pose_actions.findall(phrase)
        }
        if required_actions & absent_actions:
            raise ValueError(
                "absent pose must use a mutually exclusive counter-state action, not repeat required pose"
            )

    def _entity_query_skill(
        self, instruction: str, media_type: str, intent: dict
    ) -> VisualSkillSpec:
        if media_type == "image":
            nodes = [
                {"id": "media", "op": "media.image@1.0", "inputs": {"media": "$input"}, "params": {}},
            ]
            frame_ref = "$media"
        else:
            nodes = [
                {"id": "media", "op": "media.video@1.0", "inputs": {"media": "$input"}, "params": {}},
                {"id": "frames", "op": "video.sample@1.0", "inputs": {"video": "$media"}, "params": {"fps": 2.0}},
            ]
            frame_ref = "$frames"
        label = intent["label"].strip()
        entity = intent["entity"]
        nodes.append({
            "id": "candidates", "op": "rex.ground@1.0", "inputs": {"frames": frame_ref},
            "params": {
                "targets": [{"label": entity["zh"].strip(), "phrases": [entity["en"].strip()]}],
                "deduplicate_metric": "ios", "deduplicate_iou": 0.7,
            },
        })
        current_ref = "$candidates"
        predicates = [("required", item) for item in intent["required"]]
        predicates.extend(("absent", item) for item in intent["absent"])
        dimension_order = {"size": 0, "position": 1}
        predicates.sort(key=lambda item: dimension_order.get(item[1].get("dimension"), 2))
        if any(
            polarity == "required"
            and predicate.get("dimension") not in {"color", "size", "position"}
            for polarity, predicate in predicates
        ):
            nodes.append({
                "id": "evidence_frames", "op": "image.tile@1.0",
                "inputs": {"frames": frame_ref},
                "params": {
                    "tile_width": 640,
                    "tile_height": 640,
                    "overlap": 0.2,
                    "include_full_frame": True,
                },
            })
        regions = {
            "whole": [0.0, 0.0, 1.0, 1.0],
            "head": [0.0, 0.0, 1.0, 0.35],
            "upper_body": [0.0, 0.15, 1.0, 0.7],
            "lower_body": [0.0, 0.45, 1.0, 1.0],
        }
        for index, (polarity, predicate) in enumerate(predicates, start=1):
            is_last = index == len(predicates)
            dimension = predicate.get("dimension")
            if dimension == "color":
                condition_id = f"constraint_{index}_color"
                color_objects_ref = current_ref
                carrier = predicate.get("carrier")
                if carrier:
                    carrier_config = CARRIER_CATALOG.get(
                        carrier, {"phrase": carrier, "color_mode": "dominant"}
                    )
                    carrier_phrase = carrier_config["phrase"]
                    carriers_id = f"constraint_{index}_carriers"
                    nodes.append({
                        "id": carriers_id, "op": "rex.ground@1.0",
                        "inputs": {"frames": frame_ref},
                        "params": {"targets": [{"label": carrier_phrase,
                                                "phrases": [carrier_phrase]}],
                                   "deduplicate_metric": "ios", "deduplicate_iou": 0.7},
                    })
                    color_objects_ref = f"${carriers_id}"
                nodes.append({
                    "id": condition_id, "op": "visual.color_fraction@1.0",
                    "inputs": {"frames": frame_ref, "objects": color_objects_ref},
                    "params": {
                        "color": predicate["value"],
                        "subject_region": [0.0, 0.0, 1.0, 1.0] if carrier
                                          else regions[predicate["region"]],
                        "min_fraction": COLOR_MIN_FRACTIONS[predicate["value"]],
                        "selection_mode": carrier_config["color_mode"] if carrier else "fraction",
                        "dominance_margin": 0.05,
                    },
                })
                condition_ref = f"${condition_id}"
                if carrier:
                    colored_id = f"constraint_{index}_colored_carriers"
                    matches_id = f"constraint_{index}_matches"
                    nodes.extend([
                        {"id": colored_id, "op": "filter.apply@1.0",
                         "inputs": {"objects": color_objects_ref, "condition": condition_ref},
                         "params": {}},
                        {"id": matches_id, "op": "spatial.associate@1.0",
                         "inputs": {"subjects": current_ref, "objects": f"${colored_id}"},
                         "params": {"relation": "best_owner", "threshold": 0.1}},
                    ])
                    condition_ref = f"${matches_id}"
                if polarity == "absent":
                    keep_id = f"constraint_{index}_keep"
                    nodes.append({"id": keep_id, "op": "logic.not@1.0",
                                  "inputs": {"condition": condition_ref}, "params": {}})
                    condition_ref = f"${keep_id}"
                filtered_id = "filtered" if is_last else f"filtered_{index}"
                nodes.append({
                    "id": filtered_id, "op": "filter.apply@1.0",
                    "inputs": {"objects": current_ref, "condition": condition_ref},
                    "params": {"output_label": label},
                })
                current_ref = f"${filtered_id}"
            elif dimension in {"size", "position"}:
                condition_id = f"constraint_{index}_geometry"
                nodes.append({
                    "id": condition_id, "op": "visual.geometry@1.0",
                    "inputs": {"objects": current_ref},
                    "params": {
                        "dimension": dimension,
                        "value": predicate["value"],
                        "size_mode": "relative",
                        "small_max_area": 0.02,
                        "large_min_area": 0.12,
                        "position_margin": 0.33,
                    },
                })
                condition_ref = f"${condition_id}"
                if polarity == "absent":
                    keep_id = f"constraint_{index}_keep"
                    nodes.append({"id": keep_id, "op": "logic.not@1.0",
                                  "inputs": {"condition": condition_ref}, "params": {}})
                    condition_ref = f"${keep_id}"
                filtered_id = "filtered" if is_last else f"filtered_{index}"
                nodes.append({
                    "id": filtered_id, "op": "filter.apply@1.0",
                    "inputs": {"objects": current_ref, "condition": condition_ref},
                    "params": {"output_label": label},
                })
                current_ref = f"${filtered_id}"
            else:
                matched_id = f"constraint_{index}_objects"
                association_id = f"constraint_{index}_matches"
                grounding_phrases = self._predicate_grounding_phrases(entity, predicate)
                nodes.extend([
                    {"id": matched_id, "op": "rex.ground@1.0",
                     "inputs": {
                         "frames": "$evidence_frames" if polarity == "required" else frame_ref
                     },
                     "params": {
                         "targets": [{
                             "label": predicate["sources"][0],
                             "phrases": grounding_phrases,
                         }],
                         "deduplicate_metric": "ios",
                         "deduplicate_iou": 0.7,
                     }},
                    {"id": association_id, "op": "spatial.associate@1.0",
                     "inputs": {"subjects": current_ref, "objects": f"${matched_id}"},
                     "params": {"relation": "overlap", "threshold": 0.5}},
                ])
                condition_ref = f"${association_id}"
                if polarity == "absent":
                    keep_id = f"constraint_{index}_keep"
                    nodes.append({"id": keep_id, "op": "logic.not@1.0",
                                  "inputs": {"condition": condition_ref}, "params": {}})
                    condition_ref = f"${keep_id}"
                filtered_id = "filtered" if is_last else f"filtered_{index}"
                nodes.append({
                    "id": filtered_id, "op": "filter.apply@1.0",
                    "inputs": {"objects": current_ref, "condition": condition_ref},
                    "params": {"output_label": label},
                })
                current_ref = f"${filtered_id}"
        nodes.append({
            "id": "draw", "op": "output.draw@1.0",
            "inputs": {"frames": frame_ref, "objects": current_ref}, "params": {},
        })
        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", entity["en"]).strip("_")[:48]
        if not safe_name or not safe_name[0].isalpha():
            safe_name = "entity_query_detector"
        spec = VisualSkillSpec.model_validate({
            "version": "0.1", "name": safe_name, "display_name": label,
            "original_instruction": instruction, "compile_status": "compiled",
            "input": {"accept": [media_type]}, "nodes": nodes,
            "outputs": {"media": "$draw", "objects": current_ref},
        })
        assert_valid_skill(spec, self.registry)
        return spec

    @staticmethod
    def _predicate_grounding_phrases(entity: dict, predicate: dict) -> list[str]:
        base = entity["en"].strip()
        if predicate["kind"] == "support_relation":
            article = "an" if predicate["object"].strip()[0].lower() in "aeiou" else "a"
            support_object = predicate["object"].strip()
            if support_object in {"surface", "seat", "chair", "bench", "ledge", "platform"}:
                relation_text = (
                    f"{predicate['subject_part'].strip()} resting on {article} {support_object}"
                )
            else:
                relation_text = (
                    f"{predicate['subject_part'].strip()} supported by {article} {support_object}"
                )
            return [
                f"{base} {predicate['action'].strip()} with {relation_text}"
            ]
        phrases = []
        for phrase in predicate["phrases"]:
            phrase = phrase.strip()
            if re.search(rf"\b{re.escape(base)}\b", phrase, re.I):
                full = phrase
            else:
                full = f"{base} {phrase}"
            if full not in phrases:
                phrases.append(full)
        return phrases[:2]

    def _fallback(self, instruction: str, media_type: str) -> VisualSkillSpec:
        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", instruction).strip("_")[:32]
        if not safe_name or not safe_name[0].isalpha():
            safe_name = "direct_grounding"
        nodes = []
        if media_type == "image":
            nodes.append({"id": "media", "op": "media.image@1.0", "inputs": {"media": "$input"}, "params": {}})
            frame_ref = "$media"
        else:
            nodes.extend([
                {"id": "media", "op": "media.video@1.0", "inputs": {"media": "$input"}, "params": {}},
                {"id": "frames", "op": "video.sample@1.0", "inputs": {"video": "$media"}, "params": {"fps": 2.0}},
            ])
            frame_ref = "$frames"
        nodes.extend([
            {"id": "resize", "op": "image.resize@1.0", "inputs": {"frames": frame_ref}, "params": {"long_side": 1280}},
            {"id": "objects", "op": "rex.ground@1.0", "inputs": {"frames": "$resize"},
             "params": {"targets": [{"label": instruction, "phrases": [instruction]}]}},
            {"id": "draw", "op": "output.draw@1.0", "inputs": {"frames": frame_ref, "objects": "$objects"}, "params": {}},
        ])
        spec = VisualSkillSpec.model_validate({
            "version": "0.1",
            "name": safe_name,
            "display_name": instruction[:80],
            "original_instruction": instruction,
            "compile_status": "degraded",
            "input": {"accept": [media_type]},
            "nodes": nodes,
            "outputs": {"media": "$draw"},
        })
        assert_valid_skill(spec, self.registry)
        return spec


__all__ = ["CompileResult", "DeepSeekPlanner"]

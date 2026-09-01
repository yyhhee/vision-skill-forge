from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from dotenv import load_dotenv
from openai import OpenAI

from core.business_capabilities import build_business_capability_registry
from core.registry import OperatorRegistry
from core.business_rule_draft import (
    NaturalLanguageBusinessDraft,
    normalize_business_draft_payload,
)
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
        self.business_capabilities = build_business_capability_registry(registry)
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

    def _repair_target_fields(self, ledger: dict, instruction: str) -> dict:
        """Repair malformed target identity without replacing LLM constraints.

        The deterministic text normalizer already knows common base entities
        such as person and vehicle.  Reuse only its target identity when the
        LLM omitted it or invented a source span; keep every LLM condition and
        the reviewable business rule unchanged.
        """

        target = dict(ledger.get("target") or {})
        span = str(target.get("source_span", "")).strip()
        concept = str(target.get("concept", "")).strip()
        phrases = [
            str(value).strip()
            for value in target.get("phrases", [])
            if str(value).strip()
        ]
        if span and span in instruction and concept and phrases:
            return ledger
        try:
            fallback = self.normalizer.infer_target(instruction)
        except Exception:
            fallback = {}
        if not concept and phrases:
            concept = phrases[0].lower()
            target["concept"] = concept
        if concept and not phrases:
            phrases = [concept.lower()]
            target["phrases"] = phrases
        if not fallback:
            aliases = {
                "person": ("人员", "行人", "工人", "人"),
                "vehicle": ("车辆", "汽车", "车"),
                "car": ("汽车", "车辆", "车"),
                "smoke": ("烟雾", "烟"),
                "fire": ("明火", "火焰", "火"),
                "garbage": ("垃圾", "废弃物"),
                "trash": ("垃圾", "废弃物"),
            }
            source_candidates = [
                label
                for item in target.get("classes", [])
                if isinstance(item, dict)
                for label in [str(item.get("label", "")).strip()]
                if label
            ]
            source_candidates.extend(aliases.get(concept.lower(), ()))
            source_candidates.append(concept)
            matched_span = next(
                (
                    candidate for candidate in source_candidates
                    if candidate and candidate in instruction
                ),
                "",
            )
            fallback = {
                "source_span": matched_span,
                "concept": concept,
                "phrases": phrases,
                "classes": target.get("classes", []),
            }
        if not span or span not in instruction:
            if fallback.get("source_span"):
                target["source_span"] = fallback["source_span"]
        if not concept:
            if fallback.get("concept"):
                target["concept"] = fallback["concept"]
        if not phrases:
            if fallback.get("phrases"):
                target["phrases"] = list(fallback["phrases"])
        target.setdefault("classes", list(fallback.get("classes", [])))
        ledger["target"] = target
        return ledger

    @staticmethod
    def _repair_business_target_labels(
        ledger: dict,
        business_payload: dict | None,
    ) -> dict:
        """Keep per-class labels when an LLM batches several targets.

        The semantic ledger may contain a useful ``target.classes`` mapping
        while the business draft represents the same detector as a list of
        bare phrases plus one display label.  Replacing that list with
        ``{label, phrases}`` entries is a generic normalization step: it
        preserves model categories for any multi-target task and prevents the
        compiler from collapsing every result into one branch label.
        """

        if not isinstance(business_payload, dict):
            return ledger
        target = ledger.get("target")
        classes = target.get("classes") if isinstance(target, dict) else None
        if not isinstance(classes, list):
            return ledger
        class_items = [
            item for item in classes
            if isinstance(item, dict)
            and str(item.get("label", "")).strip()
            and item.get("phrases")
        ]
        if len(class_items) < 2:
            return ledger

        def repair_conditions(items: list[dict]) -> None:
            for condition in items:
                if not isinstance(condition, dict):
                    continue
                if condition.get("capability_id") == "target.detect":
                    parameters = condition.setdefault("parameters", {})
                    values = parameters.get("targets")
                    if isinstance(values, list) and len(values) == len(class_items):
                        parameters["targets"] = [
                            {
                                "label": str(item["label"]).strip(),
                                "phrases": [
                                    str(phrase).strip()
                                    for phrase in item.get("phrases", [])
                                    if str(phrase).strip()
                                ],
                            }
                            for item in class_items
                        ]
                        # A single aggregate business label is no longer a
                        # safe output label when each model class is visible.
                        parameters.pop("business_label", None)
                repair_conditions(condition.get("children") or [])

        for branch in business_payload.get("branches", []):
            if isinstance(branch, dict):
                repair_conditions(branch.get("conditions") or [])
        return ledger

    @staticmethod
    def _repair_ground_surface_positions(
        ledger: dict,
        business_payload: dict | None,
    ) -> dict:
        """Treat an open ground surface as visible target evidence, not an ROI.

        A phrase such as "garbage on the ground" is directly observable.  It
        must not be turned into a spatial-membership card with ``inside=ground``:
        that parameter is boolean and a generic ground surface is not a user
        drawn region.
        """

        ground_values = {
            "ground", "on ground", "on the ground", "floor", "on floor",
            "on the floor", "pavement", "on pavement", "地面", "地上",
            "地板", "路面",
        }
        constraints = ledger.get("constraints")
        target = ledger.get("target")
        if not isinstance(constraints, list) or not isinstance(target, dict):
            return ledger
        ground_constraints = [
            item for item in constraints
            if isinstance(item, dict)
            and str(item.get("kind", "")).strip().lower() == "position"
            and str(item.get("value", "")).strip().lower() in ground_values
        ]
        phrases = [
            str(phrase).strip() for phrase in target.get("phrases", [])
            if str(phrase).strip()
        ]
        if not ground_constraints or not phrases:
            return ledger

        visual_phrase = next(
            (phrase for phrase in phrases if "ground" in phrase.lower()),
            f"{phrases[0]} on the ground",
        )
        target["phrases"] = [visual_phrase]
        ledger["target"] = target
        ground_spans = {
            str(item.get("source_span", "")).strip()
            for item in ground_constraints
        }
        ledger["constraints"] = [
            item for item in constraints if item not in ground_constraints
        ]
        ledger["unresolved"] = [
            item for item in ledger.get("unresolved", [])
            if str(item.get("source_span", "")).strip() not in ground_spans
        ]

        if not isinstance(business_payload, dict):
            return ledger
        source_keys: set[str] = set()

        def collect_ground_memberships(items: list[dict]) -> None:
            for condition in items:
                if not isinstance(condition, dict):
                    continue
                parameters = condition.get("parameters")
                inside = parameters.get("inside") if isinstance(parameters, dict) else None
                if (
                    condition.get("capability_id") == "spatial.membership"
                    and isinstance(inside, str)
                    and inside.strip().lower() in ground_values
                ):
                    source = str(parameters.get("source", ""))
                    if source.startswith("condition:"):
                        source_keys.add(source.split(":", 1)[1])
                collect_ground_memberships(condition.get("children") or [])

        def remove_ground_memberships(items: list[dict]) -> list[dict]:
            retained = []
            for condition in items:
                if not isinstance(condition, dict):
                    continue
                parameters = condition.get("parameters")
                inside = parameters.get("inside") if isinstance(parameters, dict) else None
                if (
                    condition.get("capability_id") == "spatial.membership"
                    and isinstance(inside, str)
                    and inside.strip().lower() in ground_values
                ):
                    continue
                if condition.get("key") in source_keys and condition.get("capability_id") == "target.detect":
                    condition.setdefault("parameters", {})["phrases"] = [visual_phrase]
                condition["children"] = remove_ground_memberships(
                    condition.get("children") or []
                )
                retained.append(condition)
            return retained

        for branch in business_payload.get("branches", []):
            if not isinstance(branch, dict):
                continue
            collect_ground_memberships(branch.get("conditions") or [])
        for branch in business_payload.get("branches", []):
            if isinstance(branch, dict):
                branch["conditions"] = remove_ground_memberships(
                    branch.get("conditions") or []
                )
        return ledger

    @staticmethod
    def _repair_business_region_positions(
        ledger: dict,
        business_payload: dict | None,
    ) -> dict:
        """Use a declared region resource for an open scene-position phrase.

        Canonical position values describe screen coordinates.  Phrases such
        as "on the road" instead describe a configurable semantic region.  If
        the same planner response declares exactly one matching region resource,
        convert that unsupported position to a normal region requirement rather
        than discarding the user's spatial constraint.
        """

        if not isinstance(business_payload, dict):
            return ledger
        constraints = ledger.get("constraints")
        if not isinstance(constraints, list):
            return ledger
        open_positions = [
            item
            for item in constraints
            if isinstance(item, dict)
            and str(item.get("kind", "")).strip().lower() == "position"
            and str(item.get("value", "")).strip().lower()
            not in ATTRIBUTE_CATALOG["position"]["values"]
        ]
        resources = business_payload.setdefault("resources", [])
        regions = [
            item
            for item in resources
            if isinstance(item, dict) and item.get("resource_type") == "region"
        ]
        if not regions and len(open_positions) == 1:
            position = open_positions[0]
            raw_role = str(position.get("value") or "scene area").strip().lower()
            role = re.sub(r"[^a-z0-9]+", "_", raw_role).strip("_") or "scene_area"
            media_types = list(dict.fromkeys(
                str(branch.get("media_type"))
                for branch in business_payload.get("branches", [])
                if isinstance(branch, dict)
                and branch.get("media_type") in {"image", "video"}
            )) or ["image"]
            region = {
                "key": role,
                "name": str(position.get("source_span") or raw_role),
                "resource_type": "region",
                "semantic_role": role,
                "media_types": media_types,
                "minimum_items": 1,
                "paired_region_key": None,
            }
            resources.append(region)
            regions = [region]

            def repair_conditions(items: list[dict]) -> None:
                for condition in items:
                    if not isinstance(condition, dict):
                        continue
                    parameters = condition.get("parameters")
                    if (
                        condition.get("capability_id") == "spatial.membership"
                        and isinstance(parameters, dict)
                        and parameters.get("scope") == "full_frame"
                    ):
                        parameters["scope"] = f"resource:{role}"
                    repair_conditions(condition.get("children") or [])

            for branch in business_payload.get("branches", []):
                if isinstance(branch, dict):
                    repair_conditions(branch.get("conditions") or [])
        if len(regions) != 1:
            return ledger
        region = regions[0]
        role = str(region.get("semantic_role") or region.get("key") or "area")
        repaired_spans: set[str] = set()
        for index, condition in enumerate(list(constraints)):
            if not isinstance(condition, dict):
                continue
            if str(condition.get("kind", "")).strip().lower() != "position":
                continue
            value = str(condition.get("value", "")).strip().lower()
            if value in ATTRIBUTE_CATALOG["position"]["values"]:
                continue
            span = str(condition.get("source_span", "")).strip()
            repaired_spans.add(span)
            constraints[index] = {
                "kind": "region_requirement",
                "value": {
                    "source": "manual",
                    "cardinality": (
                        "many" if int(region.get("minimum_items", 1)) > 1 else "one"
                    ),
                    "semantic_role": role,
                    "allowed_shapes": ["rectangle", "polygon"],
                },
                "source": condition.get("source") or span,
                "source_span": span,
                "phrases": [],
                "temporal": False,
            }
        if repaired_spans:
            ledger["unresolved"] = [
                item
                for item in ledger.get("unresolved", [])
                if str(item.get("source_span", "")).strip() not in repaired_spans
            ]
        return ledger

    @staticmethod
    def _repair_business_manual_directions(
        ledger: dict,
        business_payload: dict | None,
    ) -> dict:
        """Materialize manual direction references as editable resources."""

        if not isinstance(business_payload, dict):
            return ledger
        direction_constraints = [
            item
            for item in ledger.get("constraints", [])
            if isinstance(item, dict)
            and item.get("kind") == "direction_relation"
            and isinstance(item.get("value"), dict)
            and item["value"].get("reference_source") == "manual"
        ]
        if len(direction_constraints) != 1:
            return ledger
        direction_value = direction_constraints[0]["value"]
        resources = business_payload.setdefault("resources", [])
        if direction_value.get("reference_scope") == "per_named_region":
            has_region_constraint = any(
                isinstance(item, dict)
                and (
                    item.get("kind") == "region_requirement"
                    or item.get("kind") == "spatial_relation"
                    and isinstance(item.get("value"), dict)
                    and isinstance(item["value"].get("region"), dict)
                    and item["value"]["region"].get("source") == "manual"
                )
                for item in ledger.get("constraints", [])
            )
            business_regions = [
                item for item in resources
                if isinstance(item, dict) and item.get("resource_type") == "region"
            ]
            if not has_region_constraint and len(business_regions) == 1:
                region = business_regions[0]
                region_span = str(
                    direction_constraints[0].get("source")
                    or direction_constraints[0].get("source_span")
                    or region.get("name")
                    or "命名区域"
                )
                ledger.setdefault("constraints", []).insert(0, {
                    "kind": "region_requirement",
                    "value": {
                        "source": "manual",
                        "cardinality": "many",
                        "semantic_role": str(
                            region.get("semantic_role") or region.get("key") or "area"
                        ),
                        "allowed_shapes": ["rectangle", "polygon"],
                    },
                    "source": region_span,
                    "source_span": region_span,
                    "phrases": [],
                    "temporal": False,
                })

        # A scene-direction annotation is a resource, not an executable branch.
        # Drop branches that contain only a direction condition over full_frame;
        # the actual detection branch consumes the synthesized resource below.
        retained_branches = []
        removed_branch_keys: set[str] = set()
        for branch in business_payload.get("branches", []):
            conditions = branch.get("conditions", []) if isinstance(branch, dict) else []
            resource_only = bool(conditions) and all(
                isinstance(item, dict)
                and item.get("capability_id") == "motion.direction"
                and isinstance(item.get("parameters"), dict)
                and item["parameters"].get("source") == "full_frame"
                for item in conditions
            )
            if not resource_only:
                retained_branches.append(branch)
            elif isinstance(branch, dict) and branch.get("key"):
                removed_branch_keys.add(str(branch["key"]))
        business_payload["branches"] = retained_branches
        directions = [
            item for item in resources
            if isinstance(item, dict) and item.get("resource_type") == "direction"
        ]
        if not directions:
            region_keys = [
                str(item.get("key")) for item in resources
                if isinstance(item, dict)
                and item.get("resource_type") == "region"
                and item.get("key")
            ]
            media_types = list(dict.fromkeys(
                str(branch.get("media_type"))
                for branch in business_payload.get("branches", [])
                if isinstance(branch, dict)
                and branch.get("media_type") in {"image", "video"}
            )) or ["video"]
            directions = [{
                "key": "reference_direction",
                "name": "参考方向",
                "resource_type": "direction",
                "semantic_role": "reference_direction",
                "media_types": media_types,
                "minimum_items": 1,
                "paired_region_key": (
                    region_keys[0]
                    if direction_value.get("reference_scope") == "per_named_region"
                    and len(region_keys) == 1
                    else None
                ),
            }]
            resources.extend(directions)
        if len(directions) != 1:
            return ledger
        direction_ref = f"resource:{directions[0]['key']}"
        for pending in business_payload.get("pending_decisions", []):
            if not isinstance(pending, dict):
                continue
            affected = pending.get("affected_refs")
            if not isinstance(affected, list):
                continue
            pending["affected_refs"] = list(dict.fromkeys(
                direction_ref
                if isinstance(item, str)
                and item.startswith("condition:")
                and any(
                    item.split(":", 1)[1].startswith(f"{branch_key}.")
                    for branch_key in removed_branch_keys
                )
                else item
                for item in affected
            ))

        def repair_conditions(items: list[dict]) -> None:
            for condition in items:
                if not isinstance(condition, dict):
                    continue
                parameters = condition.get("parameters")
                if (
                    condition.get("capability_id") in {
                        "motion.direction", "motion.wrong_way"
                    }
                    and isinstance(parameters, dict)
                ):
                    if parameters.get("reference") in (None, "", "manual"):
                        parameters["reference"] = direction_ref
                    if condition.get("capability_id") == "motion.direction":
                        parameters.setdefault(
                            "relation", direction_value.get("relation", "opposite")
                        )
                        reverse_angle = parameters.pop("minimum_reverse_angle", None)
                        if reverse_angle is not None and parameters.get("angle") is None:
                            parameters["angle"] = reverse_angle
                repair_conditions(condition.get("children") or [])

        for branch in business_payload.get("branches", []):
            if isinstance(branch, dict):
                repair_conditions(branch.get("conditions") or [])
        return ledger

    @staticmethod
    def _business_orchestration_rules() -> str:
        return (
            "业务编排必须满足以下不变量："
            "一、主体血缘：每个条件必须通过 source/subject/object/attributes/equipment 引用可追溯到基础实体；"
            "禁止只靠条件名称暗示输入。"
            "二、分支边界：可独立判定、展示、保存或计时的主体链分别建立 branch；"
            "同一主体的多项属性保留在同一 branch。"
            "同一主体的证据复核：明确要求‘同一张/同一个/同一人’时，"
            "让属性或关系条件引用同一主体来源，并使用 subject.same_attributes 或等价归属关系；"
            "未明确同一主体时，不得擅自把不同目标绑定。"
            "三、关系完整性：同时依赖两个或以上主体的空间关系、归属、配对和缺失关系保持在同一 branch，"
            "不得拆断其依赖。"
            "命名区域边界：一句话明确出现区域1、区域2或多个不同命名区域，且各区域分别有条件时，"
            "为每个独立区域建立一个 branch，最终用 final_decision 的 AND/OR/N_OF_M 汇合；"
            "同一基础目标（例如 person）可以在多个区域 branch 中复用，系统会共享/去重执行来源。"
            "每个区域 branch 内的属性、数量、状态和空间条件必须通过 scope 或来源条件引用对应 resource:key；"
            "不要把区域1和区域2的条件塞进同一个 branch，也不要用一个全画面条件冒充多个区域条件。"
            "区域条件若共享同一检测目标，检测目标可作为无区域前置依赖；区域特有的后继条件必须绑定该区域，"
            "否则不得猜测归属，应写 pending_decisions 或 unresolved。"
            "四、逻辑分层：分支内部使用递归 AND/OR/NOT/N_OF_M；分支之间由 final_decision 或 patterns 组合；"
            "禁止用条件名称代替逻辑结构。"
            "自然语言连接词按语义映射：和、且、同时、都表示 AND/all；或、或者、任一表示 OR/any；"
            "至少 N 个表示 N_OF_M，并将 N 写入 required_count；连接词不能只保留在名称中。"
            "只出现一个条件时保持单条件，不得为了‘复核’凭空添加第二个条件；"
            "A AND B、A OR B、单独 A 或单独 B 都必须忠实落到条件树。"
            "颜色属性的双证据复核通过 attribute.color.verification_logic 表达："
            "普通‘某颜色目标’且未指定复核方式时使用 AND；"
            "明确要求颜色占比与模型属性语义证据同时满足时使用 AND，任一满足时使用 OR，"
            "只按颜色占比时使用 FRACTION_ONLY，只按模型属性语义证据时使用 SEMANTIC_ONLY。"
            "这四种模式是证据组合方式，不得把基础目标检测误写成独立业务条件。"
            "五、输出类型：entities/tracks/events/count/value 必须分别引用兼容的实体、轨迹、事件或测量来源；"
            "多分支最终判定是布尔来源，不能充当 entities 框来源。"
            "六、媒体与资源：图片不得包含轨迹或时序能力；人工区域和方向只声明 resource，"
            "业务条件通过 resource:key 引用。"
            "用户明确说‘02 标注/场景标注/手工画出的…区域’时，这个区域是人工资源："
            "必须声明 manual region_requirement，并让 spatial.membership 引用该 resource；"
            "不得再创建用于识别该区域表面、材质或场景名称的 target.detect。"
            "七、参数来源：用户未给出的阈值、时长、数量、区域数和方向不得猜测；"
            "需要确认的值写 pending_decisions。"
            "八、执行隔离：business_rule 只表达业务语义，不规划模型调用次数、抽帧、切片、去重或执行节点；"
            "执行优化由确定性编译器统一完成。"
            "同一媒体上的多个 target.detect 会由编译器合并为一次模型请求。声明这些可见证据时，"
            "必须按视觉证据的定位难度排序：先局部、较小、易遮挡或需要精确定位的关联物证据，"
            "再带关系/状态的组合语义证据，最后宽泛的主体或场景基础目标。"
            "例如关联物→‘主体与关联物处于某关系’→主体；这只是同一次请求内的类别顺序，"
            "不得因此创建多次模型调用。排序必须由证据在关系中的角色决定，不得按实体名称、"
            "语言、预置案例或固定类别表猜测。"
            "九、语义与规则的选择：单一、可直接看见、可用一句肯定描述表达且模型能够返回目标主体框的"
            "类别、外观、穿戴、姿态或状态，优先使用模型正向语义直接识别，"
            "例如已佩戴某物的主体、打开的门、冒烟的车辆；不得先凭像素、位置或宽高比自行推导简单语义。"
            "否定语义必须检测剥离否定后的正向语义，再用 NOT、缺失或排除能力表达，"
            "禁止把 not/without/no 发送给检测模型。"
            "使用 subject.missing_equipment 表达任意‘主体缺少关联物/关系’时，如果正向事实能由一个主体框表达，"
            "必须建立肯定式 target.detect 语义证据，并由 semantic_evidence 引用；"
            "正向短语应忠实使用 wearing、carrying、containing、loaded with、attached to、connected to 等实际关系，"
            "不得把所有关系统一改写成 wearing 或 with。"
            "若业务语义还要求关联物处于可定位的主体相对位置（例如头部、手部、足部、上/下半身），"
            "且关联物本身可被检测，verification_mode 必须选择“模型语义且关系复核”，并声明 wear_location；"
            "这样模型语义框与位置关系需同时成立，可区分携带、邻近和实际关联。"
            "若关系本身不能由稳定二维位置表达（例如远处锚点连接、内部状态），可使用“仅模型语义”。"
            "数量、命名区域、时序、速度、方向、精确几何、跨目标关系，以及模型无法用单一主体框完整表达的条件，"
            "使用确定性业务能力；用户明确要求复核时，才按用户语义组合模型证据与规则证据。"
            "若模型语义框和基础目标框需要归属，只做同一主体回绑，不得把归属规则冒充为新的业务条件。"
            "十、证据组合：基础检测、轨迹、区域或事件来源只是后继条件的数据依赖，不自动算作一条业务证据；"
            "最终判定中的 A/B 必须是可独立成立的测量、模型语义、关系、状态或时序证据。"
            "若业务能力资产暴露 verification_logic 或同类证据组合参数，优先用该参数表达 AND、OR、仅 A、仅 B；"
            "若资产没有内置复核参数，则把 A/B 建成显式条件并用递归 AND/OR/NOT/N_OF_M 组合。"
            "要求同一主体时，所有证据必须引用同一主体来源并配置归属关系，禁止跨主体拼接。"
            "以上规则按依赖和类型判断，不得根据具体实体名、颜色名、技能名或示例名称建立特殊分支。"
            "提示中的示例只用于说明字段格式，不构成编排规则。"
            "P01-P13 预置演示技能是回归样例而不是可复制的工作流模板；"
            "不得因为命中某个预置名称就照抄其分支、阈值、资源或执行步骤，"
            "只能依据当前自然语言和动态业务能力资产重新建立语义依赖。"
        )

    @staticmethod
    def _orchestration_slot_schema(slot: str) -> str:
        return {
            "condition": "branches[].conditions[] ATOM",
            "branch_time": "branches[].time",
            "pattern": "patterns[]",
            "condition_operator": "conditions[].operator/children",
            "result": "results[]",
        }[slot]

    def _business_capability_assets(self) -> list[dict]:
        assets = []
        for definition in self.business_capabilities.definitions():
            parameters = []
            for parameter in definition.parameters:
                item = {
                    "id": parameter.parameter_id,
                    "type": parameter.editor,
                    "required": parameter.required,
                    "level": parameter.level,
                }
                if parameter.default is not None:
                    item["default"] = parameter.default
                if parameter.choices:
                    item["choices"] = parameter.choices
                if parameter.minimum is not None:
                    item["minimum"] = parameter.minimum
                if parameter.maximum is not None:
                    item["maximum"] = parameter.maximum
                parameters.append(item)
            assets.append(
                {
                    "id": definition.capability_id,
                    "name": definition.display_name,
                    "category": definition.category,
                    "description": definition.description,
                    "schema_slot": self._orchestration_slot_schema(
                        definition.orchestration_slot
                    ),
                    "input_types": definition.accepted_source_types,
                    "output_type": definition.output_value_type,
                    "media": definition.media_requirements,
                    "resources": definition.resource_requirements,
                    "parameters": parameters,
                    "evidence": definition.evidence_contract,
                }
            )
        return assets

    def _planner_asset_contract(self) -> dict:
        return {
            "business_capability_assets": self._business_capability_assets(),
        }

    def _system_prompt(self) -> str:
        ontology = {
            "colors": sorted(set(COLOR_ALIASES.values())),
            "known_carriers": sorted(set(CARRIER_TEXT_ALIASES.values())),
            "attribute_dimensions": sorted(ATTRIBUTE_CATALOG),
        }
        asset_contract = self._planner_asset_contract()
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
            "对于未佩戴、未带、缺少等可穿戴物的否定条件，正向可见证据必须表达“该物已佩戴在主体对应部位”；"
            "不得把手持、携带、附近或仅落在主体大框内的物体视为已佩戴。"
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
            + self._business_orchestration_rules()
            + "编排前必须读取下方动态资产契约，并按依赖图自底向上选择业务能力："
            "每个 ATOM 的 capability_id 只能来自 business_capability_assets，且只能放入其 schema_slot；"
            "参数名、必填项、枚举、范围、媒体、资源、输入类型和输出类型必须与该资产完全一致。"
            "后继条件的来源类型必须兼容前驱输出类型；若当前资产无法无损表达用户语义，"
            "写入 pending_decisions 或 unresolved，禁止杜撰能力、参数、原子或默认阈值。"
            "执行原子资产不进入 LLM 上下文：业务能力注册时已经校验其编译配方引用的原子存在；"
            "业务组合原子由确定性编译器选择，系统基础原子按媒体、资源、证据和输出闭包自动补齐。"
            "不得在 business_rule 中输出执行原子 op、执行顺序、模型调用或系统基础节点；LLM 只编排业务能力。"
            "同一来源可供多个后继条件复用；不要为同一语义重复检测或重复筛选。"
            "每个独立业务主体建立一次基础实体来源，再以属性、关系、区域、数量、状态、运动或时间能力逐层收敛。"
            "parameters 中的来源用 condition:key 或 condition:branchKey.conditionKey；"
            "区域/方向用 resource:key，全画面用 full_frame。"
            "source/subject/object/attributes/equipment 不得写 full_frame；full_frame 仅可作为 scope。"
            "percentage 参数统一输出 0 到 100 的百分数；用户没有明确给出的 tuning 参数必须省略，采用资产默认值。"
            "顶层用户消息中的 requested_skill_display_name 只是技能名称，不是事件名、告警名或框标签，"
            "不得直接复制给 final_decision.name。final_decision.name 应根据业务语义生成简洁名称；"
            "用户明确给出事件/告警名称时原样采用，否则根据参与分支概括，例如多区域人员告警。"
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
            f"动态编排资产契约：{json.dumps(asset_contract, ensure_ascii=False, separators=(',', ':'))}。"
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
        require_business_draft: bool = False,
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
                ledger = self._repair_target_fields(ledger, text)
                business_payload = ledger.pop("business_rule", None)
                if require_business_draft and business_payload is None:
                    raise SemanticValidationError(
                        "缺少必需的顶层 business_rule；一句话创建必须同时返回可审核业务编排。"
                    )
                ledger = self._repair_business_target_labels(
                    ledger, business_payload
                )
                ledger = self._repair_ground_surface_positions(
                    ledger, business_payload
                )
                ledger = self._repair_business_region_positions(
                    ledger, business_payload
                )
                ledger = self._repair_business_manual_directions(
                    ledger, business_payload
                )
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
                        normalize_business_draft_payload(business_payload)
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
                # Syntax failures usually benefit from one clean retry.  A
                # structurally valid but semantically invalid ledger gets the
                # third planned attempt so one malformed target/span response
                # cannot force the user into manual JSON repair.
                if attempt >= 3 or (
                    attempt >= 2
                    and (
                        isinstance(exc, json.JSONDecodeError)
                        or (
                            isinstance(exc, SemanticValidationError)
                            and str(exc) == "LLM returned an empty semantic ledger"
                        )
                    )
                ):
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

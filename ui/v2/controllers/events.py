"""EventRuleController: extracted V2 responsibilities, preserving public method signatures."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import gradio as gr

from application.v2.support import _variant_key
from core.document_hashes import refresh_document_hashes
from core.editor_schema import (
    ResolvableValue,
)
from core.schema import SkillPackage
from core.validator import validate_skill_package
from core.video_sampling import normalize_end_seconds


class EventRuleController:
    def read_execution_controls(
        self, effective_json: str, media_type: str
    ) -> dict[str, Any] | None:
        """Read the actual visible execution controls from one effective DAG."""

        if not (effective_json or "").strip():
            return None
        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        variant = package.variants.get(key)
        if variant is None or variant.status == "unsupported":
            raise gr.Error(f"当前技能没有可配置的 {key} variant")
        resize = next(
            (node for node in variant.nodes if node.op.startswith("image.resize@")),
            None,
        )
        if resize is None:
            raise gr.Error("当前 variant 没有显式 image.resize 节点")
        resize_params = dict(self.registry.require(resize.op).defaults)
        resize_params.update(resize.params)
        tile = next(
            (
                node
                for node in variant.nodes
                if node.op.startswith("image.tile@")
                and node.inputs.get("frames") == f"${resize.id}"
            ),
            None,
        )
        tile_params = dict(self.registry.require("image.tile@1.1").defaults)
        if tile is not None:
            tile_params.update(tile.params)
        dedup = next(
            (node for node in variant.nodes if node.op == "objects.deduplicate@1.0"),
            None,
        )
        dedup_params = dict(self.registry.require("objects.deduplicate@1.0").defaults)
        if dedup is not None:
            dedup_params.update(dedup.params)
        result: dict[str, Any] = {
            "resize_mode": resize_params["mode"],
            "long_side": resize_params["long_side"],
            "width": resize_params["width"],
            "height": resize_params["height"],
            "interpolation": resize_params["interpolation"],
            "tile_enabled": tile is not None,
            "tile_width": tile_params["tile_width"],
            "tile_height": tile_params["tile_height"],
            "overlap_x": tile_params["overlap_x"],
            "overlap_y": tile_params["overlap_y"],
            "include_full_frame": tile_params["include_full_frame"],
            "dedup_metric": dedup_params["metric"],
            "dedup_threshold": dedup_params["threshold"],
        }
        if key == "video":
            sample = next(
                (node for node in variant.nodes if node.op.startswith("video.sample@")),
                None,
            )
            if sample is None:
                raise gr.Error("video variant 没有显式抽帧节点")
            sample_params = dict(self.registry.require(sample.op).defaults)
            sample_params.update(sample.params)
            sample_mode = sample_params["mode"]
            if sample_mode == "frame_step" and sample_params["frame_step"] == 1:
                sample_mode = "original_fps"
            result.update(
                {
                    "sample_mode": sample_mode,
                    "fps": sample_params["fps"],
                    "interval_seconds": sample_params["interval_seconds"],
                    "frame_step": sample_params["frame_step"],
                    "start_seconds": sample_params["start_seconds"],
                    "end_seconds": normalize_end_seconds(sample_params["end_seconds"]),
                    "max_frames": sample_params["max_frames"],
                }
            )
        return result

    def read_temporal_controls(
        self, effective_json: str, media_type: str
    ) -> list[dict[str, Any]]:
        """Return every configurable duration event from one executable variant."""

        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        variant = package.variants.get(key)
        if variant is None or variant.status == "unsupported":
            return []
        controls = []
        for node in variant.nodes:
            if node.op not in {"temporal.persist@1.0", "event.from_condition@1.0"}:
                continue
            defaults = self.registry.require(node.op).defaults
            params = {**defaults, **node.params}
            event_label, condition_summary = self.temporal_rule_summary(variant, node)
            seconds = float(params["seconds"])
            control = {
                "node_id": node.id,
                "label": f"持续事件：{event_label}",
                "event_label": event_label,
                "condition_summary": condition_summary,
                "duration_summary": f"连续满足上述条件 {seconds:g} 秒后触发",
                "seconds": seconds,
                "gap_tolerance_seconds": float(params["gap_tolerance_seconds"]),
                "trigger_mode": params["trigger_mode"],
            }
            controls.append(control)
        return controls

    @staticmethod
    def temporal_rule_summary(variant, event_node) -> tuple[str, str]:
        """Describe the explicit condition DAG that a duration event consumes."""

        nodes = {node.id: node for node in variant.nodes}

        def node_for(reference: str | None):
            if not isinstance(reference, str) or not reference.startswith("$"):
                return None
            return nodes.get(reference[1:])

        event_ref = f"${event_node.id}"
        alert = next(
            (
                node
                for node in variant.nodes
                if node.op == "output.alert@1.0"
                and node.inputs.get("events") == event_ref
            ),
            None,
        )
        event_label = (
            (alert.params.get("label") if alert is not None else None)
            or event_node.params.get("label")
            or event_node.id
        )

        def describe(node, visited: set[str]) -> str:
            if node is None or node.id in visited:
                return "上游条件"
            visited = {*visited, node.id}
            if node.op == "logic.all@1.0":
                conditions = node.inputs.get("conditions", [])
                if not isinstance(conditions, list):
                    conditions = [conditions]
                return " 且 ".join(
                    describe(node_for(reference), visited) for reference in conditions
                )
            if node.op == "logic.any@1.0":
                conditions = node.inputs.get("conditions", [])
                if not isinstance(conditions, list):
                    conditions = [conditions]
                return " 或 ".join(
                    describe(node_for(reference), visited) for reference in conditions
                )
            if node.op == "logic.not@1.0":
                return (
                    "不满足（"
                    + describe(node_for(node.inputs.get("condition")), visited)
                    + "）"
                )
            if node.op == "filter.apply@1.0":
                return "检测到" + str(
                    node.params.get("output_label") or event_label or "目标"
                )
            if node.op == "objects.relabel@1.0":
                # Relabeling changes only the user-facing evidence name.  It is
                # transparent to the condition DAG and must not replace an
                # event summary with an implementation node id.
                return describe(node_for(node.inputs.get("objects")), visited)
            if node.op == "reduce.exists@1.0":
                source = node_for(node.inputs.get("sets"))
                return "存在" + describe(source, visited)
            if node.op == "track.iou@1.0":
                return describe(node_for(node.inputs.get("objects")), visited)
            if node.op == "logic.compare@1.0":
                measurement = node_for(node.inputs.get("left"))
                measure_labels = {
                    "measure.count@1.0": "全画面目标数量",
                    "measure.region_count@1.0": "每个命名区域内目标数量",
                    "measure.speed@1.0": "目标速度",
                    "measure.region_speed@1.0": "每个命名区域内目标速度",
                }
                subject = measure_labels.get(
                    measurement.op if measurement is not None else "", "数值"
                )
                value = node.params.get("value", node.params.get("threshold"))
                if value is None:
                    return subject
                return f"{subject} {node.params.get('operator', '>=')} {value:g}"
            if node.op == "spatial.inside@1.0":
                region = node_for(node.inputs.get("region"))
                if region is not None and region.op == "region.full_frame@1.0":
                    return describe(node_for(node.inputs.get("objects")), visited)
                return "目标位于标注区域内"
            if node.op == "spatial.associate@1.0":
                relation_labels = {
                    "overlap": "目标框重叠",
                    "mutual_match": "目标双向匹配",
                    "inside": "目标位于关联框内",
                    "contains": "目标包含关联框",
                    "near": "目标彼此接近",
                    "best_owner": "目标唯一归属关联框",
                    "source_entity": "目标与来源实体关联",
                }
                relation = relation_labels.get(
                    node.params.get("relation"), "目标空间关联"
                )
                threshold = node.params.get("threshold")
                summary = (
                    f"目标关联：{relation}（阈值 {float(threshold):g}）"
                    if isinstance(threshold, (int, float))
                    else f"目标关联：{relation}"
                )
                subject_node = node_for(node.inputs.get("subjects"))
                if subject_node is not None and subject_node.op.startswith("track."):
                    summary += "；按目标轨迹逐帧判断"
                return summary
            if node.op == "logic.heading_by_lane@1.0":
                return "按车道参考方向判断相反方向"
            return node.id

        return event_label, describe(
            node_for(event_node.inputs.get("condition")), set()
        )

    def temporal_rules_markdown(self, effective_json: str, media_type: str) -> str:
        """Render duration rules as the user-facing event decision contract."""

        if not effective_json:
            return "### 事件判定\n生成或加载技能后，这里会说明是否需要配置持续时间。"
        controls = self.read_temporal_controls(effective_json, media_type)
        if not controls:
            return (
                "### 事件判定\n"
                "当前流程没有持续事件；图片检测或单帧阈值判断不需要设置持续时间。"
            )
        rows = [
            (
                f"- **{item['event_label']}**：{item['condition_summary']}；"
                f"{item['duration_summary']}。"
            )
            for item in controls
        ]
        return (
            "### 事件判定\n"
            "当前流程存在持续事件；需要时在上方「事件规则编辑」修改持续时间。\n"
            + "\n".join(rows)
        )

    def configuration_guidance_markdown(
        self, effective_json: str, media_type: str
    ) -> str:
        """Explain the existing event atoms and required scene input without editing them."""

        if not effective_json:
            return "### 识别出的原子能力\n生成或加载技能后，这里会说明下一步配置。"
        package = SkillPackage.model_validate_json(effective_json)
        controls = self.read_event_rule_controls(effective_json, media_type)
        _, slot_rows = self.annotation_slots(effective_json, media_type)
        fallen_pose = any(
            constraint.kind == "pose"
            and str(constraint.value).strip().lower()
            in {"fallen", "fall", "lying", "lie"}
            for constraint in package.semantic_ir.constraints
        )
        lines = [
            "### 识别出的原子能力",
            f"**原文约束**：{package.original_instruction or '未提供'}",
        ]
        if fallen_pose:
            lines.append(
                "- 当前规则判定的是**倒地/躺卧可见状态**：人员候选与倒地人员证据在同一画面关联；"
                "不会推断站立或行走到倒地的动作过程。"
            )
        if not controls:
            if fallen_pose:
                lines.append(
                    "- 当前技能没有事件阈值；检测结果可直接在“04 运行与结果”查看。"
                    "如需告警，请在描述中明确“持续至少 N 秒后触发”。"
                )
            else:
                lines.append(
                    "- 当前技能没有事件阈值；检测结果可直接在“04 运行与结果”查看。"
                )
        for control in controls:
            categories = "、".join(control["categories"]) or "当前检测目标"
            if control["condition_kind"] == "direction":
                condition = "按车道参考方向判断相反方向"
            else:
                parts = [
                    item["measure"]
                    .replace("目标", "")
                    .replace("每个命名区域内", "每个命名区域 ")
                    + f" {item['operator']} {item['value']:g}"
                    for item in control["comparisons"]
                ]
                connector = " AND " if control["logic"] == "all" else " OR "
                condition = connector.join(parts) or control["condition_summary"]
            lines.extend(
                [
                    f"\n**{control['event_label']}**",
                    f"- {categories} → {condition} → 持续 {control['seconds']:g} 秒 → 告警“{control['event_label']}”。",
                    f"- {control['atom_summary']}",
                ]
            )
        if slot_rows:
            labels = "、".join(row["label"] for row in slot_rows if row["active"])
            lines.append(
                f"\n**下一步配置**：先到“02 标注”配置 {labels}；"
                f"再到“03 审核”调整上述阈值、持续与告警。"
            )
        else:
            automatic_regions = self._automatic_region_labels(
                effective_json, media_type
            )
            if automatic_regions:
                lines.append(
                    "\n**下一步配置**：02 标注显示的区域由检测结果自动生成（"
                    + "、".join(automatic_regions)
                    + "），不可手工删除或编辑；如需调整规则，到“03 审核”修改后运行。"
                )
            else:
                lines.append(
                    "\n**下一步配置**：无需场景标注；如需调整规则，到“03 审核”修改后运行。"
                )
        return "\n".join(lines)

    def read_event_rule_controls(
        self, effective_json: str, media_type: str
    ) -> list[dict[str, Any]]:
        """Read the editable atoms that form each event rule in one DAG."""

        if not effective_json:
            return []
        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        variant = package.variants.get(key)
        if variant is None or variant.status == "unsupported":
            return []
        nodes = {node.id: node for node in variant.nodes}
        single_region_labels = {
            slot.binding.node_id: slot.label
            for slot in variant.configuration_slots
            if slot.kind == "region"
        }

        def node_for(reference: str | None):
            if not isinstance(reference, str) or not reference.startswith("$"):
                return None
            return nodes.get(reference[1:])

        def first_ground(node, visited: set[str] | None = None):
            if node is None:
                return None
            visited = set() if visited is None else visited
            if node.id in visited:
                return None
            if node.op == "rex.ground@1.1":
                return node
            visited.add(node.id)
            for reference in node.inputs.values():
                references = reference if isinstance(reference, list) else [reference]
                for item in references:
                    ground = first_ground(node_for(item), visited)
                    if ground is not None:
                        return ground
            return None

        candidate_entries: list[dict[str, str]] = []
        candidate_by_key: dict[str, dict[str, str]] = {}
        for ground in variant.nodes:
            if ground.op != "rex.ground@1.1":
                continue
            for index, target in enumerate(ground.params.get("targets", [])):
                if not isinstance(target, dict) or not target.get("label"):
                    continue
                entry = {
                    "key": f"{ground.id}:{index}",
                    "label": str(target["label"]),
                }
                candidate_entries.append(entry)
                candidate_by_key[entry["key"]] = entry

        def label_filter_in_path(node, visited: set[str] | None = None):
            if node is None:
                return None
            visited = set() if visited is None else visited
            if node.id in visited:
                return None
            visited.add(node.id)
            if node.op == "objects.filter_by_label@1.0":
                labels = node.params.get("labels", [])
                if isinstance(labels, list) and len(labels) == 1:
                    return str(labels[0])
            for reference in node.inputs.values():
                references = reference if isinstance(reference, list) else [reference]
                for item in references:
                    label = label_filter_in_path(node_for(item), visited)
                    if label is not None:
                        return label
            return None

        def candidate_for_reference(reference: str | None):
            node = node_for(reference)
            ground = first_ground(node)
            if ground is None:
                return None
            targets = [
                item
                for item in ground.params.get("targets", [])
                if isinstance(item, dict) and item.get("label")
            ]
            selected_label = label_filter_in_path(node)
            if selected_label is not None:
                return next(
                    (
                        candidate_by_key.get(f"{ground.id}:{index}")
                        for index, target in enumerate(targets)
                        if str(target["label"]) == selected_label
                    ),
                    None,
                )
            if len(targets) == 1:
                return candidate_by_key.get(f"{ground.id}:0")
            return None

        association_labels = {
            "overlap": "目标框重叠",
            "mutual_match": "目标框双向匹配",
            "inside": "目标位于关联框内",
            "contains": "目标包含关联框",
            "near": "目标彼此接近",
            "best_owner": "目标唯一归属关联框",
            "source_entity": "目标与来源实体关联",
        }

        def event_associations(condition):
            associations = []
            pending = [condition]
            visited: set[str] = set()
            while pending:
                node = pending.pop()
                if node is None or node.id in visited:
                    continue
                visited.add(node.id)
                if node.op == "spatial.associate@1.0":
                    subject = candidate_for_reference(node.inputs.get("subjects"))
                    object_ = candidate_for_reference(node.inputs.get("objects"))
                    params = {
                        **self.registry.require(node.op).defaults,
                        **node.params,
                    }
                    threshold = params.get("threshold")
                    if (
                        params.get("relation")
                        in {"overlap", "mutual_match", "inside", "contains"}
                        and subject is not None
                        and object_ is not None
                        and isinstance(threshold, (int, float))
                    ):
                        associations.append(
                            {
                                "node_id": node.id,
                                "label": association_labels.get(
                                    params.get("relation"), "目标空间关联"
                                ),
                                "relation": str(params.get("relation", "overlap")),
                                "threshold": float(threshold),
                                "subject": dict(subject),
                                "object": dict(object_),
                                "candidates": [
                                    dict(item) for item in candidate_entries
                                ],
                            }
                        )
                for reference in node.inputs.values():
                    references = (
                        reference if isinstance(reference, list) else [reference]
                    )
                    pending.extend(node_for(item) for item in references)
            return associations

        measure_labels = {
            "measure.count@1.0": "全画面目标数量",
            "measure.region_count@1.0": "每个命名区域内目标数量",
            "measure.speed@1.0": "目标速度",
            "measure.region_speed@1.0": "每个命名区域内目标速度",
        }
        scope_labels = {
            "global": "全画面",
            "region": "每个命名区域（在“02 标注”绘制或修改区域）",
            "track": "每条目标轨迹",
        }
        controls = []
        for event in variant.nodes:
            if event.op not in {"temporal.persist@1.0", "event.from_condition@1.0"}:
                continue
            condition = node_for(event.inputs.get("condition"))
            if condition is None:
                continue
            logic_node = (
                condition
                if condition.op in {"logic.all@1.0", "logic.any@1.0"}
                else None
            )
            references = (
                condition.inputs.get("conditions", [])
                if logic_node
                else [f"${condition.id}"]
            )
            if not isinstance(references, list):
                references = [references]
            comparisons = []
            state_conditions = []
            category_node = None
            region_ids: list[str] = []
            region_entries: list[dict[str, str]] = []
            for reference in references:
                comparison = node_for(reference)
                if comparison is None:
                    continue
                if comparison.op != "logic.compare@1.0":
                    if comparison.op not in {"logic.all@1.0", "logic.any@1.0"}:
                        if comparison.op == "visual.geometry@1.0":
                            # Geometry guards are part of a state/pose rule,
                            # not a second editable event state card.
                            continue
                        definition = self.registry.get(comparison.op)
                        state_conditions.append(
                            {
                                "node_id": comparison.id,
                                "op": comparison.op,
                                "label": definition.display_name
                                if definition
                                else comparison.op,
                                "params": dict(comparison.params),
                            }
                        )
                    continue
                measurement = node_for(comparison.inputs.get("left"))
                value = comparison.params.get(
                    "value", comparison.params.get("threshold")
                )
                if measurement is None or value is None:
                    continue
                comparison_data = {
                    "node_id": comparison.id,
                    "measure": measure_labels.get(measurement.op, measurement.id),
                    "operator": comparison.params.get("operator", ">="),
                    "value": float(value),
                }
                if comparison.params.get("key_filter") is not None:
                    comparison_data["region_id"] = str(comparison.params["key_filter"])
                if comparison.params.get("overrides"):
                    comparison_data["overrides"] = dict(comparison.params["overrides"])
                if comparison.params.get("operator_overrides"):
                    comparison_data["operator_overrides"] = dict(
                        comparison.params["operator_overrides"]
                    )
                regions = node_for(measurement.inputs.get("regions"))
                if regions is not None and regions.op == "region.manual_set@1.0":
                    region_entries = [
                        {
                            "id": str(item["id"]),
                            "label": str(item.get("label") or item["id"]),
                        }
                        for item in regions.params.get("regions", [])
                        if isinstance(item, dict) and item.get("id")
                    ]
                    region_ids = [item["id"] for item in region_entries]
                elif regions is not None and regions.op == "region.manual@1.0":
                    comparison_data["fixed_region"] = {
                        "id": regions.id,
                        "label": single_region_labels.get(regions.id, regions.id),
                    }
                if category_node is None:
                    category_node = first_ground(measurement)
                if region_entries:
                    comparison_data.setdefault("region_id", None)
                    comparison_data["region_choices"] = [
                        dict(item) for item in region_entries
                    ]
                comparisons.append(comparison_data)
            if category_node is None:
                category_node = first_ground(condition)
            alert = next(
                (
                    node
                    for node in variant.nodes
                    if node.op == "output.alert@1.0"
                    and node.inputs.get("events") == f"${event.id}"
                ),
                None,
            )
            categories = [
                target["label"]
                for target in (
                    category_node.params.get("targets", []) if category_node else []
                )
                if isinstance(target, dict) and target.get("label")
            ]
            semantic_target_label = package.semantic_ir.target.source_span.strip()
            legacy_display_label = (
                not package.semantic_ir.target.classes
                and categories == [package.display_name]
                and bool(semantic_target_label)
            )
            if legacy_display_label:
                categories = [semantic_target_label]
            event_label = (
                (alert.params.get("label") if alert is not None else None)
                or event.params.get("label")
                or event.id
            )
            params = {**self.registry.require(event.op).defaults, **event.params}
            scope = params.get("scope", "global")
            scope_choices = [scope]
            is_direction = condition.op == "logic.heading_by_lane@1.0"
            region_references = {}
            if is_direction:
                lane_node = node_for(condition.inputs.get("lanes"))
                if lane_node is not None and lane_node.op == "region.manual_set@1.0":
                    region_entries = [
                        {
                            "id": str(item["id"]),
                            "label": str(item.get("label") or item["id"]),
                        }
                        for item in lane_node.params.get("regions", [])
                        if isinstance(item, dict) and item.get("id")
                    ]
                    region_ids = [item["id"] for item in region_entries]
                reference_node = node_for(condition.inputs.get("references"))
                if (
                    reference_node is not None
                    and reference_node.op == "direction.manual_set@1.0"
                ):
                    configured_reference_keys = {
                        str(item.get("key"))
                        for item in reference_node.params.get("directions", [])
                        if isinstance(item, dict) and item.get("key")
                    }
                    region_references = {
                        item["id"]: (
                            "已配置参考箭头"
                            if item["id"] in configured_reference_keys
                            else "待在 02 标注参考箭头"
                        )
                        for item in region_entries
                    }
            condition_kind = (
                "direction"
                if is_direction
                else "comparison"
                if comparisons and not state_conditions
                else "state"
                if state_conditions and not comparisons
                else "composite"
            )
            condition_summary = self.temporal_rule_summary(variant, event)[1]
            atom_summary = (
                "这是方向/空间关系，不是数量或速度比较；需要在“02 标注”配置命名车道区域和参考方向箭头。"
                if is_direction
                else (
                    "这是布尔/状态条件原子；系统按上游目标关联或状态判断逐帧计算，"
                    "可在本页修改持续时间、允许中断、触发方式和告警。"
                    if condition_kind == "state"
                    else "这是由状态与数值原子组合的复合条件；可分别调整数值卡和整组事件策略。"
                    if condition_kind == "composite"
                    else (
                        f"统计范围：{scope_labels.get(scope, str(scope))}；"
                        "可在本页修改类别、阈值、逻辑、持续与告警。"
                    )
                )
            )
            regional_parameters = []
            for comparison in comparisons:
                regional_parameters.extend(
                    [
                        {
                            "id": f"{comparison['node_id']}::operator",
                            "node_id": comparison["node_id"],
                            "parameter": "operator",
                            "label": f"{comparison['measure']}：比较方式",
                            "editor": "select",
                            "choices": [">", ">=", "==", "!=", "<=", "<"],
                            "default": comparison["operator"],
                            "overrides": comparison.get("operator_overrides", {}),
                            "storage": "operator_overrides",
                        },
                        {
                            "id": f"{comparison['node_id']}::value",
                            "node_id": comparison["node_id"],
                            "parameter": "value",
                            "label": f"{comparison['measure']}：比较值",
                            "editor": "number",
                            "default": comparison["value"],
                            "overrides": comparison.get("overrides", {}),
                            "storage": "overrides",
                        },
                    ]
                )
            if is_direction:
                direction_defaults = {
                    **self.registry.require(condition.op).defaults,
                    **condition.params,
                }
                direction_overrides = direction_defaults.get("scope_overrides", {})
                for parameter, label, editor, choices in (
                    ("threshold", "方向相反判定阈值", "number", []),
                    (
                        "relation",
                        "方向关系",
                        "select",
                        ["opposite", "aligned"],
                    ),
                ):
                    regional_parameters.append(
                        {
                            "id": f"{condition.id}::{parameter}",
                            "node_id": condition.id,
                            "parameter": parameter,
                            "label": label,
                            "editor": editor,
                            "choices": choices,
                            "default": direction_defaults[parameter],
                            "overrides": {
                                key: value[parameter]
                                for key, value in direction_overrides.items()
                                if isinstance(value, dict) and parameter in value
                            },
                            "storage": "scope_overrides",
                        }
                    )
                event_overrides = params.get("scope_overrides", {})
                for parameter, label, editor, choices in (
                    ("seconds", "逆行持续时间", "number", []),
                    ("gap_tolerance_seconds", "允许短暂中断", "number", []),
                    (
                        "trigger_mode",
                        "区域触发方式",
                        "select",
                        ["once", "repeat"],
                    ),
                ):
                    regional_parameters.append(
                        {
                            "id": f"{event.id}::{parameter}",
                            "node_id": event.id,
                            "parameter": parameter,
                            "label": label,
                            "editor": editor,
                            "choices": choices,
                            "default": params[parameter],
                            "overrides": {
                                key: value[parameter]
                                for key, value in event_overrides.items()
                                if isinstance(value, dict) and parameter in value
                            },
                            "storage": "scope_overrides",
                        }
                    )
            control = {
                "event_id": event.id,
                "event_label": event_label,
                "scope": scope,
                "scope_label": scope_labels.get(scope, str(scope)),
                "scope_choices": scope_choices,
                "category_node_id": category_node.id if category_node else None,
                "categories": categories,
                "selected_categories": categories,
                "comparisons": comparisons,
                "logic_node_id": logic_node.id if logic_node else None,
                "logic": (
                    "all"
                    if logic_node is None
                    else logic_node.op.split(".")[1].split("@")[0]
                ),
                "condition_kind": condition_kind,
                "condition_summary": condition_summary,
                "atom_summary": atom_summary,
                "seconds": float(params["seconds"]),
                "gap_tolerance_seconds": float(params["gap_tolerance_seconds"]),
                "trigger_mode": params["trigger_mode"],
                "alert_node_id": alert.id if alert is not None else None,
                "regional_parameters": regional_parameters,
            }
            if region_references:
                control["region_references"] = region_references
            if state_conditions:
                control["state_conditions"] = state_conditions
                if len(state_conditions) == 1:
                    control["state_condition"] = state_conditions[0]
            associations = event_associations(condition)
            if associations:
                control["associations"] = associations
            if region_ids:
                control["region_ids"] = region_ids
                control["regions"] = region_entries
            controls.append(control)
        return controls

    def apply_event_rule_control(
        self,
        effective_json: str,
        media_type: str,
        event_id: str,
        category_node_id: str | None,
        categories: list[str] | None,
        comparison_ids: list[str],
        comparison_operators: list[str],
        comparison_values: list[float],
        logic_mode: str,
        seconds: float,
        gap_tolerance_seconds: float,
        trigger_mode: str,
        alert_label: str,
        scope: str | None = None,
        region_overrides: dict[str, dict[str, float]] | None = None,
        region_operator_overrides: dict[str, dict[str, str]] | None = None,
        region_bindings: list[str | None] | None = None,
    ) -> str:
        """Apply selected event atoms while preserving DAG wiring and scene slots."""

        if logic_mode not in {"all", "any"}:
            raise gr.Error("条件关系必须是 all 或 any")
        if trigger_mode not in {"once", "repeat"}:
            raise gr.Error("触发方式必须是 once 或 repeat")
        if float(seconds) < 0 or float(gap_tolerance_seconds) < 0:
            raise gr.Error("持续时间和允许中断时间不能小于 0")
        if not alert_label or not alert_label.strip():
            raise gr.Error("请填写告警名称")
        if not (
            len(comparison_ids) == len(comparison_operators) == len(comparison_values)
        ):
            raise gr.Error("比较条件参数数量不一致")
        if region_bindings is not None and len(region_bindings) != len(comparison_ids):
            raise gr.Error("条件对应区域数量必须与比较条件一致")
        allowed_operators = {">", ">=", "=", "<=", "<", "==", "!="}
        if any(operator not in allowed_operators for operator in comparison_operators):
            raise gr.Error("比较符必须是 >、>=、=、<=、<、== 或 !=")
        comparison_operators = [
            "==" if operator == "=" else operator for operator in comparison_operators
        ]

        current = next(
            (
                item
                for item in self.read_event_rule_controls(effective_json, media_type)
                if item["event_id"] == event_id
            ),
            None,
        )
        if current is None:
            raise gr.Error("找不到要编辑的事件规则")
        permitted_comparisons = {item["node_id"] for item in current["comparisons"]}
        if not set(comparison_ids).issubset(permitted_comparisons):
            raise gr.Error("比较条件不是当前事件规则的一部分")
        if current["logic_node_id"] is None and logic_mode != "all":
            raise gr.Error("只有一个条件时不能切换为 OR")
        if category_node_id != current["category_node_id"]:
            raise gr.Error("目标类别节点不是当前事件规则的一部分")
        requested_scope = scope or current["scope"]
        if requested_scope not in current["scope_choices"]:
            raise gr.Error("当前事件规则不能切换到所选统计范围")
        region_overrides = region_overrides or {}
        if not isinstance(region_overrides, dict):
            raise gr.Error("按区域覆盖必须是区域 ID 到条件阈值的映射")
        region_operator_overrides = region_operator_overrides or {}
        if not isinstance(region_operator_overrides, dict):
            raise gr.Error("区域比较符必须是区域 ID 到条件比较符的映射")
        allowed_regions = set(current.get("region_ids", []))
        if region_bindings is not None:
            unknown_bindings = {
                region_id for region_id in region_bindings if region_id is not None
            } - allowed_regions
            if unknown_bindings:
                raise gr.Error(f"未知的命名区域：{next(iter(unknown_bindings))}")
        override_by_comparison: dict[str, dict[str, float]] = {}
        operator_override_by_comparison: dict[str, dict[str, str]] = {}
        for region_id, values in region_overrides.items():
            if region_id not in allowed_regions:
                raise gr.Error(f"未知的命名区域：{region_id}")
            if not isinstance(values, dict):
                raise gr.Error(f"区域 {region_id} 的覆盖值必须按条件填写")
            for comparison_id, value in values.items():
                if comparison_id not in permitted_comparisons:
                    raise gr.Error("区域覆盖只能修改当前事件规则的比较条件")
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise gr.Error("区域覆盖阈值必须是数字")
                override_by_comparison.setdefault(comparison_id, {})[region_id] = float(
                    value
                )
        for region_id, values in region_operator_overrides.items():
            if region_id not in allowed_regions:
                raise gr.Error(f"未知的命名区域：{region_id}")
            if not isinstance(values, dict):
                raise gr.Error(f"区域 {region_id} 的比较符必须按条件填写")
            for comparison_id, operator in values.items():
                if comparison_id not in permitted_comparisons:
                    raise gr.Error("区域比较符只能修改当前事件规则的比较条件")
                if operator not in allowed_operators:
                    raise gr.Error("区域比较符必须是 >、>=、=、<=、<、== 或 !=")
                operator_override_by_comparison.setdefault(comparison_id, {})[
                    region_id
                ] = "==" if operator == "=" else operator

        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        data = package.model_dump(mode="json")
        variant = data["variants"].get(key)
        if not variant or variant["status"] == "unsupported":
            raise gr.Error(f"当前技能没有可配置的 {key} variant")
        nodes = {node["id"]: node for node in variant["nodes"]}
        for index, (node_id, operator, value) in enumerate(
            zip(comparison_ids, comparison_operators, comparison_values)
        ):
            if not isinstance(value, (int, float)):
                raise gr.Error("比较阈值必须是数字")
            node = nodes[node_id]
            node["params"] = {
                **node["params"],
                "operator": operator,
                "value": float(value),
            }
            node["params"].pop("threshold", None)
            if region_bindings is not None and region_bindings[index] is not None:
                node["params"]["key_filter"] = region_bindings[index]
            else:
                node["params"].pop("key_filter", None)
            overrides = override_by_comparison.get(node_id, {})
            if overrides:
                node["params"]["overrides"] = overrides
            else:
                node["params"].pop("overrides", None)
            operator_overrides = operator_override_by_comparison.get(node_id, {})
            if operator_overrides:
                node["params"]["operator_overrides"] = operator_overrides
            else:
                node["params"].pop("operator_overrides", None)

        if current["logic_node_id"] is not None:
            logic = nodes[current["logic_node_id"]]
            logic["op"] = f"logic.{logic_mode}@1.0"

        event = nodes[event_id]
        event["params"] = {
            **event["params"],
            "seconds": float(seconds),
            "gap_tolerance_seconds": float(gap_tolerance_seconds),
            "trigger_mode": trigger_mode,
        }
        if current["alert_node_id"] is not None:
            alert = nodes[current["alert_node_id"]]
            alert["params"] = {**alert["params"], "label": alert_label.strip()}

        if category_node_id is not None:
            category_node = nodes[category_node_id]
            available = {
                target.get("label")
                for target in category_node["params"].get("targets", [])
                if isinstance(target, dict) and target.get("label")
            }
            semantic_target_label = package.semantic_ir.target.source_span.strip()
            legacy_display_label = (
                not package.semantic_ir.target.classes
                and available == {package.display_name}
                and bool(semantic_target_label)
            )
            requested = set(categories or [])
            if not requested:
                raise gr.Error("至少保留一个统计类别")
            if legacy_display_label:
                requested = {
                    package.display_name if label == semantic_target_label else label
                    for label in requested
                }
            if not requested.issubset(available):
                raise gr.Error("统计类别必须来自当前检测目标")
            category_node["params"]["targets"] = [
                {
                    **target,
                    "label": semantic_target_label,
                }
                if legacy_display_label and target.get("label") == package.display_name
                else target
                for target in category_node["params"].get("targets", [])
                if target.get("label") in requested
            ]

        updated = SkillPackage.model_validate(data)
        errors = validate_skill_package(updated, self.registry)
        if errors:
            raise gr.Error("事件规则配置无效：" + "；".join(errors))
        return self._dump(updated)

    def sync_editor_region_overrides(
        self,
        editor_json: str,
        effective_json: str,
        media_type: str,
        comparison_ids: list[str],
    ) -> str:
        """Persist dedicated per-region controls into the business draft graph.

        The per-region card also updates the current Effective package so its
        summary refreshes immediately.  This companion write keeps the draft as
        the source of truth, otherwise a later “validate and generate” would
        compile the older graph and silently discard every regional override.
        """

        document = self._parse_editor_json(editor_json)
        key = _variant_key(media_type)
        graph = document.skill_template.rule_graphs.get(key)
        if graph is None:
            raise gr.Error(f"当前业务草稿没有 {key} 规则图")
        package = SkillPackage.model_validate_json(effective_json)
        variant = package.variants.get(key)
        if variant is None or variant.status == "unsupported":
            raise gr.Error(f"当前运行版本没有可同步的 {key} 流程")
        package_nodes = {node.id: node for node in variant.nodes}
        draft_nodes = {node.node_id: node for node in graph.nodes}
        for node_id in comparison_ids:
            source = package_nodes.get(node_id)
            target = draft_nodes.get(node_id)
            if source is None or target is None or target.operator != source.op:
                raise gr.Error("区域阈值对应的判断条件已变化，请刷新后重试")
            for name in ("overrides", "operator_overrides", "scope_overrides"):
                if name in source.params:
                    target.params[name] = deepcopy(source.params[name])
                    target.parameter_sources[name] = ResolvableValue(
                        state="explicit",
                        value=deepcopy(source.params[name]),
                        source="user",
                        required_before="never",
                    )
                else:
                    target.params.pop(name, None)
                    target.parameter_sources.pop(name, None)
        document.version += 1
        document.effective_skill_package = None
        document.validation_report.update({"dirty": True, "can_run": False})
        return self._dump(refresh_document_hashes(document))

    def apply_region_parameter_override(
        self,
        effective_json: str,
        media_type: str,
        event_id: str,
        region_id: str,
        parameter_id: str,
        value: Any,
    ) -> tuple[str, list[str]]:
        """Apply one validated region-scoped parameter through its declared storage."""

        controls = self.read_event_rule_controls(effective_json, media_type)
        selected = next(
            (item for item in controls if item["event_id"] == event_id), None
        )
        if selected is None:
            raise gr.Error("当前事件规则已变化，请刷新后重试")
        if region_id not in {item["id"] for item in selected.get("regions", [])}:
            raise gr.Error("请选择 02 中已标注的区域")
        descriptor = next(
            (
                item
                for item in selected.get("regional_parameters", [])
                if item["id"] == parameter_id
            ),
            None,
        )
        if descriptor is None:
            raise gr.Error("当前区域参数已变化，请刷新后重试")
        if descriptor["editor"] == "number":
            try:
                value = float(value)
            except (TypeError, ValueError) as exc:
                raise gr.Error("该区域参数必须填写数字") from exc
        elif value not in descriptor.get("choices", []):
            raise gr.Error("请从固定选项中选择区域参数")

        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        data = package.model_dump(mode="json")
        variant = data["variants"].get(key)
        if not variant or variant["status"] == "unsupported":
            raise gr.Error(f"当前技能没有可配置的 {key} 流程")
        nodes = {node["id"]: node for node in variant["nodes"]}
        node = nodes.get(descriptor["node_id"])
        if node is None:
            raise gr.Error("区域参数对应的原子已经不存在")
        storage = descriptor["storage"]
        if storage == "scope_overrides":
            overrides = deepcopy(node["params"].get(storage, {}))
            overrides.setdefault(region_id, {})[descriptor["parameter"]] = value
            node["params"][storage] = overrides
        else:
            overrides = deepcopy(node["params"].get(storage, {}))
            overrides[region_id] = value
            node["params"][storage] = overrides

        updated = SkillPackage.model_validate(data)
        errors = validate_skill_package(updated, self.registry)
        if errors:
            raise gr.Error("区域参数配置无效：" + "；".join(errors))
        return self._dump(updated), [descriptor["node_id"]]

    def apply_event_rule_cards(
        self,
        effective_json: str,
        media_type: str,
        event_id: str,
        cards: list[dict[str, Any]],
        logic_mode: str,
        seconds: float,
        gap_tolerance_seconds: float,
        trigger_mode: str,
        alert_label: str,
    ) -> str:
        """Persist a variable list of atomic comparison cards into one event DAG."""

        if logic_mode not in {"all", "any"}:
            raise gr.Error("条件关系必须是 all 或 any")
        if trigger_mode not in {"once", "repeat"}:
            raise gr.Error("触发方式必须是 once 或 repeat")
        if float(seconds) < 0 or float(gap_tolerance_seconds) < 0:
            raise gr.Error("持续时间和允许中断时间不能小于 0")
        if not alert_label or not alert_label.strip():
            raise gr.Error("请填写告警名称")
        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        data = package.model_dump(mode="json")
        variant = data["variants"].get(key)
        if not variant or variant["status"] == "unsupported":
            raise gr.Error(f"当前技能没有可配置的 {key} variant")
        nodes = {node["id"]: node for node in variant["nodes"]}
        event = nodes.get(event_id)
        if event is None or event["op"] not in {
            "temporal.persist@1.0",
            "event.from_condition@1.0",
        }:
            raise gr.Error("找不到要编辑的事件规则")
        current = next(
            (
                item
                for item in self.read_event_rule_controls(effective_json, media_type)
                if item["event_id"] == event_id
            ),
            None,
        )
        if current is None:
            raise gr.Error("找不到要编辑的事件规则")
        if current["condition_kind"] != "comparison":
            if cards:
                raise gr.Error("当前事件是状态/方向条件，不能添加数值比较卡")
            event["params"] = {
                **event.get("params", {}),
                "seconds": float(seconds),
                "gap_tolerance_seconds": float(gap_tolerance_seconds),
                "trigger_mode": trigger_mode,
            }
            alert = next(
                (
                    node
                    for node in variant["nodes"]
                    if node["op"] == "output.alert@1.0"
                    and node.get("inputs", {}).get("events") == f"${event_id}"
                ),
                None,
            )
            if alert is not None:
                alert.setdefault("params", {})["label"] = alert_label.strip()
            updated = SkillPackage.model_validate(data)
            errors = validate_skill_package(updated, self.registry)
            if errors:
                raise gr.Error("事件规则配置无效：" + "；".join(errors))
            return self._dump(updated)
        if not cards:
            raise gr.Error("至少保留一个启用条件")
        templates = {item["node_id"]: item for item in current["comparisons"]}
        allowed_regions = set(current.get("region_ids", []))
        allowed_operators = {">", ">=", "=", "<=", "<", "==", "!="}
        used_templates: set[str] = set()
        comparison_refs: list[str] = []
        comparison_region_sources: list[tuple[str, str | None]] = []

        def next_id(base: str) -> str:
            candidate = base
            suffix = 2
            while candidate in nodes:
                candidate = f"{base}_{suffix}"
                suffix += 1
            return candidate

        def node_for_ref(reference: str | None):
            if not isinstance(reference, str) or not reference.startswith("$"):
                return None
            return nodes.get(reference[1:])

        def region_source_for_measurement(measurement: dict[str, Any]) -> str | None:
            for input_name in ("regions", "lanes"):
                region_node = node_for_ref(measurement["inputs"].get(input_name))
                if region_node is not None:
                    return str(region_node["id"])
            return None

        def category_labels(measurement: dict[str, Any]) -> set[str]:
            seen: set[str] = set()

            def visit(node: dict[str, Any] | None):
                if node is None or node["id"] in seen:
                    return set()
                seen.add(node["id"])
                if node["op"] == "rex.ground@1.1":
                    return {
                        str(target["label"])
                        for target in node.get("params", {}).get("targets", [])
                        if isinstance(target, dict) and target.get("label")
                    }
                labels: set[str] = set()
                for value in node.get("inputs", {}).values():
                    references = value if isinstance(value, list) else [value]
                    for reference in references:
                        labels.update(visit(node_for_ref(reference)))
                return labels

            return visit(measurement)

        for index, card in enumerate(cards, start=1):
            if not isinstance(card, dict):
                raise gr.Error("条件卡必须是对象")
            template_id = str(card.get("template_id") or "")
            template = templates.get(template_id)
            if template is None:
                raise gr.Error("条件卡必须选择当前事件可用的统计量")
            operator = str(card.get("operator") or "")
            if operator not in allowed_operators:
                raise gr.Error("比较符必须是 >、>=、=、<=、<、== 或 !=")
            value = card.get("value")
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise gr.Error("比较阈值必须是数字")
            region_id = card.get("region_id")
            global_scope = region_id == "__global__"
            if (
                region_id is not None
                and not global_scope
                and str(region_id) not in allowed_regions
            ):
                raise gr.Error(f"未知的命名区域：{region_id}")

            template_node = nodes[template_id]
            reuse_template = template_id not in used_templates
            used_templates.add(template_id)
            if reuse_template:
                comparison = template_node
            else:
                comparison = deepcopy(template_node)
                comparison["id"] = next_id(f"{event_id}_condition_{index}")
                nodes[comparison["id"]] = comparison
                variant["nodes"].append(comparison)
            measurement = node_for_ref(comparison["inputs"].get("left"))
            if measurement is None:
                raise gr.Error("条件卡的统计量缺少上游度量")
            region_source_id = (
                None if global_scope else region_source_for_measurement(measurement)
            )
            if global_scope:
                region_input = next(
                    (
                        name
                        for name in ("regions", "lanes")
                        if name in measurement["inputs"]
                    ),
                    None,
                )
                if region_input is None:
                    raise gr.Error("当前统计量没有可切换的全画面度量")
                object_input = next(
                    (
                        name
                        for name in ("objects", "entities")
                        if name in measurement["inputs"]
                    ),
                    None,
                )
                if object_input is None:
                    raise gr.Error("当前统计量不支持全画面类别筛选")
                global_measurement_id = next_id(f"{comparison['id']}__global_measure")
                global_measurement = {
                    "id": global_measurement_id,
                    "op": "measure.count@1.0",
                    "inputs": {"entities": measurement["inputs"][object_input]},
                    "params": {"scope": "frame", "group_by": "none"},
                }
                nodes[global_measurement_id] = global_measurement
                variant["nodes"].append(global_measurement)
                measurement = global_measurement
                comparison["inputs"]["left"] = f"${global_measurement_id}"
            if not reuse_template:
                measurement = deepcopy(measurement)
                measurement["id"] = next_id(f"{comparison['id']}_measure")
                nodes[measurement["id"]] = measurement
                variant["nodes"].append(measurement)
                comparison["inputs"]["left"] = f"${measurement['id']}"

            requested_categories = [
                str(label) for label in card.get("categories", []) if str(label)
            ]
            available_categories = category_labels(measurement)
            if requested_categories:
                if available_categories and not set(requested_categories).issubset(
                    available_categories
                ):
                    raise gr.Error("目标类别必须来自当前检测目标")
                object_input = next(
                    (
                        name
                        for name in ("objects", "entities")
                        if name in measurement["inputs"]
                    ),
                    None,
                )
                if object_input is None:
                    raise gr.Error("当前统计量不支持按目标类别筛选")
                upstream_ref = measurement["inputs"][object_input]
                upstream = node_for_ref(upstream_ref)
                if (
                    upstream is not None
                    and upstream["op"] == "objects.filter_by_label@1.0"
                    and "__event_card_" in upstream["id"]
                ):
                    upstream_ref = upstream["inputs"]["objects"]
                filter_id = next_id(f"{comparison['id']}__event_card_categories")
                filter_node = {
                    "id": filter_id,
                    "op": "objects.filter_by_label@1.0",
                    "inputs": {"objects": upstream_ref},
                    "params": {"labels": requested_categories, "mode": "include"},
                }
                nodes[filter_id] = filter_node
                variant["nodes"].append(filter_node)
                measurement["inputs"][object_input] = f"${filter_id}"

            comparison["params"] = {
                **comparison["params"],
                "operator": "==" if operator == "=" else operator,
                "value": float(value),
            }
            comparison["params"].pop("threshold", None)
            comparison["params"].pop("overrides", None)
            comparison["params"].pop("operator_overrides", None)
            if region_id is None or global_scope:
                comparison["params"].pop("key_filter", None)
            else:
                comparison["params"]["key_filter"] = str(region_id)
            comparison_refs.append(f"${comparison['id']}")
            if region_source_id is not None:
                comparison_region_sources.append(
                    (
                        region_source_id,
                        None if region_id is None else str(region_id),
                    )
                )

        # logic.all / logic.any are multi-input operators.  A lone comparison is
        # already an executable condition, so connect it directly to the event.
        # The reachability cleanup below removes an obsolete combiner, if any.
        if len(comparison_refs) == 1:
            event["inputs"]["condition"] = comparison_refs[0]
        else:
            current_logic_id = current["logic_node_id"]
            if current_logic_id is None:
                logic_id = next_id(f"{event_id}_conditions")
                logic = {
                    "id": logic_id,
                    "op": "logic.all@1.0",
                    "inputs": {},
                    "params": {},
                }
                nodes[logic_id] = logic
                variant["nodes"].append(logic)
            else:
                logic = nodes[current_logic_id]
                logic_id = current_logic_id
            logic["op"] = f"logic.{logic_mode}@1.0"
            logic["inputs"] = {"conditions": comparison_refs}
            logic["params"] = {
                "combine_scope": (
                    "frame_any" if len(set(comparison_region_sources)) > 1 else "by_key"
                )
            }
            event["inputs"]["condition"] = f"${logic_id}"
        event["params"] = {
            **event["params"],
            "seconds": float(seconds),
            "gap_tolerance_seconds": float(gap_tolerance_seconds),
            "trigger_mode": trigger_mode,
        }
        alert = next(
            (
                node
                for node in variant["nodes"]
                if node["op"] == "output.alert@1.0"
                and node["inputs"].get("events") == f"${event_id}"
            ),
            None,
        )
        if alert is not None:
            alert["params"] = {**alert["params"], "label": alert_label.strip()}

        # A card replacement can leave legacy branches detached.  Keep the package
        # executable by retaining only nodes that contribute to declared outputs.
        reachable: set[str] = set()
        pending = [
            reference[1:]
            for reference in variant["outputs"].values()
            if isinstance(reference, str) and reference.startswith("$")
        ]
        while pending:
            node_id = pending.pop()
            if node_id in reachable or node_id not in nodes:
                continue
            reachable.add(node_id)
            for value in nodes[node_id].get("inputs", {}).values():
                references = value if isinstance(value, list) else [value]
                pending.extend(
                    reference[1:]
                    for reference in references
                    if isinstance(reference, str) and reference.startswith("$")
                )
        variant["nodes"] = [
            node for node in variant["nodes"] if node["id"] in reachable
        ]
        retained_ids = {node["id"] for node in variant["nodes"]}
        fallback = comparison_refs[0][1:]
        for atom_id, binding in variant.get("atom_bindings", {}).items():
            kept = [node_id for node_id in binding if node_id in retained_ids]
            variant["atom_bindings"][atom_id] = kept or [fallback]

        updated = SkillPackage.model_validate(data)
        errors = validate_skill_package(updated, self.registry)
        if errors:
            raise gr.Error("事件条件配置无效：" + "；".join(errors))
        return self._dump(updated)

    def apply_event_association(
        self,
        effective_json: str,
        media_type: str,
        event_id: str,
        association_id: str,
        subject_key: str,
        object_key: str,
        threshold: float,
    ) -> str:
        """Rebind one event association to declared detector categories."""

        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
            raise gr.Error("关联阈值必须是数字")
        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        data = package.model_dump(mode="json")
        variant = data["variants"].get(key)
        if not variant or variant["status"] == "unsupported":
            raise gr.Error(f"当前技能没有可配置的 {key} variant")
        nodes = {node["id"]: node for node in variant["nodes"]}
        event = nodes.get(event_id)
        if event is None or event["op"] not in {
            "temporal.persist@1.0",
            "event.from_condition@1.0",
        }:
            raise gr.Error("找不到要编辑的事件规则")
        association = nodes.get(association_id)
        if association is None or association["op"] != "spatial.associate@1.0":
            raise gr.Error("找不到要编辑的目标关联")

        current = next(
            (
                item
                for item in self.read_event_rule_controls(effective_json, media_type)
                if item["event_id"] == event_id
            ),
            None,
        )
        permitted_associations = {
            item["node_id"] for item in (current or {}).get("associations", [])
        }
        if association_id not in permitted_associations:
            raise gr.Error("目标关联不是当前事件规则的一部分")

        relation = association.get("params", {}).get("relation", "overlap")
        if relation in {"overlap", "mutual_match", "inside", "contains"} and not (
            0.0 <= float(threshold) <= 1.0
        ):
            raise gr.Error("框关联阈值必须在 0 到 1 之间")
        if relation not in {"overlap", "mutual_match", "inside", "contains", "near"}:
            raise gr.Error("当前关联方式不支持在事件规则中重绑定候选框")

        def node_for(reference: str | None):
            if not isinstance(reference, str) or not reference.startswith("$"):
                return None
            return nodes.get(reference[1:])

        def parse_candidate(candidate_key: str):
            try:
                ground_id, index_text = str(candidate_key).rsplit(":", 1)
                index = int(index_text)
            except (AttributeError, TypeError, ValueError) as exc:
                raise gr.Error("候选框必须来自当前技能的检测类别") from exc
            ground = nodes.get(ground_id)
            if ground is None or ground["op"] != "rex.ground@1.1":
                raise gr.Error("候选框必须来自当前技能的检测类别")
            targets = ground.get("params", {}).get("targets", [])
            if (
                index < 0
                or index >= len(targets)
                or not isinstance(targets[index], dict)
            ):
                raise gr.Error("候选框必须来自当前技能的检测类别")
            if not targets[index].get("label"):
                raise gr.Error("候选框缺少已声明的类别标签")
            return ground_id, index, targets

        def candidate_reference(role: str, candidate_key: str) -> str:
            ground_id, target_index, targets = parse_candidate(candidate_key)
            base_id = next(
                (
                    node["id"]
                    for node in variant["nodes"]
                    if node["op"] == "objects.deduplicate@1.0"
                    and node.get("inputs", {}).get("objects") == f"${ground_id}"
                ),
                ground_id,
            )
            if len(targets) == 1:
                return f"${base_id}"
            filter_id = f"{association_id}__{role}_{ground_id}_{target_index}"
            selected = nodes.get(filter_id)
            if selected is None:
                selected = {
                    "id": filter_id,
                    "op": "objects.filter_by_label@1.0",
                    "inputs": {"objects": f"${base_id}"},
                    "params": {
                        "labels": [str(targets[target_index]["label"])],
                        "mode": "include",
                    },
                }
                nodes[filter_id] = selected
                variant["nodes"].append(selected)
            else:
                selected["inputs"] = {"objects": f"${base_id}"}
                selected["params"] = {
                    "labels": [str(targets[target_index]["label"])],
                    "mode": "include",
                }
            return f"${filter_id}"

        def track_node_for(reference: str | None, visited: set[str] | None = None):
            node = node_for(reference)
            if node is None:
                return None
            visited = set() if visited is None else visited
            node_id = str(node["id"])
            if node_id in visited:
                return None
            visited.add(node_id)
            if node["op"] == "track.iou@1.0":
                return node
            for value in node.get("inputs", {}).values():
                references = value if isinstance(value, list) else [value]
                for item in references:
                    track = track_node_for(item, visited)
                    if track is not None:
                        return track
            return None

        subject_reference = candidate_reference("subject", subject_key)
        object_reference = candidate_reference("object", object_key)
        previous_subject_reference = association["inputs"].get("subjects")
        track = track_node_for(previous_subject_reference)
        if track is not None:
            track.setdefault("inputs", {})["objects"] = subject_reference
        else:
            association.setdefault("inputs", {})["subjects"] = subject_reference
            for node in variant["nodes"]:
                if (
                    node["op"] == "filter.apply@1.0"
                    and node.get("inputs", {}).get("condition") == f"${association_id}"
                    and node.get("inputs", {}).get("objects")
                    == previous_subject_reference
                ):
                    node["inputs"]["objects"] = subject_reference
        association.setdefault("inputs", {})["objects"] = object_reference
        association.setdefault("params", {})["threshold"] = float(threshold)

        updated = SkillPackage.model_validate(data)
        errors = validate_skill_package(updated, self.registry)
        if errors:
            raise gr.Error("目标关联配置无效：" + "；".join(errors))
        return self._dump(updated)

    def apply_temporal_control(
        self,
        effective_json: str,
        media_type: str,
        node_id: str,
        seconds: float,
        gap_tolerance_seconds: float,
        trigger_mode: str,
    ) -> str:
        """Update one explicit duration-event atom without changing its condition."""

        if not node_id:
            raise gr.Error("当前流程没有可配置的持续事件")
        if float(seconds) < 0 or float(gap_tolerance_seconds) < 0:
            raise gr.Error("持续时间和允许中断时间不能小于 0")
        if trigger_mode not in {"once", "repeat"}:
            raise gr.Error("触发方式必须是 once 或 repeat")
        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        data = package.model_dump(mode="json")
        variant = data["variants"].get(key)
        if not variant or variant["status"] == "unsupported":
            raise gr.Error(f"当前技能没有可配置的 {key} variant")
        event = next(
            (
                node
                for node in variant["nodes"]
                if node["id"] == node_id
                and node["op"] in {"temporal.persist@1.0", "event.from_condition@1.0"}
            ),
            None,
        )
        if event is None:
            raise gr.Error("找不到指定的持续事件节点")
        event["params"] = {
            **event["params"],
            "seconds": float(seconds),
            "gap_tolerance_seconds": float(gap_tolerance_seconds),
            "trigger_mode": trigger_mode,
        }
        updated = SkillPackage.model_validate(data)
        errors = validate_skill_package(updated, self.registry)
        if errors:
            raise gr.Error("事件阈值配置无效：" + "；".join(errors))
        return self._dump(updated)

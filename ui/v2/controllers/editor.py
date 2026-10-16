"""EditorController: extracted V2 responsibilities, preserving public method signatures."""

from __future__ import annotations

import difflib
import json
import re
from copy import deepcopy
from typing import Any

import gradio as gr

from application.v2.support import _variant_key
from core.editor_generation import build_editor_document, resolve_pending_decision
from core.editor_schema import (
    ResourceCollection,
    ResourceInstance,
    SceneProfile,
    SkillEditorDocument,
)
from core.editor_service import EditorMutationError
from core.schema import SkillPackage, WorkflowVariant
from core.validator import validate_skill_package


class EditorController:
    def unified_editor_controls(
        self,
        effective_json: str,
        editor_json: str,
        media_type: str,
        source_mode: str = "已保存技能",
    ):
        """Read the complete V3 document used by every view in step 03."""

        source_type = {
            "自然语言生成": "natural_language",
            "预置演示技能": "preset",
            "已保存技能": "legacy",
        }.get(source_mode, "legacy")
        document = self._editor_document(effective_json, editor_json, source_type)
        key = _variant_key(media_type)
        graph = document.skill_template.rule_graphs.get(key)
        if graph is None:
            raise gr.Error(f"当前技能没有 {key} 规则图")
        branches = [
            (f"{item.display_name}（{item.branch_id}）", item.branch_id)
            for item in document.skill_template.business_branches
            if item.media_type == key
        ]
        nodes = [
            (f"{item.display_name}（{item.node_id} · {item.operator}）", item.node_id)
            for item in graph.nodes
        ]
        operators = [
            (f"{item['display_name']}（{item['operator']}）", item["operator"])
            for item in self.editor_service.operator_catalog()
        ]
        branch_value = branches[0][1] if branches else None
        node_value = nodes[0][1] if nodes else None
        params, parameter, value = self._unified_node_parameter_values(
            document, key, node_value
        )
        report = self.editor_service.validate(document)
        pending = [
            {
                "id": item.decision_id,
                "问题": item.prompt,
                "状态": item.resolution.state,
                "运行前必须确认": item.resolution.blocks("run"),
            }
            for item in document.skill_template.pending_decisions
        ]
        pending_choices = [
            (f"{item.prompt}（{item.decision_id}）", item.decision_id)
            for item in document.skill_template.pending_decisions
            if item.resolution.state == "unresolved"
        ]
        results = [
            item.model_dump(mode="json")
            for item in document.skill_template.result_specs
        ]
        status = (
            f"规则图：{len(graph.nodes)} 个原子 / {len(graph.edges)} 条连接；"
            f"业务分支：{len(branches)}；复杂事件模式：{len(document.skill_template.event_patterns)}。"
        )
        if report["errors"]:
            status += " 当前草稿待修复：" + "；".join(report["errors"][:3])
        elif report["pending"]:
            status += f" 仍有 {len(report['pending'])} 项需在运行前确认。"
        else:
            status += " 当前结构可审核并应用。"
        return (
            self._dump(document),
            status,
            gr.update(choices=branches, value=branch_value),
            gr.update(choices=nodes, value=node_value),
            gr.update(
                choices=operators,
                value=operators[0][1] if operators else None,
            ),
            gr.update(choices=nodes, value=node_value),
            gr.update(choices=nodes, value=None),
            gr.update(choices=params, value=parameter),
            value,
            self._dump(
                [
                    item.model_dump(mode="json")
                    for item in document.skill_template.event_patterns
                ]
            ),
            gr.update(
                choices=pending_choices,
                value=pending_choices[0][1] if pending_choices else None,
            ),
            pending,
            self._dump(results),
        )

    def unified_node_parameters(
        self, editor_json: str, media_type: str, node_id: str | None
    ):
        if not editor_json:
            return gr.update(choices=[], value=None), ""
        document = self._parse_editor_json(editor_json)
        params, selected, value = self._unified_node_parameter_values(
            document, _variant_key(media_type), node_id
        )
        return gr.update(choices=params, value=selected), value

    def unified_parameter_value(
        self, editor_json: str, media_type: str, node_id: str, parameter: str
    ) -> str:
        if not editor_json or not node_id or not parameter:
            return ""
        document = self._parse_editor_json(editor_json)
        _, _, value = self._unified_node_parameter_values(
            document, _variant_key(media_type), node_id, parameter
        )
        return value

    def unified_apply_parameter(
        self, editor_json: str, node_id: str, parameter: str, value_text: str
    ):
        document = self._parse_editor_json(editor_json)
        try:
            value = json.loads(value_text)
        except json.JSONDecodeError:
            value = value_text
        try:
            updated = self.editor_service.set_parameter(
                document, node_id, parameter, value
            )
        except EditorMutationError as exc:
            raise gr.Error(str(exc)) from exc
        return (
            self._dump(updated),
            f"已记录用户覆盖：{node_id}.{parameter} 到 03 草稿（尚未生效）；请点击【校验并生成当前运行版本（使修改生效）】。",
        )

    def unified_reset_parameter(self, editor_json: str, node_id: str, parameter: str):
        document = self._parse_editor_json(editor_json)
        try:
            updated = self.editor_service.reset_parameter(document, node_id, parameter)
        except EditorMutationError as exc:
            raise gr.Error(str(exc)) from exc
        return (
            self._dump(updated),
            f"已恢复 LLM 生成/系统默认值：{node_id}.{parameter}；当前仍是 03 草稿（尚未生效），请点击【校验并生成当前运行版本（使修改生效）】。",
        )

    def unified_mutate_graph(
        self,
        editor_json: str,
        media_type: str,
        action: str,
        selected_node: str,
        new_node_id: str,
        operator: str,
        source_node: str,
        target_node: str,
        port: str,
        branch_id: str,
    ):
        document = self._parse_editor_json(editor_json)
        key = _variant_key(media_type)
        try:
            if action == "新增原子":
                updated = self.editor_service.add_node(
                    document, key, operator, new_node_id, branch_id=branch_id or None
                )
            elif action == "复制原子":
                updated = self.editor_service.copy_node(
                    document, key, selected_node, new_node_id
                )
            elif action == "删除原子":
                updated = self.editor_service.delete_node(document, key, selected_node)
            elif action == "替换能力":
                updated = self.editor_service.replace_node_operator(
                    document, key, selected_node, operator
                )
            elif action == "连接原子":
                updated = self.editor_service.connect(
                    document, key, source_node, target_node, port
                )
            elif action == "断开连接":
                updated = self.editor_service.disconnect(
                    document, key, source_node, target_node, port or None
                )
            else:
                raise EditorMutationError("请选择图编辑动作")
        except EditorMutationError as exc:
            raise gr.Error(str(exc)) from exc
        return (
            self._dump(updated),
            f"已完成：{action}。当前为 03 未应用草稿；请点击【校验并生成当前运行版本（使修改生效）】。",
        )

    def unified_mutate_branch(
        self,
        editor_json: str,
        media_type: str,
        action: str,
        branch_id: str,
        new_branch_id: str,
        display_name: str,
    ):
        document = self._parse_editor_json(editor_json)
        try:
            if action == "新增分支":
                updated = self.editor_service.add_branch(
                    document, _variant_key(media_type), new_branch_id, display_name
                )
            elif action == "复制分支":
                updated = self.editor_service.copy_branch(
                    document, branch_id, new_branch_id, display_name
                )
            elif action == "重命名分支":
                updated = self.editor_service.update_branch(
                    document, branch_id, display_name=display_name
                )
            elif action == "启用/停用":
                branch = next(
                    item
                    for item in document.skill_template.business_branches
                    if item.branch_id == branch_id
                )
                updated = self.editor_service.update_branch(
                    document, branch_id, enabled=not branch.enabled
                )
            elif action == "上移":
                updated = self.editor_service.update_branch(
                    document, branch_id, move=-1
                )
            elif action == "下移":
                updated = self.editor_service.update_branch(document, branch_id, move=1)
            elif action == "删除分支":
                updated = self.editor_service.delete_branch(document, branch_id)
            else:
                raise EditorMutationError("请选择业务分支动作")
        except (EditorMutationError, StopIteration) as exc:
            raise gr.Error(str(exc) or "找不到业务分支") from exc
        return (
            self._dump(updated),
            f"已完成：{action}。当前为 03 未应用草稿；请点击【校验并生成当前运行版本（使修改生效）】。",
        )

    def unified_insert_recipe(
        self, editor_json: str, media_type: str, recipe_id: str, branch_id: str
    ):
        document = self._parse_editor_json(editor_json)
        try:
            updated = self.editor_service.insert_recipe(
                document, _variant_key(media_type), recipe_id, branch_id or None
            )
        except EditorMutationError as exc:
            raise gr.Error(str(exc)) from exc
        return (
            self._dump(updated),
            f"已插入可复用 Recipe：{recipe_id} 到 03 草稿（尚未生效）。请补齐外部输入后点击【校验并生成当前运行版本（使修改生效）】。",
        )

    def unified_apply_patterns(self, editor_json: str, patterns_json: str):
        document = self._parse_editor_json(editor_json)
        try:
            patterns = json.loads(patterns_json or "[]")
            if not isinstance(patterns, list):
                raise ValueError("EventPattern 必须是数组")  # noqa: TRY004 — preserved V2 behavior
            updated = self.editor_service.set_event_patterns(document, patterns)
        except (ValueError, EditorMutationError, json.JSONDecodeError) as exc:
            raise gr.Error(str(exc)) from exc
        return (
            self._dump(updated),
            "复杂事件编排已保存到 03 草稿（尚未生效）；请点击【校验并生成当前运行版本（使修改生效）】。",
        )

    def unified_resolve_pending(
        self, editor_json: str, decision_id: str, value_text: str
    ):
        if not decision_id:
            raise gr.Error("当前没有可确认的不确定条件")
        document = self._parse_editor_json(editor_json)
        try:
            value = json.loads(value_text)
        except json.JSONDecodeError:
            value = value_text
        try:
            updated = resolve_pending_decision(document, decision_id, value)
        except ValueError as exc:
            raise gr.Error(str(exc)) from exc
        updated.version += 1
        updated.effective_skill_package = None
        updated.validation_report.update({"dirty": True, "can_run": False})
        return (
            self._dump(updated),
            f"已确认：{decision_id}，仍是 03 草稿（尚未生效）。请点击【校验并生成当前运行版本（使修改生效）】。",
        )

    def unified_apply_results(self, editor_json: str, results_json: str):
        document = self._parse_editor_json(editor_json)
        try:
            specs = json.loads(results_json or "[]")
            if not isinstance(specs, list):
                raise ValueError("ResultSpec 必须是数组")  # noqa: TRY004 — preserved V2 behavior
            updated = self.editor_service.set_result_specs(document, specs)
        except (ValueError, EditorMutationError, json.JSONDecodeError) as exc:
            raise gr.Error(str(exc)) from exc
        return (
            self._dump(updated),
            "✅ 结果与证据契约已保存到 03 草稿（尚未生效）；请点击【校验并生成当前运行版本（使修改生效）】。",
        )

    def unified_validate_apply(self, editor_json: str):
        document = self._parse_editor_json(editor_json)
        try:
            compiled = self.editor_service.apply(document)
        except Exception as exc:
            raise gr.Error(f"配置不能应用：{exc}") from exc
        package = compiled.effective_skill_package
        if package is None:
            raise gr.Error("编译未生成 Effective SkillPackage")
        pending = compiled.validation_report.get("pending", [])
        status = (
            f"✅ 条件、时间编排、最终判定和业务输出已校验；当前运行版本已更新（v{compiled.version}）。"
            "04 运行将使用本次校验后的配置。"
        )
        if pending:
            status = (
                f"⚠️ 草稿已编译但尚未生效：仍有 {len(pending)} 项不确定条件。"
                "完成确认后，再点击【校验并生成当前运行版本（使修改生效）】；04 暂不允许运行。"
            )
        return self._dump(compiled), self._dump(package), status

    def _editor_document(
        self,
        effective_json: str,
        editor_json: str,
        source_type: str = "legacy",
        active_media_type: str | None = None,
    ) -> SkillEditorDocument:
        package = SkillPackage.model_validate_json(effective_json)
        if editor_json:
            try:
                existing = self._parse_editor_json(editor_json)
                existing_package = existing.effective_skill_package
                same_effective = (
                    existing_package is not None
                    and existing_package.model_dump(mode="json")
                    == package.model_dump(mode="json")
                )
                if existing.skill_template.skill_id == package.skill_id:
                    if not same_effective:
                        existing = self._sync_editor_scene_resources(existing, package)
                        existing.effective_skill_package = package
                    return self._refresh_editor_validation(existing, active_media_type)
            except Exception:  # noqa: S110, BLE001 — preserved V2 behavior
                pass
        cached = self._generated_editor_documents.get(package.skill_id)
        if (
            cached is not None
            and cached.skill_template.original_instruction
            == package.original_instruction
        ):
            synced = self._sync_editor_scene_resources(
                cached.model_copy(deep=True), package
            )
            synced.effective_skill_package = package
            return self._refresh_editor_validation(synced, active_media_type)
        built = build_editor_document(package, source_type=source_type)
        self._generated_editor_documents.setdefault(
            package.skill_id, built.model_copy(deep=True)
        )
        return self._refresh_editor_validation(built, active_media_type)

    def prepare_run_editor_document(
        self, effective_json: str, editor_json: str, media_type: str | None = None
    ) -> str:
        """Refresh annotations and run blockers immediately before execution."""

        if not editor_json:
            return ""
        return self._dump(
            self._editor_document(
                effective_json, editor_json, active_media_type=media_type
            )
        )

    @staticmethod
    def run_configuration_blocker_message(
        document: SkillEditorDocument,
    ) -> str:
        """Translate internal resource ids into one actionable UI message."""

        blockers = list(document.validation_report.get("resource_blockers", []))
        by_id = {
            item.requirement_id: item.display_name
            for item in document.skill_template.resource_requirements
        }
        labels = [by_id.get(str(item), str(item)) for item in blockers]
        labels = list(dict.fromkeys(labels))
        errors = [str(item) for item in document.validation_report.get("errors", [])]
        parts = list(errors)
        if labels:
            parts.append(
                "请先到 02 标注依次绘制并点击“保存并继续”：" + "、".join(labels)
            )
        return "；".join(parts) or "请查看 02 标注中的待配置项"

    def _refresh_editor_validation(
        self, document: SkillEditorDocument, active_media_type: str | None = None
    ) -> SkillEditorDocument:
        """Refresh run readiness after package/scene-resource projection.

        Annotation binding changes the Effective SkillPackage, while the run
        button reads the cached editor document's validation report. Keeping
        that report fresh prevents stale resource blockers from surviving a
        successful 02 annotation save.
        """

        package = document.effective_skill_package
        if package is not None:
            slot_required = {
                f"{media_type}_{slot.slot_id}": slot.required
                for media_type, variant in package.variants.items()
                for slot in variant.configuration_slots
            }
            for requirement in document.skill_template.resource_requirements:
                required = slot_required.get(requirement.requirement_id)
                if required is not None:
                    requirement.required_before = "run" if required else "never"
        report = self.editor_service.validate(document)
        if active_media_type:
            active_key = _variant_key(active_media_type)
            requirements = {
                item.requirement_id: item
                for item in document.skill_template.resource_requirements
            }
            # Image and video annotations are independent.  Validate only the
            # resource requirements of the media that will actually run.
            report["resource_blockers"] = [
                requirement_id
                for requirement_id in report.get("resource_blockers", [])
                if not requirements.get(requirement_id)
                or not requirements[requirement_id].media_types
                or active_key in requirements[requirement_id].media_types
            ]
            report["valid"] = bool(
                not report.get("errors")
                and not report.get("pending")
                and not report["resource_blockers"]
            )
        document.validation_report = {
            **report,
            "can_run": bool(
                document.effective_skill_package is not None and report["valid"]
            ),
        }
        return document

    @staticmethod
    def _sync_editor_scene_resources(
        document: SkillEditorDocument, package: SkillPackage
    ) -> SkillEditorDocument:
        """Copy 02 annotations into the business editor's scene profile."""

        result = document.model_copy(deep=True)
        profile = next(
            (
                item
                for item in result.scene_profiles
                if item.scene_profile_id == result.active_scene_profile_id
            ),
            None,
        )
        if profile is None:
            profile = SceneProfile(display_name="当前任务标注")
            result.scene_profiles.append(profile)
            result.active_scene_profile_id = profile.scene_profile_id
        collection_by_id = {item.requirement_id: item for item in profile.collections}
        for requirement in result.skill_template.resource_requirements:
            safe_requirement_id = re.sub(
                r"[^A-Za-z0-9_-]+", "_", requirement.requirement_id
            ).strip("_")
            candidate_slot_ids = {
                requirement.requirement_id,
                f"slot_{safe_requirement_id}",
                str(requirement.legacy_metadata.get("slot_id", "")),
            }
            matched = None
            for media_type, variant in package.variants.items():
                if (
                    requirement.media_types
                    and media_type not in requirement.media_types
                ):
                    continue
                slot = next(
                    (
                        item
                        for item in variant.configuration_slots
                        if item.slot_id in candidate_slot_ids
                    ),
                    None,
                )
                if slot is None:
                    continue
                node = next(
                    (item for item in variant.nodes if item.id == slot.binding.node_id),
                    None,
                )
                if node is not None:
                    matched = (media_type, slot, node)
                    break
            if matched is None:
                continue
            media_type, slot, node = matched
            # 02 writes annotations to the current Effective package first.  Keep
            # the draft graph's resource node in sync as well, so later business
            # validation cannot compile an older empty region/direction node and
            # erase the user's canvas work.
            draft_graph = result.skill_template.rule_graphs.get(media_type)
            draft_node = next(
                (
                    item
                    for item in (draft_graph.nodes if draft_graph else [])
                    if item.node_id == slot.binding.node_id
                ),
                None,
            )
            if draft_node is not None:
                draft_node.operator = node.op
                draft_node.params = deepcopy(node.params)
                draft_node.enabled = node.enabled
            instances = []
            if slot.kind == "region":
                if node.params.get("points"):
                    instances.append(
                        ResourceInstance(
                            resource_id=requirement.requirement_id,
                            resource_type="region",
                            display_name=requirement.display_name,
                            semantic_role=requirement.semantic_role,
                            geometry={
                                "shape": node.params.get("shape", "polygon"),
                                "points": node.params["points"],
                            },
                        )
                    )
            elif slot.kind == "region_set":
                instances.extend(
                    ResourceInstance(
                        resource_id=item["id"],
                        resource_type="region",
                        display_name=item.get("label") or item["id"],
                        semantic_role=requirement.semantic_role,
                        geometry={
                            "shape": item.get("shape", "polygon"),
                            "points": item.get("points", []),
                        },
                    )
                    for item in node.params.get("regions", [])
                    if isinstance(item, dict) and item.get("id")
                )
            elif slot.kind == "direction":
                vector = node.params.get("vector", [])
                if len(vector) == 2 and any(value != 0 for value in vector):
                    instances.append(
                        ResourceInstance(
                            resource_id=requirement.requirement_id,
                            resource_type="direction",
                            display_name=requirement.display_name,
                            semantic_role=requirement.semantic_role,
                            geometry={"vector": vector},
                        )
                    )
            else:
                instances.extend(
                    ResourceInstance(
                        resource_id=f"{item['key']}_direction",
                        resource_type="direction",
                        display_name=item.get("label") or item["key"],
                        semantic_role=requirement.semantic_role,
                        paired_resource_id=item["key"],
                        geometry={
                            "vector": item.get("vector", []),
                            "start": item.get("start", []),
                            "end": item.get("end", []),
                        },
                    )
                    for item in node.params.get("directions", [])
                    if isinstance(item, dict) and item.get("key")
                )
            collection = ResourceCollection(
                requirement_id=requirement.requirement_id,
                items=instances,
                completed=len(instances) >= requirement.cardinality.minimum,
            )
            collection_by_id[requirement.requirement_id] = collection
        profile.collections = list(collection_by_id.values())
        return result

    def _unified_node_parameter_values(
        self,
        document: SkillEditorDocument,
        media_type: str,
        node_id: str | None,
        selected: str | None = None,
    ):
        graph = document.skill_template.rule_graphs.get(media_type)
        node = next(
            (
                item
                for item in (graph.nodes if graph else [])
                if item.node_id == node_id
            ),
            None,
        )
        if node is None or node.operator is None:
            return [], None, ""
        definition = self.registry.require(node.operator)
        params = sorted(set(definition.parameters) | set(node.params))
        parameter = selected if selected in params else (params[0] if params else None)
        if parameter is None:
            return params, None, ""
        override = next(
            (
                item
                for item in reversed(document.user_overrides)
                if item.target_id == node.node_id and item.parameter == parameter
            ),
            None,
        )
        value = (
            override.value
            if override
            else node.params.get(parameter, definition.defaults.get(parameter))
        )
        return params, parameter, self._dump(value)

    def atomic_parameter_controls(self, effective_json: str, media_type: str):
        package = SkillPackage.model_validate_json(effective_json)
        variant = package.select_variant(_variant_key(media_type))
        choices = []
        rows = []
        for node in variant.nodes:
            definition = self.registry.require(node.op)
            editable = sorted(set(definition.parameters) | set(node.params))
            if not editable:
                continue
            choices.append((f"{definition.display_name}（{node.id}）", node.id))
            for parameter in editable:
                value = node.params.get(parameter, definition.defaults.get(parameter))
                rows.append(
                    {
                        "node_id": node.id,
                        "operator": node.op,
                        "parameter": parameter,
                        "value": value,
                        "source": "explicit"
                        if parameter in node.params
                        else "defaulted",
                    }
                )
        selected = choices[0][1] if choices else None
        parameters, value = self.atomic_parameter_for_node(
            effective_json, media_type, selected
        )
        return choices, selected, parameters, value, rows

    def atomic_parameter_for_node(
        self, effective_json: str, media_type: str, node_id: str | None
    ):
        if not node_id:
            return [], ""
        package = SkillPackage.model_validate_json(effective_json)
        variant = package.select_variant(_variant_key(media_type))
        node = next((item for item in variant.nodes if item.id == node_id), None)
        if node is None:
            return [], ""
        definition = self.registry.require(node.op)
        parameters = sorted(set(definition.parameters) | set(node.params))
        if not parameters:
            return [], ""
        name = parameters[0]
        value = node.params.get(name, definition.defaults.get(name))
        return parameters, self._dump(value)

    def atomic_parameter_value(
        self,
        effective_json: str,
        media_type: str,
        node_id: str,
        parameter: str,
    ) -> str:
        package = SkillPackage.model_validate_json(effective_json)
        variant = package.select_variant(_variant_key(media_type))
        node = next((item for item in variant.nodes if item.id == node_id), None)
        if node is None:
            return ""
        definition = self.registry.require(node.op)
        return self._dump(
            node.params.get(parameter, definition.defaults.get(parameter))
        )

    def apply_atomic_parameter(
        self,
        effective_json: str,
        media_type: str,
        node_id: str,
        parameter: str,
        value_text: str,
    ):
        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        variant = package.select_variant(key)
        node = next((item for item in variant.nodes if item.id == node_id), None)
        if node is None:
            raise gr.Error("找不到要编辑的原子节点")
        definition = self.registry.require(node.op)
        if parameter not in set(definition.parameters) | set(node.params):
            raise gr.Error("该参数不属于当前原子")
        try:
            value = json.loads(value_text)
        except json.JSONDecodeError:
            value = value_text
        data = package.model_dump(mode="json")
        target = next(
            item for item in data["variants"][key]["nodes"] if item["id"] == node_id
        )
        target["params"][parameter] = value
        try:
            updated = SkillPackage.model_validate(data)
            errors = validate_skill_package(updated, self.registry)
        except Exception as exc:
            raise gr.Error(f"原子参数无效：{exc}") from exc
        if errors:
            raise gr.Error("原子参数无效：" + "；".join(errors))
        return self._dump(updated), f"✅ 已更新 {node_id}.{parameter}；执行配置已同步。"

    @staticmethod
    def diff(generated_json: str, effective_json: str) -> str:
        return (
            "".join(
                difflib.unified_diff(
                    generated_json.splitlines(keepends=True),
                    effective_json.splitlines(keepends=True),
                    fromfile="generated_package",
                    tofile="effective_package",
                )
            )
            or "无修改"
        )

    def select_variant(self, effective_json: str, media_type: str):
        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        variant = package.variants.get(key)
        if variant is None:
            return "", f"⚠️ 当前技能未声明 {key} variant"
        if variant.status == "unsupported":
            return self._dump(variant), f"⚠️ {key} 不支持：{variant.issue}"
        return self._dump(
            variant
        ), f"✅ {key} variant 可执行，共 {len(variant.nodes)} 个节点"

    def apply_variant_json(
        self, effective_json: str, media_type: str, variant_json: str
    ) -> str:
        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        variant = WorkflowVariant.model_validate_json(variant_json)
        if variant.media_type != key:
            raise gr.Error(f"variant.media_type 必须是 {key}")
        data = package.model_dump(mode="json")
        data["variants"][key] = variant.model_dump(mode="json")
        updated = SkillPackage.model_validate(data)
        errors = validate_skill_package(updated, self.registry)
        if errors:
            raise gr.Error("variant 写回后校验失败：" + "；".join(errors))
        return self._dump(updated)

    @staticmethod
    def _default_grounding_query(params: dict[str, Any]) -> str:
        targets = [
            target for target in params.get("targets", []) if isinstance(target, dict)
        ]
        if params.get("phrase_selection") == "primary_per_target":
            phrases = [
                next(
                    (
                        phrase.strip()
                        for phrase in target.get("phrases", [])
                        if isinstance(phrase, str) and phrase.strip()
                    ),
                    "",
                )
                for target in targets
            ]
            phrases = [phrase for phrase in phrases if phrase]
        else:
            phrases = [
                str(phrase).strip()
                for target in targets
                for phrase in target.get("phrases", [])
                if isinstance(phrase, str) and phrase.strip()
            ]
        return f"Detect {', '.join(phrases)}" if phrases else "Detect requested targets"

    @staticmethod
    def _grounding_target_display(params: dict[str, Any]) -> str:
        """Show the exact model phrases, retaining business labels as context."""

        displays = []
        for target in params.get("targets", []):
            if not isinstance(target, dict):
                continue
            label = str(target.get("label") or "").strip()
            phrases = [
                str(phrase).strip()
                for phrase in target.get("phrases", [])
                if str(phrase).strip()
            ]
            phrase_text = " / ".join(dict.fromkeys(phrases))
            if not phrase_text:
                phrase_text = label
            if label and phrase_text and label.casefold() != phrase_text.casefold():
                displays.append(f"{phrase_text}（{label}）")
            elif phrase_text:
                displays.append(phrase_text)
            elif label:
                displays.append(label)
        return "；".join(dict.fromkeys(displays))

    def grounding_prompt_controls(
        self, effective_json: str, media_type: str
    ) -> list[dict[str, Any]]:
        """Expose the visual-query portion of every generic Rex Grounding node."""

        if not (effective_json or "").strip():
            return []
        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        variant = package.variants.get(key)
        if variant is None or variant.status == "unsupported":
            return []
        controls = []
        for node in variant.nodes:
            if not node.op.startswith("rex.ground@"):
                continue
            default_prompt = self._default_grounding_query(node.params)
            override = node.params.get("query_prompt")
            prompt = (
                override.strip()
                if isinstance(override, str) and override.strip()
                else default_prompt
            )
            labels = self._grounding_target_display(node.params)
            controls.append(
                {
                    "node_id": node.id,
                    "label": labels or node.id,
                    "op": node.op,
                    "prompt": prompt,
                    "default_prompt": default_prompt,
                    "is_override": prompt != default_prompt,
                }
            )
        return controls

    def _write_grounding_prompt(
        self,
        effective_json: str,
        media_type: str,
        node_id: str,
        query_prompt: str | None,
    ) -> str:
        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        data = package.model_dump(mode="json")
        variant = data["variants"].get(key)
        if not variant or variant["status"] == "unsupported":
            raise gr.Error(f"当前技能没有可编辑的 {key} variant")
        node = next((item for item in variant["nodes"] if item["id"] == node_id), None)
        if node is None or not str(node["op"]).startswith("rex.ground@"):
            raise gr.Error("请选择当前 variant 中的模型检测节点")
        if query_prompt is None:
            node["params"].pop("query_prompt", None)
        else:
            node["params"]["query_prompt"] = query_prompt
        updated = SkillPackage.model_validate(data)
        errors = validate_skill_package(updated, self.registry)
        if errors:
            raise gr.Error("模型检测提示词配置无效：" + "；".join(errors))
        return self._dump(updated)

    def apply_grounding_prompt_control(
        self,
        effective_json: str,
        media_type: str,
        node_id: str,
        query_prompt: str,
    ) -> str:
        prompt = (query_prompt or "").strip()
        if not prompt:
            raise gr.Error(
                "模型检测提示词不能为空；如需恢复默认短语，请点“还原默认短语提示词”"
            )
        return self._write_grounding_prompt(effective_json, media_type, node_id, prompt)

    def reset_grounding_prompt_control(
        self, effective_json: str, media_type: str, node_id: str
    ) -> str:
        return self._write_grounding_prompt(effective_json, media_type, node_id, None)

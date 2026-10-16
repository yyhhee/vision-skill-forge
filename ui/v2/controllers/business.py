"""BusinessRuleController: extracted V2 responsibilities, preserving public method signatures."""

from __future__ import annotations

import json
from typing import Any

import gradio as gr

from application.v2.support import _variant_key
from core.business_rule_editor import BusinessRuleEditError
from core.editor_schema import (
    SkillEditorDocument,
)
from ui.event_rule_editor import (
    friendly_choice_label,
    parse_parameter_table,
    render_branch_overview,
    render_branch_pattern,
    render_condition_tree,
    render_parameter_help,
)
from ui.v2.presentation import effective_condition_config_rows


class BusinessRuleController:
    def business_condition_input_help(
        self,
        document: SkillEditorDocument,
        media_type: str,
        branch_id: str | None,
        condition_id: str | None,
    ) -> str:
        """Explain the concrete upstream values consumed by one condition."""

        if not branch_id or not condition_id:
            return ""
        key = _variant_key(media_type)
        graph = document.skill_template.rule_graphs.get(key)
        if graph is None:
            return ""

        if condition_id.startswith("existing_node:"):
            node_id = condition_id.removeprefix("existing_node:")
            nodes = {item.node_id: item for item in graph.nodes}
            node = nodes.get(node_id)
            if node is None:
                return ""
            incoming: dict[str, list[str]] = {}
            for edge in graph.edges:
                if edge.target == node_id:
                    incoming.setdefault(edge.port or "input", []).append(edge.source)

            def describe_node(source_id: str, visited: set[str] | None = None) -> str:
                visited = set() if visited is None else visited
                if source_id in visited:
                    return source_id
                visited = {*visited, source_id}
                source = nodes.get(source_id)
                if source is None:
                    return source_id
                if source.operator and source.operator.startswith("rex.ground@"):
                    labels = [
                        str(item.get("label"))
                        for item in source.params.get("targets", [])
                        if isinstance(item, dict) and item.get("label")
                    ]
                    if labels:
                        return "、".join(dict.fromkeys(labels))
                labels = source.params.get("labels")
                if isinstance(labels, list) and labels:
                    return "、".join(str(item) for item in labels)
                if source.operator and source.operator.startswith("region."):
                    regions = source.params.get("regions")
                    if isinstance(regions, list) and regions:
                        return (
                            "、".join(
                                str(item.get("label") or item.get("id"))
                                for item in regions
                                if isinstance(item, dict)
                            )
                            or source.display_name
                        )
                parents = [
                    edge.source for edge in graph.edges if edge.target == source_id
                ]
                descriptions = list(
                    dict.fromkeys(describe_node(parent, visited) for parent in parents)
                )
                if len(descriptions) == 1:
                    return descriptions[0]
                if descriptions:
                    return f"{source.display_name}（{' + '.join(descriptions)}）"
                return source.display_name

            has_subject_object_pair = "subjects" in incoming and "objects" in incoming
            port_labels = {
                "subjects": "目标 A（主体）",
                "objects": (
                    "目标 B（关联对象）" if has_subject_object_pair else "目标对象"
                ),
                "left": "输入 A（左值）",
                "right": "输入 B（右值）",
                "condition": "上游条件",
                "conditions": "上游条件组",
                "frames": "输入画面",
                "media": "输入媒体",
                "video": "输入视频",
                "regions": "区域",
                "region": "区域",
                "directions": "方向",
                "direction": "方向",
                "references": "参考方向",
                "lanes": "区域或车道",
                "tracks": "目标轨迹",
                "entities": "待统计目标",
                "sets": "输入集合",
                "pairs": "目标配对结果",
                "values": "输入数值",
                "states": "输入状态",
                "events": "输入事件",
                "evidence": "证据对象",
            }
            lines = []
            for port, source_ids in incoming.items():
                descriptions = "、".join(
                    dict.fromkeys(describe_node(source_id) for source_id in source_ids)
                )
                lines.append(
                    f"- **{port_labels.get(port, f'输入 {port}')}**：{descriptions}"
                )
            relation = str(node.params.get("relation", ""))
            threshold = node.params.get("threshold")
            relation_help = {
                "mutual_match": "A 覆盖 B、且 B 覆盖 A 的比例都达到阈值，才视为同一位置的匹配目标。",
                "bidirectional": "A 覆盖 B、且 B 覆盖 A 的比例都达到阈值，才视为同一位置的匹配目标。",
                "overlap": "A 被 B 覆盖的比例达到阈值即成立。",
                "inside": "A 位于 B 内的覆盖比例达到阈值即成立。",
                "contains": "B 位于 A 内的覆盖比例达到阈值即成立。",
                "near": "A 与 B 的中心距离不超过阈值即成立。",
                "best_owner": "每个 B 只归给重叠比例最高且达到阈值的 A。",
                "source_entity": "B 必须来自 A 的局部裁剪或来源实体。",
                "center_in_subject_region": "B 的中心点必须落在 A 的指定相对部位内。",
            }.get(relation)
            if relation_help:
                suffix = (
                    f" 当前阈值为 {float(threshold):g}。"
                    if isinstance(threshold, (int, float))
                    else ""
                )
                lines.append(f"- **当前关系怎么用**：{relation_help}{suffix}")
            if not lines:
                return ""
            return "#### 当前算子作用对象\n" + "\n".join(lines)

        branch = next(
            (
                item
                for item in document.skill_template.business_branches
                if item.branch_id == branch_id
            ),
            None,
        )
        if branch is None or branch.condition_root is None:
            return ""
        stack = [branch.condition_root]
        expression = None
        while stack:
            current = stack.pop()
            if current.expression_id == condition_id:
                expression = current
                break
            stack.extend(current.children)
        if expression is None or not expression.capability_id:
            return ""
        definition = self.business_capabilities.require(expression.capability_id)
        source_parameters = [
            item for item in definition.parameters if item.editor == "source_select"
        ]
        if not source_parameters:
            return ""
        choices = {
            item["value"]: item["label"]
            for item in self.business_rule_editor.source_choices(
                document, branch_id, condition_id
            )
        }
        lines = []
        for parameter in source_parameters:
            value = expression.parameters.get(parameter.parameter_id)
            if value:
                lines.append(
                    f"- **{parameter.label}**：{choices.get(str(value), str(value))}"
                )
        if expression.capability_id == "attribute.color":
            mode = str(expression.parameters.get("verification_logic") or "AND").upper()
            mode_label = friendly_choice_label(mode)
            lines.extend(
                [
                    "- **条件 A（颜色占比）**：由“颜色、判断区域、颜色至少占该部位”控制。",
                    "- **条件 B（模型属性语义 + 同一主体归属）**：模型短语由基础目标与颜色自动生成，归属关系由系统确定性编译。",
                    f"- **A/B 组合**：当前为“{mode_label}”；可改为 A 与 B 同时满足、A 或 B 任一满足、仅颜色占比或仅模型属性证据。",
                ]
            )
        lines.append(
            "- **来源说明**：条件结构（A、B、C、D…）由 LLM 根据自然语言生成；执行原子由系统从已注册能力配方自动编译。可修改业务参数和组合方式，不能直接改执行原子。"
        )
        return "#### 当前条件作用对象\n" + "\n".join(lines) if lines else ""

    def business_rule_view(
        self,
        editor_json: str,
        media_type: str,
        branch_id: str | None = None,
        condition_id: str | None = None,
        include_tuning: bool = False,
    ) -> dict[str, Any]:
        """Build the complete 03 view model without depending on UI widgets."""

        if not editor_json:
            return {
                "document_json": "",
                "branches": [],
                "branch_id": None,
                "branch_name": "",
                "branch_overview": render_branch_overview([], None),
                "conditions": [],
                "condition_id": None,
                "condition_tree": render_condition_tree([]),
                "capabilities": [],
                "capability_id": None,
                "condition_name": "",
                "parameters": [],
                "parameter_table": [],
                "parameter_help": "生成或加载技能后，可在这里审核业务条件。",
            }
        document = self.business_rule_editor.prepare(
            self._parse_editor_json(editor_json)
        )
        key = _variant_key(media_type)
        branches = self.business_rule_editor.branch_rows(document, key)
        branch_ids = {item["branch_id"] for item in branches}
        selected_branch = (
            branch_id
            if branch_id in branch_ids
            else (branches[0]["branch_id"] if branches else None)
        )
        branch = next(
            (
                item
                for item in document.skill_template.business_branches
                if item.branch_id == selected_branch
            ),
            None,
        )
        conditions = (
            self.business_rule_editor.condition_rows(document, selected_branch)
            if selected_branch
            else []
        )
        atom_ids = [
            item["condition_id"] for item in conditions if item["kind"] == "条件"
        ]
        review_primary = next(
            (
                item["condition_id"]
                for item in conditions
                if item["kind"] == "条件" and item.get("review_primary")
            ),
            None,
        )
        selected_condition = (
            condition_id
            if condition_id in atom_ids
            else (review_primary or (atom_ids[0] if atom_ids else None))
        )
        expression = None
        if branch and branch.condition_root and selected_condition:
            expression = next(
                (
                    item
                    for item in self.business_rule_editor.condition_rows(
                        document, selected_branch
                    )
                    if item["condition_id"] == selected_condition
                ),
                None,
            )
        parameter_rows = (
            self.business_rule_editor.parameter_rows(
                document,
                selected_branch,
                selected_condition,
                include_tuning=include_tuning,
            )
            if selected_branch and selected_condition
            else []
        )
        capabilities = [
            definition
            for definition in self.business_capabilities.definitions()
            if key in definition.media_requirements
            and definition.category not in {"逻辑组合", "输出与证据", "时间与复杂编排"}
        ]
        capability_id = None
        condition_name = ""
        selected_row = next(
            (item for item in conditions if item["condition_id"] == selected_condition),
            None,
        )
        if selected_row is not None:
            capability_id = selected_row.get("capability_id")
            condition_name = (
                selected_row.get("configuration_name") or selected_row["name"]
            )
        if branch and branch.condition_root and selected_condition:
            stack = [branch.condition_root]
            while stack:
                item = stack.pop()
                if item.expression_id == selected_condition:
                    capability_id = item.capability_id
                    if not (
                        selected_row is not None
                        and selected_row.get("configuration_name")
                    ):
                        condition_name = item.display_name
                    break
                stack.extend(reversed(item.children))
        input_help = self.business_condition_input_help(
            document, key, selected_branch, selected_condition
        )
        parameter_help = render_parameter_help(parameter_rows)
        if input_help:
            parameter_help = input_help + "\n\n" + parameter_help
        return {
            "document_json": self._dump(document),
            "branches": branches,
            "branch_id": selected_branch,
            "branch_name": branch.display_name if branch else "",
            "branch_overview": render_branch_overview(branches, selected_branch),
            "conditions": conditions,
            "condition_id": selected_condition,
            "condition_tree": render_condition_tree(conditions),
            "capabilities": capabilities,
            "capability_id": capability_id
            or (capabilities[0].capability_id if capabilities else None),
            "condition_name": condition_name,
            "parameters": parameter_rows,
            "parameter_table": effective_condition_config_rows(
                parameter_rows, conditions, selected_condition
            ),
            "parameter_help": parameter_help,
            "input_help": input_help,
            "selected_condition": expression,
        }

    def business_rule_controls(
        self,
        editor_json: str,
        media_type: str,
        branch_id: str | None = None,
        condition_id: str | None = None,
        include_tuning: bool = False,
    ):
        view = self.business_rule_view(
            editor_json,
            media_type,
            branch_id,
            condition_id,
            include_tuning,
        )
        branch_choices = [
            (item["display_name"], item["branch_id"]) for item in view["branches"]
        ]
        condition_choices = [
            (
                f"{'　' * item['depth']}"  # noqa: ISC004 — preserved V2 behavior
                f"{item.get('configuration_name') or item['name']}"
                f" · {item['category']}"
                f"{'（依赖来源）' if item.get('dependency_only') else ''}",
                item["condition_id"],
            )
            for item in view["conditions"]
            if item["kind"] == "条件"
        ]
        capability_choices = [
            (
                f"{item.category} / {item.display_name}",
                item.capability_id,
            )
            for item in view["capabilities"]
        ]
        rows_by_id = {item["condition_id"]: item for item in view["conditions"]}
        group_choices = [
            (
                (
                    f"[整组结果] {item['name']}"
                    if item.get("parent_id") is None
                    else "[同层："
                    + rows_by_id.get(item.get("parent_id"), {}).get("name", "条件组")
                    + f"] {'　' * item.get('display_depth', item['depth'])}{item['name']}"
                ),
                item["condition_id"],
            )
            for item in view["conditions"]
            if not item.get("imported_step") and item.get("kind") in {"条件", "条件组"}
        ]
        has_imported_logic = any(
            item.get("imported_step") and item.get("kind") == "条件组"
            for item in view["conditions"]
        )
        return (
            view["document_json"],
            gr.Dropdown(
                choices=branch_choices,
                value=view["branch_id"],
                label="当前条件分支",
            ),
            view["branch_name"],
            view["branch_overview"],
            gr.Dropdown(
                choices=condition_choices,
                value=view["condition_id"],
                label="当前编辑条件",
            ),
            view["condition_tree"],
            gr.Dropdown(
                choices=capability_choices,
                value=view["capability_id"],
                label="新增哪类条件",
            ),
            view["condition_name"],
            view["parameter_table"],
            view["parameter_help"],
            gr.update(visible=bool(group_choices) and not has_imported_logic),
            gr.Dropdown(
                choices=group_choices,
                value=[],
                multiselect=True,
                label="选择条件或条件组（AND/OR/N 需同层；NOT 选一项）",
                interactive=bool(group_choices),
            ),
        )

    @staticmethod
    def _friendly_parameter_choices(values: list[Any]) -> list[tuple[str, Any]]:
        return [(friendly_choice_label(value), value) for value in values]

    def business_parameter_controls(
        self,
        editor_json: str,
        media_type: str,
        branch_id: str | None,
        condition_id: str | None,
        include_tuning: bool,
        parameter_id: str | None = None,
    ):
        hidden = gr.update(visible=False)
        if not editor_json or not branch_id or not condition_id:
            return (
                gr.update(choices=[], value=None),
                gr.update(value="请选择一条业务条件。", visible=True),
                hidden,
                hidden,
                hidden,
                hidden,
                hidden,
                hidden,
                "当前没有可修改参数。",
            )
        view = self.business_rule_view(
            editor_json,
            media_type,
            branch_id,
            condition_id,
            include_tuning,
        )
        branch_id = view["branch_id"]
        condition_id = view["condition_id"]
        if not branch_id or not condition_id:
            return (
                gr.update(choices=[], value=None),
                gr.update(value="当前分支没有可编辑条件。", visible=True),
                hidden,
                hidden,
                hidden,
                hidden,
                hidden,
                hidden,
                "当前没有可修改参数。",
            )
        document = self._parse_editor_json(view["document_json"])
        rows = self.business_rule_editor.parameter_rows(
            document, branch_id, condition_id, include_tuning=include_tuning
        )
        ids = {row["parameter_id"] for row in rows}
        selected = (
            parameter_id
            if parameter_id in ids
            else (rows[0]["parameter_id"] if rows else None)
        )
        row = next((item for item in rows if item["parameter_id"] == selected), None)
        selector = gr.update(
            choices=[(item["name"], item["parameter_id"]) for item in rows],
            value=selected,
        )
        if row is None:
            return (
                selector,
                gr.update(value="没有参数。", visible=True),
                hidden,
                hidden,
                hidden,
                hidden,
                hidden,
                hidden,
                "",
            )

        editor = row["editor"]
        choices = list(row.get("choices") or [])
        if editor == "source_select":
            choices = [
                (item["label"], item["value"])
                for item in self.business_rule_editor.source_choices(
                    document, branch_id, condition_id
                )
            ]
        elif editor in {"scene_resource_select", "direction_resource_select"}:
            wanted = "region" if editor == "scene_resource_select" else "direction"
            choices = []
            if editor == "scene_resource_select":
                choices.append(("全画面", "full_frame"))
            for requirement in document.skill_template.resource_requirements:
                if requirement.resource_type.startswith(wanted):
                    choices.append(
                        (requirement.display_name, requirement.requirement_id)
                    )
            active_profile = next(
                (
                    profile
                    for profile in document.scene_profiles
                    if profile.scene_profile_id == document.active_scene_profile_id
                ),
                None,
            )
            if active_profile:
                requirement_names = {
                    item.requirement_id: item.display_name
                    for item in document.skill_template.resource_requirements
                }
                for collection in active_profile.collections:
                    for item in collection.items:
                        if item.resource_type == wanted:
                            choices.append(
                                (
                                    f"{requirement_names.get(collection.requirement_id, item.display_name)} / {item.display_name}",
                                    item.resource_id,
                                )
                            )
        editable_single = editor in {
            "select",
            "source_select",
            "scene_resource_select",
            "direction_resource_select",
        } and bool(choices)
        editable_multi = editor == "multi_select" and bool(choices)
        editable_open_multi = editor == "multi_select" and not choices
        editable_text = editor == "text"
        editable_number = editor in {
            "number",
            "duration",
            "frames",
            "percentage",
            "angle_degrees",
        }
        editable_boolean = editor == "boolean"
        fixed = not any(
            (
                editable_single,
                editable_multi,
                editable_open_multi,
                editable_text,
                editable_number,
                editable_boolean,
            )
        )
        value = row.get("value")
        shown = (
            json.dumps(value, ensure_ascii=False)
            if isinstance(value, (list, dict))
            else str(value or "")
        )
        editable_text_value = (
            "，".join(str(item) for item in value) if isinstance(value, list) else shown
        )
        source = row.get("source") or "系统"
        status = (
            f"**{row['name']}**：{row['help']}  \n当前来源：{source}。"
            + ("请从固定选项中选择。" if editable_single or editable_multi else "")
            + (
                "可输入一个或多个业务值，多个值使用逗号分隔。"
                if editable_open_multi
                else ""
            )
            + ("可直接修改这项业务文本。" if editable_text else "")
            + ("请输入数值。" if editable_number else "")
            + ("该项由系统派生或在其它配置区维护，仅供确认。" if fixed else "")
        )
        if view.get("input_help"):
            status = f"{view['input_help']}\n\n{status}"
        return (
            selector,
            gr.update(
                value=shown if fixed else "",
                visible=fixed,
                label=f"{row['name']}（只读）",
            ),
            gr.update(
                choices=(
                    self._friendly_parameter_choices(choices)
                    if choices and not isinstance(choices[0], tuple)
                    else choices
                ),
                value=value if editable_single else None,
                visible=editable_single,
                label=row["name"],
            ),
            gr.update(
                choices=self._friendly_parameter_choices(choices),
                value=value if editable_multi and isinstance(value, list) else [],
                visible=editable_multi,
                label=row["name"],
            ),
            gr.update(
                value=value if editable_number else None,
                minimum=row.get("minimum"),
                maximum=row.get("maximum"),
                precision=0 if editor == "frames" else None,
                visible=editable_number,
                label=row["name"] + (f"（{row['unit']}）" if row.get("unit") else ""),
            ),
            gr.update(
                value=value if editable_boolean else None,
                visible=editable_boolean,
                label=row["name"],
            ),
            gr.update(
                value=editable_text_value if editable_text else "",
                visible=editable_text,
                label=row["name"],
            ),
            gr.update(
                value=editable_text_value if editable_open_multi else "",
                visible=editable_open_multi,
                label=row["name"],
            ),
            status,
        )

    def business_apply_parameter(
        self,
        editor_json: str,
        branch_id: str,
        condition_id: str,
        parameter_id: str,
        single_value: Any,
        multi_value: list[Any] | None,
        number_value: float | None,
        boolean_value: bool | None,
        text_value: str | None,
        open_multi_value: str | None,
        include_tuning: bool,
    ) -> tuple[str, str]:
        try:
            document = self._parse_editor_json(editor_json)
            rows = self.business_rule_editor.parameter_rows(
                document, branch_id, condition_id, include_tuning=include_tuning
            )
            selected = next(
                (item for item in rows if item["parameter_id"] == parameter_id), None
            )
            if selected is None:
                raise BusinessRuleEditError("请选择可修改的配置项。")
            editor = selected["editor"]
            if editor in {
                "select",
                "source_select",
                "scene_resource_select",
                "direction_resource_select",
            }:
                value = single_value
            elif editor == "multi_select" and selected.get("choices"):
                value = multi_value or []
            elif editor == "multi_select":
                value = [
                    item.strip()
                    for item in str(open_multi_value or "")
                    .replace("，", ",")
                    .split(",")
                    if item.strip()
                ]
            elif editor == "text":
                value = text_value
            elif editor in {
                "number",
                "duration",
                "frames",
                "percentage",
                "angle_degrees",
            }:
                value = number_value
            elif editor == "boolean":
                value = boolean_value
            else:
                raise BusinessRuleEditError(
                    "该项是 LLM 建议或系统固定内容，不允许直接修改。"
                )
            parameters = {item["parameter_id"]: item.get("value") for item in rows}
            parameters[parameter_id] = value
            document = self.business_rule_editor.update_condition(
                document, branch_id, condition_id, parameters=parameters
            )
        except (BusinessRuleEditError, KeyError, ValueError) as exc:
            raise gr.Error(str(exc)) from exc
        return (
            self._dump(document),
            f"✅ 已更新“{selected['name']}”到 03 草稿（尚未生效）；请点击【校验并生成当前运行版本（使修改生效）】。",
        )

    def business_add_branch(
        self, editor_json: str, media_type: str, display_name: str
    ) -> tuple[str, str]:
        try:
            document = self.business_rule_editor.add_branch(
                self._parse_editor_json(editor_json),
                _variant_key(media_type),
                display_name,
            )
        except (BusinessRuleEditError, KeyError, ValueError) as exc:
            raise gr.Error(str(exc)) from exc
        return (
            self._dump(document),
            "✅ 已新增条件分支到 03 草稿（尚未生效）；配置完成后请点击【校验并生成当前运行版本（使修改生效）】。",
        )

    def business_branch_action(
        self,
        editor_json: str,
        branch_id: str,
        action: str,
        display_name: str,
    ) -> tuple[str, str]:
        try:
            document = self._parse_editor_json(editor_json)
            if action == "重命名":
                document = self.business_rule_editor.rename_branch(
                    document, branch_id, display_name
                )
            elif action == "复制":
                document = self.business_rule_editor.copy_branch(
                    document, branch_id, display_name or None
                )
            elif action == "删除":
                document = self.business_rule_editor.delete_branch(document, branch_id)
            else:
                raise BusinessRuleEditError("不支持的分支操作。")
        except (BusinessRuleEditError, KeyError, ValueError) as exc:
            raise gr.Error(str(exc)) from exc
        return (
            self._dump(document),
            f"✅ 分支已{action}，当前仍是 03 草稿（尚未生效）；请点击【校验并生成当前运行版本（使修改生效）】。",
        )

    def business_add_condition(
        self, editor_json: str, branch_id: str, capability_id: str
    ) -> tuple[str, str, str]:
        try:
            document, condition_id = self.business_rule_editor.add_condition(
                self._parse_editor_json(editor_json),
                branch_id,
                capability_id,
            )
        except (BusinessRuleEditError, KeyError, ValueError) as exc:
            raise gr.Error(str(exc)) from exc
        definition = self.business_capabilities.require(capability_id)
        return (
            self._dump(document),
            condition_id,
            f"✅ 已新增“{definition.display_name}”到 03 草稿（尚未生效）；完成参数后请点击【校验并生成当前运行版本（使修改生效）】。",
        )

    def business_condition_action(
        self,
        editor_json: str,
        branch_id: str,
        condition_id: str,
        action: str,
    ) -> tuple[str, str, str | None]:
        try:
            document = self._parse_editor_json(editor_json)
            selected: str | None = condition_id
            if action == "复制":
                document, selected = self.business_rule_editor.copy_condition(
                    document, branch_id, condition_id
                )
            elif action == "删除":
                document = self.business_rule_editor.delete_condition(
                    document, branch_id, condition_id
                )
                selected = None
            elif action == "删除（含依赖）":
                document = self.business_rule_editor.delete_condition(
                    document, branch_id, condition_id, cascade=True
                )
                selected = None
            elif action == "NOT 取反":
                document, _ = self.business_rule_editor.group_expressions(
                    document, branch_id, [condition_id], "NOT"
                )
                # Groups are visible in the tree but the parameter editor keeps
                # focus on a leaf, so refresh chooses the first available leaf.
                selected = condition_id
            else:
                raise BusinessRuleEditError("不支持的条件操作。")
        except (BusinessRuleEditError, KeyError, ValueError) as exc:
            raise gr.Error(str(exc)) from exc
        return (
            self._dump(document),
            f"✅ 条件已{action}，当前仍是 03 草稿（尚未生效）；请点击【校验并生成当前运行版本（使修改生效）】。",
            selected,
        )

    def business_group_conditions(
        self,
        editor_json: str,
        branch_id: str,
        condition_ids: list[str],
        operator: str,
        required_count: int | None,
    ) -> tuple[str, str]:
        try:
            document, _ = self.business_rule_editor.group_expressions(
                self._parse_editor_json(editor_json),
                branch_id,
                condition_ids or [],
                operator,
                required_count=int(required_count or 1),
            )
        except (BusinessRuleEditError, KeyError, ValueError) as exc:
            raise gr.Error(str(exc)) from exc
        message = (
            "✅ 已取消该节点的 NOT 取反，当前仍是 03 草稿（尚未生效）；请点击【校验并生成当前运行版本（使修改生效）】。"
            if operator == "NOT"
            and len(condition_ids or []) == 1
            and any(
                item["condition_id"] == condition_ids[0] and item["logic"] == "NOT"
                for item in self.business_rule_editor.condition_rows(
                    self._parse_editor_json(editor_json), branch_id
                )
            )
            else f"✅ 已按 {operator} 编排所选节点，当前仍是 03 草稿（尚未生效）；请点击【校验并生成当前运行版本（使修改生效）】。"
        )
        return self._dump(document), message

    def business_expression_logic_controls(
        self,
        editor_json: str,
        branch_id: str | None,
        group_id: str | None = None,
    ):
        hidden = gr.update(visible=False)
        if not editor_json or not branch_id:
            return (
                hidden,
                gr.update(choices=[], value=None),
                gr.update(choices=[], value=None),
                gr.update(value=1, visible=False),
                gr.update(value=False, visible=False),
                gr.update(value=""),
            )
        try:
            groups = self.business_rule_editor.expression_logic_groups(
                self._parse_editor_json(editor_json), branch_id
            )
        except (BusinessRuleEditError, KeyError, ValueError):
            groups = []
        selected = next(
            (item for item in groups if item["group_id"] == group_id),
            groups[0] if groups else None,
        )
        if selected is None:
            return (
                hidden,
                gr.update(choices=[], value=None),
                gr.update(choices=[], value=None),
                gr.update(value=1, visible=False),
                gr.update(value=False, visible=False),
                gr.update(value=""),
            )
        is_not = selected["operator"] == "NOT"
        members = "、".join(selected.get("members", [])) or "未读取到直接成员"
        operator_choices = (
            [("条件取反（NOT）", "NOT")]
            if is_not
            else [
                ("全部满足（AND）", "AND"),
                ("任一满足（OR）", "OR"),
                ("至少 N 项满足（N-of-M）", "N_OF_M"),
            ]
        )
        return (
            gr.update(visible=True),
            gr.update(
                choices=[
                    (
                        f"{'　' * item['depth']}{item['display_name']} · {item['summary']}",
                        item["group_id"],
                    )
                    for item in groups
                ],
                value=selected["group_id"],
            ),
            gr.update(
                choices=operator_choices,
                value=selected["operator"],
                interactive=not is_not,
            ),
            gr.update(
                value=selected["required_count"],
                minimum=1,
                maximum=max(1, selected["condition_count"]),
                visible=selected["operator"] == "N_OF_M",
            ),
            gr.update(value=selected["negated"], visible=True),
            gr.update(
                value=(
                    f"**组内条件：** {members}  \n"
                    f"**当前判断：** `{selected['summary']}`  \n"
                    + (
                        "关闭“反转结果”即可恢复原判断。"
                        if is_not
                        else f"共 {selected['condition_count']} 项；修改后只影响这一层括号。"
                    )
                )
            ),
        )

    def business_update_expression_logic(
        self,
        editor_json: str,
        branch_id: str,
        group_id: str,
        operator: str,
        required_count: int,
        negated: bool,
    ) -> tuple[str, str]:
        try:
            updated = self.business_rule_editor.update_expression_logic_group(
                self._parse_editor_json(editor_json),
                branch_id,
                group_id,
                operator,
                required_count=int(required_count or 1),
                negated=bool(negated),
            )
        except (BusinessRuleEditError, KeyError, ValueError) as exc:
            raise gr.Error(str(exc)) from exc
        return (
            self._dump(updated),
            "✅ 已保存嵌套条件组关系到 03 草稿（尚未生效）；请点击【校验并生成当前运行版本（使修改生效）】。",
        )

    def business_imported_logic_controls(
        self,
        editor_json: str,
        branch_id: str | None,
        group_id: str | None = None,
    ):
        if not editor_json or not branch_id:
            return (
                gr.update(visible=False),
                gr.update(choices=[], value=None, visible=False),
                gr.update(value="AND", visible=False),
                gr.update(value=1, visible=False),
                gr.update(value=False, visible=False),
                gr.update(value="", visible=False),
            )
        document = self._parse_editor_json(editor_json)
        groups = self.business_rule_editor.imported_logic_groups(document, branch_id)
        selected = next(
            (item for item in groups if item["group_id"] == group_id),
            groups[0] if groups else None,
        )
        if selected is None:
            return (
                gr.update(visible=False),
                gr.update(choices=[], value=None, visible=False),
                gr.update(value="AND", visible=False),
                gr.update(value=1, visible=False),
                gr.update(value=False, visible=False),
                gr.update(value="", visible=False),
            )
        count = selected["condition_count"]
        members = "、".join(selected.get("members", [])) or "未读取到直接成员"
        relation_text = {
            "AND": "全部条件都成立",
            "OR": "任一条件成立",
            "N_OF_M": f"至少 {selected['required_count']} 项成立",
        }.get(selected["operator"], selected["operator"])
        return (
            gr.update(visible=True),
            gr.update(
                choices=[
                    (
                        f"{item['display_name']}（{item['condition_count']}项）",
                        item["group_id"],
                    )
                    for item in groups
                ],
                value=selected["group_id"],
                visible=True,
            ),
            gr.update(value=selected["operator"], visible=True),
            gr.update(
                value=min(selected["required_count"], max(1, count)),
                minimum=1,
                maximum=max(1, count),
                visible=selected["operator"] == "N_OF_M",
            ),
            gr.update(value=selected["negated"], visible=True),
            gr.update(
                value=(
                    f"**组内条件：** {members}  \n"
                    f"**当前判断：** {relation_text}（共 {count} 项）"
                    + ("；结果已反转（NOT）。" if selected["negated"] else "。")
                ),
                visible=True,
            ),
        )

    def business_update_imported_logic(
        self,
        editor_json: str,
        branch_id: str,
        group_id: str,
        operator: str,
        required_count: int,
        negated: bool,
    ) -> tuple[str, str]:
        try:
            updated = self.business_rule_editor.update_imported_logic_group(
                self._parse_editor_json(editor_json),
                branch_id,
                group_id,
                operator,
                required_count=int(required_count or 1),
                negated=bool(negated),
            )
        except (BusinessRuleEditError, KeyError, ValueError) as exc:
            raise gr.Error(str(exc)) from exc
        return (
            self._dump(updated),
            "✅ 已修改 03 草稿中的条件关系（尚未生效）；请点击【校验并生成当前运行版本（使修改生效）】，04 才会使用新逻辑。",
        )

    def business_apply_condition(
        self,
        editor_json: str,
        branch_id: str,
        condition_id: str,
        condition_name: str,
        table: list[list[Any]],
        include_tuning: bool,
    ) -> tuple[str, str]:
        try:
            document = self._parse_editor_json(editor_json)
            schema_rows = self.business_rule_editor.parameter_rows(
                document,
                branch_id,
                condition_id,
                include_tuning=include_tuning,
            )
            parameters = parse_parameter_table(table, schema_rows)
            document = self.business_rule_editor.update_condition(
                document,
                branch_id,
                condition_id,
                display_name=condition_name,
                parameters=parameters,
            )
        except (BusinessRuleEditError, KeyError, ValueError) as exc:
            raise gr.Error(str(exc)) from exc
        return (
            self._dump(document),
            "✅ 条件参数已保存到 03 草稿（尚未生效）；请点击【校验并生成当前运行版本（使修改生效）】，04 才会使用新参数。",
        )

    def business_branch_time_controls(self, editor_json: str, branch_id: str | None):
        defaults = (
            "immediate",
            None,
            None,
            100,
            0,
            "global",
            "first",
            "current_frame",
            None,
            "当前分支立即判断，不附加持续约束。",
        )
        if not editor_json or not branch_id:
            return defaults
        document = self.business_rule_editor.prepare(
            self._parse_editor_json(editor_json)
        )
        branch = next(
            (
                item
                for item in document.skill_template.business_branches
                if item.branch_id == branch_id
            ),
            None,
        )
        if branch is None:
            return defaults
        qualifier = next(
            (item for item in branch.temporal_qualifiers if item.enabled), None
        )
        mode = qualifier.mode if qualifier else "immediate"
        duration = (
            qualifier.duration_seconds.value
            if qualifier and qualifier.duration_seconds.state != "not_applicable"
            else None
        )
        window = (
            qualifier.observation_window_seconds.value
            if qualifier
            and qualifier.observation_window_seconds.state != "not_applicable"
            else None
        )
        ratio = (qualifier.required_ratio * 100) if qualifier else 100
        gap = qualifier.allowed_gap_seconds if qualifier else 0
        identity = qualifier.identity_scope if qualifier else "global"
        emission = qualifier.emission if qualifier else "first"
        validity = branch.validity_policy
        hold = (
            validity.hold_seconds.value
            if validity.hold_seconds.state != "not_applicable"
            else None
        )
        status = (
            f"当前分支时间方式：{mode}；按 {identity} 维持；有效状态：{validity.mode}。"
        )
        return (
            mode,
            duration,
            window,
            ratio,
            gap,
            identity,
            emission,
            validity.mode,
            hold,
            status,
        )

    def business_apply_branch_time(
        self,
        editor_json: str,
        branch_id: str,
        mode: str,
        duration_seconds: float | None,
        observation_window_seconds: float | None,
        required_ratio_percent: float,
        allowed_gap_seconds: float,
        identity_scope: str,
        emission: str,
        validity_mode: str,
        hold_seconds: float | None,
    ) -> tuple[str, str]:
        try:
            document = self.business_rule_editor.set_branch_time_policy(
                self._parse_editor_json(editor_json),
                branch_id,
                mode=mode,
                duration_seconds=duration_seconds,
                observation_window_seconds=observation_window_seconds,
                required_ratio=float(required_ratio_percent or 0) / 100.0,
                allowed_gap_seconds=float(allowed_gap_seconds or 0),
                identity_scope=identity_scope,
                emission=emission,
                validity_mode=validity_mode,
                hold_seconds=hold_seconds,
            )
        except (BusinessRuleEditError, KeyError, ValueError) as exc:
            raise gr.Error(str(exc)) from exc
        return (
            self._dump(document),
            "✅ 分支时间与有效状态策略已保存到 03 草稿（尚未生效）；请点击【校验并生成当前运行版本（使修改生效）】。",
        )

    @staticmethod
    def _friendly_result_kind(value: str) -> str:
        return {
            "decision": "最终结论",
            "boolean": "是否满足",
            "count": "数量",
            "value": "数值",
            "entities": "目标框/目标列表",
            "tracks": "轨迹",
            "events": "事件列表",
            "duration": "持续时间",
            "timeline": "阶段时间线",
            "media": "标注媒体",
        }.get(value, value)

    @staticmethod
    def _internal_result_kind(value: str) -> str:
        mapping = {
            "最终结论": "decision",
            "是否满足": "boolean",
            "数量": "count",
            "数值": "value",
            "目标框/目标列表": "entities",
            "轨迹": "tracks",
            "事件列表": "events",
            "持续时间": "duration",
            "阶段时间线": "timeline",
            "标注媒体": "media",
        }
        return mapping.get(value, value)

    def _business_source_choices(
        self,
        document: SkillEditorDocument,
        *,
        include_results: bool = True,
        include_final: bool = True,
    ) -> tuple[list[tuple[str, str]], dict[str, str], dict[str, str]]:
        choices: list[tuple[str, str]] = []
        label_to_ref: dict[str, str] = {}
        ref_to_label: dict[str, str] = {}
        label_counts: dict[str, int] = {}
        sources = self.business_rule_editor.source_catalog(
            document, include_final=include_final
        )
        if include_results:
            sources.extend(
                {
                    "value": f"result:{spec.result_id}",
                    "label": f"业务输出 / {spec.display_name}",
                    "type": spec.semantic_type,
                }
                for spec in document.skill_template.result_specs
            )
        for source in sources:
            base = source["label"]
            label_counts[base] = label_counts.get(base, 0) + 1
            label = (
                base
                if label_counts[base] == 1
                else f"{base}（同名{label_counts[base]}）"
            )
            ref = source["value"]
            choices.append((label, ref))
            label_to_ref[label] = ref
            ref_to_label[ref] = label
        return choices, label_to_ref, ref_to_label

    @staticmethod
    def _event_pattern_mode(pattern) -> str:
        if pattern.pattern_type == "sequence":
            return "sequence"
        if pattern.pattern_type in {"absence", "repeat"}:
            return pattern.pattern_type
        return pattern.gateways[0].mode if pattern.gateways else "none"

    def _event_pattern_formula(
        self,
        pattern,
        branches: dict[str, str],
        patterns: dict[str, Any],
        visiting: set[str] | None = None,
    ) -> str:
        """Return a compact recursive business formula for one orchestration group."""

        visiting = set(visiting or ())
        if pattern.pattern_id in visiting:
            return "循环引用"
        visiting.add(pattern.pattern_id)
        members = []
        for stage in pattern.stages:
            source_ref = stage.source_ref or ""
            if source_ref.startswith("branch:"):
                source_id = source_ref.split(":", 1)[1]
                members.append(branches.get(source_id, stage.display_name))
            elif source_ref.startswith("event:"):
                source_id = source_ref.split(":", 1)[1]
                child = patterns.get(source_id)
                members.append(
                    f"（{self._event_pattern_formula(child, branches, patterns, visiting)}）"
                    if child
                    else stage.display_name
                )
            else:
                members.append(stage.display_name)
        mode = self._event_pattern_mode(pattern)
        if mode == "sequence":
            return " → ".join(members)
        if mode == "n_of_m":
            required = pattern.gateways[0].required_count if pattern.gateways else 1
            return f"至少 {required or 1} 项（" + "、".join(members) + "）"
        connector = {
            "all_completed": " AND ",
            "all_active": " AND ",
            "all_completed_within_window": " AND ",
            "exclusive": " XOR ",
            "any": " OR ",
        }.get(mode, "、")
        return connector.join(members)

    def business_secondary_controls(self, editor_json: str, media_type: str):
        if not editor_json:
            empty = gr.update(choices=[], value=None)
            return (
                empty,
                "none",
                None,
                1,
                "global",
                "当前未启用跨分支复杂编排。",
                "最终结果",
                "event_decision",
                empty,
                "AND",
                1,
                True,
                True,
                [],
                "none",
                0,
                "medium",
                ["event_record"],
                gr.update(visible=False),
            )
        document = self.business_rule_editor.prepare(
            self._parse_editor_json(editor_json)
        )
        key = _variant_key(media_type)
        branches = [
            item
            for item in document.skill_template.business_branches
            if item.media_type == key
        ]
        branch_index = {item.branch_id: item for item in branches}  # noqa: F841 — preserved V2 behavior
        branch_labels = {
            item.branch_id: f"分支 {index} · {item.display_name}"
            for index, item in enumerate(branches, start=1)
        }
        branch_refs = {f"branch:{item.branch_id}" for item in branches}  # noqa: F841 — preserved V2 behavior
        media_patterns = [
            item
            for item in document.skill_template.event_patterns
            if item.media_type == key
        ]
        pattern_index = {item.pattern_id: item for item in media_patterns}
        referenced_patterns = {
            stage.source_ref.split(":", 1)[1]
            for item in media_patterns
            for stage in item.stages
            if stage.source_ref and stage.source_ref.startswith("event:")
        }
        top_level_patterns = [
            item
            for item in media_patterns
            if item.pattern_id not in referenced_patterns
        ]
        pattern = (top_level_patterns or media_patterns)[-1] if media_patterns else None
        pattern_choices = [
            (f"条件分支 / {branch_labels[item.branch_id]}", f"branch:{item.branch_id}")
            for item in branches
        ]
        pattern_choices.extend(
            (
                f"已编排组 / {self._event_pattern_formula(item, branch_labels, pattern_index)}",
                f"event:{item.pattern_id}",
            )
            for item in media_patterns
        )
        pattern_mode = "none"
        selected_branches: list[str] = []
        window = None
        required = None
        correlation = "global"
        pattern_status = render_branch_pattern("none", [])
        if pattern is not None:
            selected_branches = [
                stage.source_ref for stage in pattern.stages if stage.source_ref
            ]
            correlation = pattern.correlation.scope
            if pattern.pattern_type == "sequence":
                pattern_mode = "sequence"
                delays = [
                    item.maximum_delay_seconds.value
                    for item in pattern.transitions
                    if item.maximum_delay_seconds.state != "not_applicable"
                ]
                window = delays[0] if delays else None
            elif pattern.pattern_type in {"absence", "repeat"}:
                pattern_mode = pattern.pattern_type
                window = pattern.parameters.get("window_seconds")
                required = pattern.parameters.get("minimum_count")
            elif pattern.gateways:
                gateway = pattern.gateways[0]
                pattern_mode = gateway.mode
                required = gateway.required_count
                window = (
                    gateway.window_seconds.value
                    if gateway.window_seconds.state != "not_applicable"
                    else None
                )
            selected_names = []
            for source_ref in selected_branches:
                prefix, source_id = source_ref.split(":", 1)
                if prefix == "branch":
                    selected_names.append(branch_labels.get(source_id, source_id))
                else:
                    source = pattern_index.get(source_id)
                    selected_names.append(
                        f"（{self._event_pattern_formula(source, branch_labels, pattern_index)}）"
                        if source
                        else source_id
                    )
            pattern_status = render_branch_pattern(
                pattern_mode,
                selected_names,
                required_count=required,
                window_seconds=window,
                correlation_scope=correlation,
            )
        source_choices, _, ref_to_label = self._business_source_choices(  # noqa: RUF059 — preserved V2 behavior
            document, include_final=False
        )
        final_choices = [
            (f"条件分支 / {item.display_name}", f"branch:{item.branch_id}")
            for item in branches
        ]
        final_choices.extend(
            (f"分支编排 / {item.display_name}", f"event:{item.pattern_id}")
            for item in document.skill_template.event_patterns
            if item.media_type == key
        )
        final_choice_refs = {value for _, value in final_choices}
        final = document.skill_template.final_decision
        final_source = (
            [ref for ref in final.source_refs if ref in final_choice_refs]
            if final
            else []
        )
        if not final_source:
            final_source = [value for _, value in final_choices]
        result_rows = []
        for row in self.business_rule_editor.result_rows(document):
            result_rows.append(
                [
                    row["display_name"],
                    ref_to_label.get(row["source_ref"], row["source_ref"]),
                    self._friendly_result_kind(row["result_kind"]),
                    row["unit"],
                    {
                        "required": "必须保存",
                        "optional": "尽量保存",
                        "none": "不需要",
                    }[row["evidence_policy"]],
                    {
                        "always": "每次保存",
                        "on_change": "变化时保存",
                        "on_match": "满足时保存",
                        "never": "不保存",
                    }[row["save_policy"]],
                    "是" if row["show_in_overview"] else "否",
                ]
            )
        trigger = document.skill_template.trigger_policy
        pattern_mode_choices = [
            ("不组合，直接由最终判定处理", "none"),
            ("顺序：逐个完成", "sequence"),
            ("并行：全部完成", "all_completed"),
            ("互斥选择：最先完成一个即结束", "exclusive"),
            ("任意完成（或）：任一完成即结束", "any"),
            ("部分汇聚：达到指定完成数量", "n_of_m"),
        ]
        if pattern_mode not in {value for _, value in pattern_mode_choices}:
            pattern_mode_choices.append(
                (f"历史关系：{pattern_mode}（重新选择后替换）", pattern_mode)
            )
        return (
            gr.Dropdown(
                choices=pattern_choices,
                value=selected_branches,
                multiselect=True,
                label="参与本组的分支或已编排组（顺序关系按选择先后）",
            ),
            gr.Dropdown(choices=pattern_mode_choices, value=pattern_mode),
            window,
            required or 1,
            correlation,
            pattern_status,
            final.display_name if final else "最终结果",
            final.decision_type if final else "event_decision",
            gr.Dropdown(
                choices=final_choices,
                value=final_source,
                multiselect=True,
                label="哪些分支参与最终告警",
            ),
            final.combination if final else "AND",
            (final.required_count or 1) if final else 1,
            final.show_reason if final else True,
            final.show_failed_or_pending_branches if final else True,
            result_rows,
            trigger.mode,
            trigger.cooldown_seconds,
            trigger.severity,
            trigger.outputs,
            gr.update(visible=len(branches) > 1),
        )

    def business_apply_pattern(
        self,
        editor_json: str,
        media_type: str,
        mode: str,
        branch_ids: list[str],
        window_seconds: float | None,
        required_count: int | None,
        correlation_scope: str,
    ) -> tuple[str, str]:
        try:
            document = self.business_rule_editor.set_complex_pattern(
                self._parse_editor_json(editor_json),
                _variant_key(media_type),
                mode,
                branch_ids or [],
                window_seconds=window_seconds,
                required_count=(int(required_count) if required_count else None),
                correlation_scope=correlation_scope,
                display_name="分支编排组",
            )
        except (BusinessRuleEditError, KeyError, ValueError) as exc:
            raise gr.Error(str(exc)) from exc
        return (
            self._dump(document),
            "✅ 分支编排已保存到 03 草稿（尚未生效）；该组可继续与其它分支或编排组组合。完成后请点击【校验并生成当前运行版本（使修改生效）】。",
        )

    def business_apply_final(
        self,
        editor_json: str,
        display_name: str,
        decision_type: str,
        source_refs: list[str],
        combination: str,
        required_count: int | None,
        show_reason: bool,
        show_failed: bool,
    ) -> tuple[str, str]:
        try:
            document = self.business_rule_editor.set_final_decision(
                self._parse_editor_json(editor_json),
                display_name,
                decision_type,
                (source_refs or [""])[0],
                source_refs=source_refs or [],
                combination=combination,
                required_count=(int(required_count or 1)),
                show_reason=show_reason,
                show_failed_or_pending_branches=show_failed,
            )
        except (BusinessRuleEditError, KeyError, ValueError) as exc:
            raise gr.Error(str(exc)) from exc
        return (
            self._dump(document),
            "✅ 最终判定已保存到 03 草稿（尚未生效）；请点击【校验并生成当前运行版本（使修改生效）】。",
        )

    def business_add_output_row(self, rows: list[list[Any]] | None) -> list[list[Any]]:
        return [
            *(rows or []),
            ["新业务输出", "", "最终结论", "", "尽量保存", "每次保存", "是"],
        ]

    @staticmethod
    def business_output_delete_choices(rows: list[list[Any]] | None):
        names = [
            str(row[0]).strip() for row in (rows or []) if row and str(row[0]).strip()
        ]
        return gr.update(choices=names, value=names[0] if names else None)

    @staticmethod
    def business_delete_output_row(
        rows: list[list[Any]] | None, selected_name: str | None
    ) -> list[list[Any]]:
        current = list(rows or [])
        selected = str(selected_name or "").strip()
        if not selected:
            raise gr.Error("请先选择要删除的业务输出。")
        matched = [
            index
            for index, row in enumerate(current)
            if row and str(row[0]).strip() == selected
        ]
        if not matched:
            raise gr.Error("所选业务输出已不存在，请刷新后重试。")
        if len(current) <= 1:
            raise gr.Error("至少需要保留一个业务输出。")
        return [row for index, row in enumerate(current) if index != matched[0]]

    def business_apply_outputs(
        self, editor_json: str, rows: list[list[Any]] | None
    ) -> tuple[str, str]:
        try:
            document = self.business_rule_editor.prepare(
                self._parse_editor_json(editor_json)
            )
            _, label_to_ref, _ = self._business_source_choices(
                document, include_results=False
            )
            existing = self.business_rule_editor.result_rows(document)
            existing_by_name = {
                item["display_name"]: item["result_id"] for item in existing
            }
            parsed = []
            for index, row in enumerate(rows or []):
                values = [*row, "", "", "", "", "", "", ""][:7]
                name = str(values[0]).strip()
                source_label = str(values[1]).strip()
                source_ref = label_to_ref.get(source_label, source_label)
                parsed.append(
                    {
                        "result_id": existing_by_name.get(name),
                        "display_name": name,
                        "source_ref": source_ref,
                        "result_kind": self._internal_result_kind(
                            str(values[2]).strip()
                        ),
                        "unit": str(values[3]).strip(),
                        "evidence_policy": {
                            "必须保存": "required",
                            "尽量保存": "optional",
                            "不需要": "none",
                        }.get(str(values[4]).strip(), str(values[4]).strip()),
                        "save_policy": {
                            "每次保存": "always",
                            "变化时保存": "on_change",
                            "满足时保存": "on_match",
                            "不保存": "never",
                        }.get(str(values[5]).strip(), str(values[5]).strip()),
                        "show_in_overview": str(values[6]).strip().lower()
                        not in {"否", "false", "0", "不显示"},
                    }
                )
            document = self.business_rule_editor.set_result_rows(document, parsed)
        except (BusinessRuleEditError, KeyError, ValueError) as exc:
            raise gr.Error(str(exc)) from exc
        return (
            self._dump(document),
            "✅ 业务输出与展示初稿已保存（尚未生效）；请点击【校验并生成当前运行版本（使修改生效）】。",
        )

    def business_apply_trigger(
        self,
        editor_json: str,
        mode: str,
        cooldown_seconds: float,
        severity: str,
        outputs: list[str],
    ) -> tuple[str, str]:
        try:
            document = self.business_rule_editor.set_trigger_policy(
                self._parse_editor_json(editor_json),
                mode=mode,
                cooldown_seconds=cooldown_seconds,
                severity=severity,
                outputs=outputs or [],
            )
        except (BusinessRuleEditError, KeyError, ValueError) as exc:
            raise gr.Error(str(exc)) from exc
        return (
            self._dump(document),
            "✅ 触发策略已保存到 03 草稿（尚未生效）；条件语义和持续约束未被改变。请点击【校验并生成当前运行版本（使修改生效）】。",
        )

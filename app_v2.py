from __future__ import annotations

import difflib
import json
import os
import re
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any

import gradio as gr

from clients.rex_client import RexGateway
from clients.v2_planner import DeepSeekSemanticPlanner
from core.annotation import (
    annotations_from_package,
    extract_annotation_frame,
    normalize_canvas_point,
    render_annotation_workspace,
)
from core.configuration import ConfigurationBinder, configuration_status
from core.editor_generation import build_editor_document, resolve_pending_decision
from core.editor_schema import SkillEditorDocument
from core.editor_service import EditorMutationError, EditorService
from core.media_assets import MediaAssetStore
from core.media_policy import inspect_execution_policy
from core.migration import migrate_v1_spec
from core.persistence import PackageStore, RunStore, SkillDocumentStore
from core.preset_factory import apply_context_confirmation
from core.preset_media import PresetMediaCatalog, seed_builtin_preset_media
from core.registry import OperatorRegistry, build_default_registry
from core.recipes import build_recipe_catalog
from core.runtime import SkillPackageRuntime, detect_media_type
from core.schema import SkillPackage, VisualSkillSpec, WorkflowVariant
from core.validator import validate_skill_package
from core.video_sampling import normalize_end_seconds


ROOT = Path(__file__).resolve().parent
NO_ANNOTATION_SLOT = "__no_annotation_required__"
MEDIA_CHOICES = {
    "仅图片": ["image"],
    "仅视频": ["video"],
    "图片和视频": ["image", "video"],
}
ANNOTATION_GUIDANCE_MARKDOWN = """
<section class="vs-section">
  <h2>仅当技能要求命名区域或方向参考时才需要标注</h2>
  <p class="vs-section-copy"><strong>什么时候需要这一步：</strong>技能涉及“在哪里”“朝哪个参考方向”或“区域之间的关系”时才标注，例如进入限制区、区域内计数、危险区域逗留、沿指定方向运动。普通的检测人/车/物可直接运行。</p>
  <div class="vs-guide">
    <div class="vs-guide-item"><b>矩形</b><span>按住拖拽框出规则区域，适合检测区、限制区。</span></div>
    <div class="vs-guide-item"><b>多边形</b><span>沿边界逐点点击，适合不规则区域。</span></div>
    <div class="vs-guide-item"><b>方向箭头</b><span>拖出规则所需的参考方向；箭头含义由当前技能规则决定。</span></div>
    <div class="vs-guide-item"><b>画完要保存</b><span>点“保存标注到技能”才会真正生效，可删除重画。</span></div>
  </div>
</section>
"""


def _variant_key(value: str) -> str:
    if value == "仅图片":
        return "image"
    if value == "仅视频":
        return "video"
    if value.startswith("image"):
        return "image"
    if value.startswith("video"):
        return "video"
    if value in {"image", "video"}:
        return value
    raise ValueError(f"unknown variant: {value}")


def json_object_or_empty(value: str | None) -> dict[str, Any]:
    """Keep UI synchronization callbacks harmless after an upstream error."""

    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


class V2AppController:
    def __init__(
        self,
        *,
        registry: OperatorRegistry,
        package_root: Path,
        run_root: Path,
        planner,
        rex,
        asset_root: Path | None = None,
        preset_catalog_path: Path | None = None,
    ):
        self.registry = registry
        self.package_store = PackageStore(package_root)
        self.document_store = SkillDocumentStore(package_root.parent / "skill_documents")
        self.run_store = RunStore(run_root)
        self.planner = planner
        self.rex = rex
        self.preset_root = ROOT / "presets_v2"
        self.asset_store = MediaAssetStore(
            asset_root or package_root.parent / "media_assets"
        )
        self.preset_media_catalog = PresetMediaCatalog(
            preset_catalog_path
            or package_root.parent / "preset_media_defaults.json",
            self.asset_store,
        )
        self.configuration_binder = ConfigurationBinder(registry)
        self.editor_service = EditorService(registry)

    @staticmethod
    def _dump(value: Any) -> str:
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        return json.dumps(value, ensure_ascii=False, indent=2)

    def preferred_executable_variant(
        self, effective_json: str, preferred: str = "image"
    ) -> str:
        """Choose a real executable variant rather than trusting a UI default."""

        package = SkillPackage.model_validate_json(effective_json)
        preferred_key = _variant_key(preferred)
        candidates = [preferred_key, *package.input.accept]
        for key in dict.fromkeys(candidates):
            variant = package.variants.get(key)
            if variant is not None and variant.status != "unsupported":
                return key
        raise gr.Error("当前技能没有可执行的图片或视频流程")

    @staticmethod
    def editor_variant_for_media(media_type: str) -> str:
        return f"{_variant_key(media_type)} variant"

    @classmethod
    def cleared_task_media_state(cls):
        return (
            "",
            {},
            None,
            {},
            "已清除当前任务媒体；已运行结果和产物目录不受影响。",
            "image",
            "image",
            cls.runtime_media_summary("", "image"),
            "image variant",
        )

    def preset_names(self) -> list[str]:
        return [path.stem for path in sorted(self.preset_root.glob("P*.json"))]

    def preset_default_media(self, preset_name: str, media_type: str):
        if not preset_name:
            raise gr.Error("请选择预置演示技能")
        key = _variant_key(media_type)
        asset = self.preset_media_catalog.get_default(preset_name, key)
        if asset is None:
            raise gr.Error(f"{preset_name} 尚未配置 {key} 默认素材")
        candidates = self.preset_media_catalog.list_candidates(preset_name, key)
        return (
            asset.stored_path,
            key,
            asdict(asset),
            candidates,
            f"✅ 已加载 {preset_name} 的 {key} 默认素材：{asset.original_name}",
        )

    def set_preset_default_media(
        self, preset_name: str, media_path: str
    ):
        if not preset_name:
            raise gr.Error("只有当前来源为预置技能时才能设置默认素材")
        if not media_path:
            raise gr.Error("请先上传或加载素材")
        try:
            asset = self.preset_media_catalog.add_candidate(
                preset_name, media_path, set_default=False
            )
            selected = self.preset_media_catalog.set_default(
                preset_name, asset.media_type, asset.asset_id
            )
        except (ValueError, FileNotFoundError) as exc:
            raise gr.Error(str(exc)) from exc
        candidates = self.preset_media_catalog.list_candidates(
            preset_name, selected.media_type
        )
        return (
            selected.stored_path,
            candidates,
            f"✅ 已显式设为默认：{preset_name} / {selected.media_type} / {selected.original_name}",
        )

    def saved_skill_choices(self) -> list[str]:
        return self.package_store.list_versions()

    def compile_skill(
        self,
        instruction: str,
        media_choice: str,
        skill_id: str,
        display_name: str,
    ):
        if self.planner is None:
            raise gr.Error("DeepSeek Planner 尚未配置")
        text = instruction.strip()
        identity = skill_id.strip()
        name = display_name.strip()
        if not text or not identity or not name:
            raise gr.Error("自然语言、技能标识和显示名称都必须填写")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", identity):
            raise gr.Error(
                "技能标识只能以英文字母开头，由字母、数字、_ 或 - 组成（不能用中文），"
                "例如 loiter_detection；显示名称可以保留中文。"
            )
        requested = MEDIA_CHOICES.get(media_choice)
        if requested is None:
            raise gr.Error("请选择媒体能力")
        result = self.planner.compile(
            text,
            requested_accept=requested,
            skill_id=identity,
            display_name=name,
        )
        if result.package is None:
            detail = "；".join(result.errors) or "语义账本无法无损编译"
            raise gr.Error(f"需要人工确认：{detail}")
        package = result.package
        package_json = self._dump(package)
        semantic_json = self._dump(package.semantic_ir)
        issues = "；".join(issue.message for issue in package.compatibility_issues)
        status = (
            f"✅ Semantic IR + 固定编译器完成；LLM 调用 {result.attempts} 次；"
            f"实际支持 {', '.join(package.input.accept)}。"
        )
        if issues:
            status += f"兼容性说明：{issues}"
        source = (
            "### 当前实际执行来源\n"
            f"**自然语言生成** · `{package.skill_id}/v{package.version}` · "
            f"**{package.display_name}**  \n"
            "未使用预置演示技能；运行对象是下方可编辑的 Effective SkillPackage。"
        )
        return package_json, package_json, semantic_json, status, source

    def load_preset(self, preset_name: str):
        if not preset_name:
            raise gr.Error("请选择预置演示技能")
        path = self.preset_root / f"{preset_name}.json"
        raw = json.loads(path.read_text("utf-8"))
        if raw.get("schema_version") == "2.0":
            package = SkillPackage.model_validate(raw)
            note = "V2 预置"
        else:
            package = migrate_v1_spec(VisualSkillSpec.model_validate(raw))
            note = "旧预置已显式迁移；语义需重新确认"
        text = self._dump(package)
        source = (
            "### 当前实际执行来源\n"
            f"**预置演示技能** · `{preset_name}` · **{package.display_name}**  \n"
            "自然语言输入未参与当前技能。"
        )
        return (
            text,
            text,
            self._dump(package.semantic_ir),
            f"已加载 {note}：{package.display_name}",
            source,
        )

    def load_preset_bundle(self, preset_name: str, timestamp: float = 0.0):
        """Load a preset and its deterministic default media as one UI action."""

        generated, effective, semantic, skill_status, source = self.load_preset(
            preset_name
        )
        package = SkillPackage.model_validate_json(effective)
        media_type = (
            "image" if "image" in package.input.accept else package.input.accept[0]
        )
        path, media_type, _, candidates, media_status = self.preset_default_media(
            preset_name, media_type
        )
        stored_path, metadata, preview, state, ingest_status = self.ingest_media(
            path, timestamp
        )
        combined_status = (
            f"{skill_status}；已自动加载 {media_type} 默认素材。"
        )
        annotation_status = f"{media_status}；{ingest_status}"
        return (
            generated,
            effective,
            semantic,
            combined_status,
            source,
            media_type,
            media_type,
            stored_path,
            metadata,
            candidates,
            stored_path,
            package.original_instruction,
            preview,
            state,
            annotation_status,
            preset_name,
            "[]",
            self.runtime_media_summary(stored_path, media_type),
            self.editor_variant_for_media(media_type),
        )

    def load_saved_skill(self, selection: str):
        if not selection or "/v" not in selection:
            raise gr.Error("请选择已保存技能")
        skill_id, version = selection.rsplit("/v", 1)
        package = self.package_store.load(skill_id, int(version))
        text = self._dump(package)
        source = (
            "### 当前实际执行来源\n"
            f"**已保存技能** · `{selection}` · **{package.display_name}**  \n"
            "自然语言输入和预置均未参与当前技能。"
        )
        return text, text, self._dump(package.semantic_ir), f"已加载 {selection}", source

    def save_skill(
        self, effective_json: str, skill_id: str = "", display_name: str = ""
    ) -> str:
        package = SkillPackage.model_validate_json(effective_json)
        errors = validate_skill_package(package, self.registry)
        if errors:
            raise gr.Error("保存前校验失败：" + "；".join(errors))
        try:
            return str(self.package_store.save(
                package,
                skill_id=skill_id.strip() or None,
                display_name=display_name.strip() or None,
            ))
        except (ValueError, FileNotFoundError) as exc:
            raise gr.Error(str(exc)) from exc

    def save_skill_bundle(
        self,
        effective_json: str,
        editor_json: str,
        skill_id: str = "",
        display_name: str = "",
    ) -> str:
        document = self._editor_document(effective_json, editor_json)
        if document.effective_skill_package is None:
            raise gr.Error("03 中存在未应用草稿，不能保存为正式版本")
        package_path = self.save_skill(effective_json, skill_id, display_name)
        try:
            document_path = self.document_store.save(
                document,
                skill_id=skill_id.strip() or None,
                display_name=display_name.strip() or None,
            )
        except (ValueError, FileNotFoundError) as exc:
            raise gr.Error(str(exc)) from exc
        return f"运行包：{package_path}\n可编辑文档：{document_path}"

    def delete_saved_skill(self, selection: str) -> str:
        if not selection or "/v" not in selection:
            raise gr.Error("请选择要删除的自定义技能版本")
        skill_id, version = selection.rsplit("/v", 1)
        self.package_store.delete(skill_id, int(version))
        return f"已删除自定义技能版本：{selection}；预置技能不受影响。"

    def validate_json(self, effective_json: str) -> str:
        try:
            package = SkillPackage.model_validate_json(effective_json)
            errors = validate_skill_package(package, self.registry)
            return "✅ V2 SkillPackage 校验通过，可执行" if not errors else (
                "❌\n" + "\n".join(errors)
            )
        except Exception as exc:
            return "❌\n" + str(exc)

    def editor_document_projection(self, effective_json: str) -> tuple[str, str]:
        """Expose the V3 editor model without replacing the proven V2 runtime."""

        package = SkillPackage.model_validate_json(effective_json)
        document = build_editor_document(package, source_type="legacy")
        requirements = document.skill_template.resource_requirements
        result_specs = document.skill_template.result_specs
        lines = [
            "### 通用组合模型",
            "运行仍使用当前 Effective SkillPackage；编辑层已投影为 SkillEditorDocument@3.0。",
            f"- 原子节点：{sum(len(item.nodes) for item in package.variants.values())}",
            f"- 结果规格：{len(result_specs)}",
        ]
        if requirements:
            lines.append(
                "- 场景资源：按实际视频动态添加，区域/车道数量无需提前确定；内部 ID 自动生成。"
            )
        else:
            lines.append("- 场景资源：当前技能无需手工区域或方向。")
        return self._dump(document), "\n".join(lines)

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
        results = [item.model_dump(mode="json") for item in document.skill_template.result_specs]
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
            gr.Dropdown(choices=branches, value=branch_value),
            gr.Dropdown(choices=nodes, value=node_value),
            gr.Dropdown(choices=operators, value=operators[0][1] if operators else None),
            gr.Dropdown(choices=nodes, value=node_value),
            gr.Dropdown(choices=nodes, value=None),
            gr.Dropdown(choices=params, value=parameter),
            value,
            self._dump([item.model_dump(mode="json") for item in document.skill_template.event_patterns]),
            gr.Dropdown(
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
            return gr.Dropdown(choices=[], value=None), ""
        document = SkillEditorDocument.model_validate_json(editor_json)
        params, selected, value = self._unified_node_parameter_values(
            document, _variant_key(media_type), node_id
        )
        return gr.Dropdown(choices=params, value=selected), value

    def unified_parameter_value(
        self, editor_json: str, media_type: str, node_id: str, parameter: str
    ) -> str:
        if not editor_json or not node_id or not parameter:
            return ""
        document = SkillEditorDocument.model_validate_json(editor_json)
        _, _, value = self._unified_node_parameter_values(
            document, _variant_key(media_type), node_id, parameter
        )
        return value

    def unified_apply_parameter(
        self, editor_json: str, node_id: str, parameter: str, value_text: str
    ):
        document = SkillEditorDocument.model_validate_json(editor_json)
        try:
            value = json.loads(value_text)
        except json.JSONDecodeError:
            value = value_text
        try:
            updated = self.editor_service.set_parameter(document, node_id, parameter, value)
        except EditorMutationError as exc:
            raise gr.Error(str(exc)) from exc
        return self._dump(updated), f"已记录用户覆盖：{node_id}.{parameter}；应用整个配置后进入运行版本。"

    def unified_reset_parameter(
        self, editor_json: str, node_id: str, parameter: str
    ):
        document = SkillEditorDocument.model_validate_json(editor_json)
        try:
            updated = self.editor_service.reset_parameter(document, node_id, parameter)
        except EditorMutationError as exc:
            raise gr.Error(str(exc)) from exc
        return self._dump(updated), f"已恢复 LLM 生成/系统默认值：{node_id}.{parameter}"

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
        document = SkillEditorDocument.model_validate_json(editor_json)
        key = _variant_key(media_type)
        try:
            if action == "新增原子":
                updated = self.editor_service.add_node(
                    document, key, operator, new_node_id, branch_id=branch_id or None
                )
            elif action == "复制原子":
                updated = self.editor_service.copy_node(document, key, selected_node, new_node_id)
            elif action == "删除原子":
                updated = self.editor_service.delete_node(document, key, selected_node)
            elif action == "替换能力":
                updated = self.editor_service.replace_node_operator(document, key, selected_node, operator)
            elif action == "连接原子":
                updated = self.editor_service.connect(document, key, source_node, target_node, port)
            elif action == "断开连接":
                updated = self.editor_service.disconnect(document, key, source_node, target_node, port or None)
            else:
                raise EditorMutationError("请选择图编辑动作")
        except EditorMutationError as exc:
            raise gr.Error(str(exc)) from exc
        return self._dump(updated), f"已完成：{action}。当前为未应用草稿。"

    def unified_mutate_branch(
        self,
        editor_json: str,
        media_type: str,
        action: str,
        branch_id: str,
        new_branch_id: str,
        display_name: str,
    ):
        document = SkillEditorDocument.model_validate_json(editor_json)
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
                    item for item in document.skill_template.business_branches
                    if item.branch_id == branch_id
                )
                updated = self.editor_service.update_branch(
                    document, branch_id, enabled=not branch.enabled
                )
            elif action == "上移":
                updated = self.editor_service.update_branch(document, branch_id, move=-1)
            elif action == "下移":
                updated = self.editor_service.update_branch(document, branch_id, move=1)
            elif action == "删除分支":
                updated = self.editor_service.delete_branch(document, branch_id)
            else:
                raise EditorMutationError("请选择业务分支动作")
        except (EditorMutationError, StopIteration) as exc:
            raise gr.Error(str(exc) or "找不到业务分支") from exc
        return self._dump(updated), f"已完成：{action}。当前为未应用草稿。"

    def unified_insert_recipe(
        self, editor_json: str, media_type: str, recipe_id: str, branch_id: str
    ):
        document = SkillEditorDocument.model_validate_json(editor_json)
        try:
            updated = self.editor_service.insert_recipe(
                document, _variant_key(media_type), recipe_id, branch_id or None
            )
        except EditorMutationError as exc:
            raise gr.Error(str(exc)) from exc
        return self._dump(updated), f"已插入可复用 Recipe：{recipe_id}。请补齐外部输入并校验。"

    def unified_apply_patterns(self, editor_json: str, patterns_json: str):
        document = SkillEditorDocument.model_validate_json(editor_json)
        try:
            patterns = json.loads(patterns_json or "[]")
            if not isinstance(patterns, list):
                raise ValueError("EventPattern 必须是数组")
            updated = self.editor_service.set_event_patterns(document, patterns)
        except (ValueError, EditorMutationError, json.JSONDecodeError) as exc:
            raise gr.Error(str(exc)) from exc
        return self._dump(updated), "复杂事件编排草稿已更新；请执行完整校验并应用。"

    def unified_resolve_pending(
        self, editor_json: str, decision_id: str, value_text: str
    ):
        if not decision_id:
            raise gr.Error("当前没有可确认的不确定条件")
        document = SkillEditorDocument.model_validate_json(editor_json)
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
        return self._dump(updated), f"已确认：{decision_id}。请完整校验并应用。"

    def unified_apply_results(self, editor_json: str, results_json: str):
        document = SkillEditorDocument.model_validate_json(editor_json)
        try:
            specs = json.loads(results_json or "[]")
            if not isinstance(specs, list):
                raise ValueError("ResultSpec 必须是数组")
            updated = self.editor_service.set_result_specs(document, specs)
        except (ValueError, EditorMutationError, json.JSONDecodeError) as exc:
            raise gr.Error(str(exc)) from exc
        return self._dump(updated), "结果与证据契约已写入草稿；请完整校验并应用。"

    def unified_validate_apply(self, editor_json: str):
        document = SkillEditorDocument.model_validate_json(editor_json)
        try:
            compiled = self.editor_service.apply(document)
        except Exception as exc:
            raise gr.Error(f"配置不能应用：{exc}") from exc
        package = compiled.effective_skill_package
        if package is None:
            raise gr.Error("编译未生成 Effective SkillPackage")
        pending = compiled.validation_report.get("pending", [])
        status = "✅ 全部原子、连接、分支和复杂事件已校验，并生成当前运行版本。"
        if pending:
            status = f"⚠️ 结构已编译，但仍有 {len(pending)} 项不确定条件，确认前禁止运行。"
        return self._dump(compiled), self._dump(package), status

    def _editor_document(
        self, effective_json: str, editor_json: str, source_type: str = "legacy"
    ) -> SkillEditorDocument:
        if editor_json:
            try:
                existing = SkillEditorDocument.model_validate_json(editor_json)
                package = SkillPackage.model_validate_json(effective_json)
                existing_package = existing.effective_skill_package
                same_effective = (
                    existing_package is not None
                    and existing_package.model_dump(mode="json")
                    == package.model_dump(mode="json")
                )
                if (
                    existing.skill_template.skill_id == package.skill_id
                    and (existing_package is None or same_effective)
                ):
                    return existing
            except Exception:
                pass
        package = SkillPackage.model_validate_json(effective_json)
        return build_editor_document(package, source_type=source_type)

    def _unified_node_parameter_values(
        self,
        document: SkillEditorDocument,
        media_type: str,
        node_id: str | None,
        selected: str | None = None,
    ):
        graph = document.skill_template.rule_graphs.get(media_type)
        node = next((item for item in (graph.nodes if graph else []) if item.node_id == node_id), None)
        if node is None or node.operator is None:
            return [], None, ""
        definition = self.registry.require(node.operator)
        params = sorted(set(definition.parameters) | set(node.params))
        parameter = selected if selected in params else (params[0] if params else None)
        if parameter is None:
            return params, None, ""
        override = next(
            (
                item for item in reversed(document.user_overrides)
                if item.target_id == node.node_id and item.parameter == parameter
            ),
            None,
        )
        value = override.value if override else node.params.get(parameter, definition.defaults.get(parameter))
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
                rows.append({
                    "node_id": node.id,
                    "operator": node.op,
                    "parameter": parameter,
                    "value": value,
                    "source": "explicit" if parameter in node.params else "defaulted",
                })
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
        return self._dump(node.params.get(parameter, definition.defaults.get(parameter)))

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
        return "".join(difflib.unified_diff(
            generated_json.splitlines(keepends=True),
            effective_json.splitlines(keepends=True),
            fromfile="generated_package",
            tofile="effective_package",
        )) or "无修改"

    def select_variant(self, effective_json: str, media_type: str):
        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        variant = package.variants.get(key)
        if variant is None:
            return "", f"⚠️ 当前技能未声明 {key} variant"
        if variant.status == "unsupported":
            return self._dump(variant), f"⚠️ {key} 不支持：{variant.issue}"
        return self._dump(variant), f"✅ {key} variant 可执行，共 {len(variant.nodes)} 个节点"

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
        phrases = [
            str(phrase).strip()
            for target in params.get("targets", [])
            if isinstance(target, dict)
            for phrase in target.get("phrases", [])
            if isinstance(phrase, str) and phrase.strip()
        ]
        return f"Detect {', '.join(phrases)}" if phrases else "Detect requested targets"

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
            prompt = override.strip() if isinstance(override, str) and override.strip() else default_prompt
            labels = [
                str(target["label"])
                for target in node.params.get("targets", [])
                if isinstance(target, dict) and target.get("label")
            ]
            controls.append({
                "node_id": node.id,
                "label": "、".join(labels) or node.id,
                "op": node.op,
                "prompt": prompt,
                "default_prompt": default_prompt,
                "is_override": prompt != default_prompt,
            })
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
        node = next(
            (item for item in variant["nodes"] if item["id"] == node_id), None
        )
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
            raise gr.Error("模型检测提示词不能为空；如需恢复默认短语，请点“还原默认短语提示词”")
        return self._write_grounding_prompt(effective_json, media_type, node_id, prompt)

    def reset_grounding_prompt_control(
        self, effective_json: str, media_type: str, node_id: str
    ) -> str:
        return self._write_grounding_prompt(effective_json, media_type, node_id, None)

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
                node for node in variant.nodes
                if node.id == "preprocess_tiles" and node.op == "image.tile@1.1"
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
        dedup_params = dict(
            self.registry.require("objects.deduplicate@1.0").defaults
        )
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
                (
                    node for node in variant.nodes
                    if node.op.startswith("video.sample@")
                ),
                None,
            )
            if sample is None:
                raise gr.Error("video variant 没有显式抽帧节点")
            sample_params = dict(self.registry.require(sample.op).defaults)
            sample_params.update(sample.params)
            sample_mode = sample_params["mode"]
            if sample_mode == "frame_step" and sample_params["frame_step"] == 1:
                sample_mode = "original_fps"
            result.update({
                "sample_mode": sample_mode,
                "fps": sample_params["fps"],
                "interval_seconds": sample_params["interval_seconds"],
                "frame_step": sample_params["frame_step"],
                "start_seconds": sample_params["start_seconds"],
                "end_seconds": normalize_end_seconds(sample_params["end_seconds"]),
                "max_frames": sample_params["max_frames"],
            })
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
                return "不满足（" + describe(
                    node_for(node.inputs.get("condition")), visited
                ) + "）"
            if node.op == "filter.apply@1.0":
                return "检测到" + str(
                    node.params.get("output_label") or event_label or "目标"
                )
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

        return event_label, describe(node_for(event_node.inputs.get("condition")), set())

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
                lines.append("- 当前技能没有事件阈值；检测结果可直接在“04 运行与结果”查看。")
        for control in controls:
            categories = "、".join(control["categories"]) or "当前检测目标"
            if control["condition_kind"] == "direction":
                condition = "按车道参考方向判断相反方向"
            else:
                parts = [
                    item["measure"].replace("目标", "")
                    .replace("每个命名区域内", "每个命名区域 ")
                    + f" {item['operator']} {item['value']:g}"
                    for item in control["comparisons"]
                ]
                connector = " AND " if control["logic"] == "all" else " OR "
                condition = connector.join(parts) or control["condition_summary"]
            lines.extend([
                f"\n**{control['event_label']}**",
                f"- {categories} → {condition} → 持续 {control['seconds']:g} 秒 → 告警“{control['event_label']}”。",
                f"- {control['atom_summary']}",
            ])
        if slot_rows:
            labels = "、".join(row["label"] for row in slot_rows if row["active"])
            lines.append(
                f"\n**下一步配置**：先到“02 标注”配置 {labels}；"
                f"再到“03 审核”调整上述阈值、持续与告警。"
            )
        else:
            automatic_regions = self._automatic_region_labels(effective_json, media_type)
            if automatic_regions:
                lines.append(
                    "\n**下一步配置**：02 标注显示的区域由检测结果自动生成（"
                    + "、".join(automatic_regions)
                    + "），不可手工删除或编辑；如需调整规则，到“03 审核”修改后运行。"
                )
            else:
                lines.append("\n**下一步配置**：无需场景标注；如需调整规则，到“03 审核”修改后运行。")
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
                item for item in ground.params.get("targets", [])
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
                        params.get("relation") in {
                            "overlap", "mutual_match", "inside", "contains"
                        }
                        and subject is not None
                        and object_ is not None
                        and isinstance(threshold, (int, float))
                    ):
                        associations.append({
                            "node_id": node.id,
                            "label": association_labels.get(
                                params.get("relation"), "目标空间关联"
                            ),
                            "relation": str(params.get("relation", "overlap")),
                            "threshold": float(threshold),
                            "subject": dict(subject),
                            "object": dict(object_),
                            "candidates": [dict(item) for item in candidate_entries],
                        })
                for reference in node.inputs.values():
                    references = reference if isinstance(reference, list) else [reference]
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
            logic_node = condition if condition.op in {"logic.all@1.0", "logic.any@1.0"} else None
            references = (
                condition.inputs.get("conditions", []) if logic_node else [f"${condition.id}"]
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
                        state_conditions.append({
                            "node_id": comparison.id,
                            "op": comparison.op,
                            "label": definition.display_name if definition else comparison.op,
                            "params": dict(comparison.params),
                        })
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
                    comparison_data["region_choices"] = [dict(item) for item in region_entries]
                comparisons.append(comparison_data)
            if category_node is None:
                category_node = first_ground(condition)
            alert = next(
                (
                    node for node in variant.nodes
                    if node.op == "output.alert@1.0"
                    and node.inputs.get("events") == f"${event.id}"
                ),
                None,
            )
            categories = [
                target["label"]
                for target in (category_node.params.get("targets", []) if category_node else [])
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
            condition_kind = (
                "direction" if is_direction
                else "comparison" if comparisons and not state_conditions
                else "state" if state_conditions and not comparisons
                else "composite"
            )
            condition_summary = self.temporal_rule_summary(variant, event)[1]
            atom_summary = (
                "这是方向/空间关系，不是数量或速度比较；需要在“02 标注”配置命名车道区域和参考方向箭头。"
                if is_direction
                else (
                    "这是布尔/状态条件原子；系统按上游目标关联或状态判断逐帧计算，"
                    "可在本页修改持续时间、允许中断、触发方式和告警。"
                    if condition_kind == "state" else
                    "这是由状态与数值原子组合的复合条件；可分别调整数值卡和整组事件策略。"
                    if condition_kind == "composite" else
                    (
                        f"统计范围：{scope_labels.get(scope, str(scope))}；"
                        "可在本页修改类别、阈值、逻辑、持续与告警。"
                    )
                )
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
                    "all" if logic_node is None else logic_node.op.split(".")[1].split("@")[0]
                ),
                "condition_kind": condition_kind,
                "condition_summary": condition_summary,
                "atom_summary": atom_summary,
                "seconds": float(params["seconds"]),
                "gap_tolerance_seconds": float(params["gap_tolerance_seconds"]),
                "trigger_mode": params["trigger_mode"],
                "alert_node_id": alert.id if alert is not None else None,
            }
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
            len(comparison_ids)
            == len(comparison_operators)
            == len(comparison_values)
        ):
            raise gr.Error("比较条件参数数量不一致")
        if region_bindings is not None and len(region_bindings) != len(comparison_ids):
            raise gr.Error("条件对应区域数量必须与比较条件一致")
        allowed_operators = {">", ">=", "=", "<=", "<", "==", "!="}
        if any(operator not in allowed_operators for operator in comparison_operators):
            raise gr.Error("比较符必须是 >、>=、=、<=、<、== 或 !=")
        comparison_operators = [
            "==" if operator == "=" else operator
            for operator in comparison_operators
        ]

        current = next(
            (
                item for item in self.read_event_rule_controls(
                    effective_json, media_type
                )
                if item["event_id"] == event_id
            ),
            None,
        )
        if current is None:
            raise gr.Error("找不到要编辑的事件规则")
        permitted_comparisons = {
            item["node_id"] for item in current["comparisons"]
        }
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
                override_by_comparison.setdefault(comparison_id, {})[region_id] = float(value)
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
                    package.display_name
                    if label == semantic_target_label else label
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
        if event is None or event["op"] not in {"temporal.persist@1.0", "event.from_condition@1.0"}:
            raise gr.Error("找不到要编辑的事件规则")
        current = next(
            (item for item in self.read_event_rule_controls(effective_json, media_type)
             if item["event_id"] == event_id),
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
                    node for node in variant["nodes"]
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
            if region_id is not None and not global_scope and str(region_id) not in allowed_regions:
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
                    (name for name in ("regions", "lanes") if name in measurement["inputs"]),
                    None,
                )
                if region_input is None:
                    raise gr.Error("当前统计量没有可切换的全画面度量")
                object_input = next(
                    (name for name in ("objects", "entities") if name in measurement["inputs"]),
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

            requested_categories = [str(label) for label in card.get("categories", []) if str(label)]
            available_categories = category_labels(measurement)
            if requested_categories:
                if available_categories and not set(requested_categories).issubset(available_categories):
                    raise gr.Error("目标类别必须来自当前检测目标")
                object_input = next(
                    (name for name in ("objects", "entities") if name in measurement["inputs"]),
                    None,
                )
                if object_input is None:
                    raise gr.Error("当前统计量不支持按目标类别筛选")
                upstream_ref = measurement["inputs"][object_input]
                upstream = node_for_ref(upstream_ref)
                if upstream is not None and upstream["op"] == "objects.filter_by_label@1.0" and "__event_card_" in upstream["id"]:
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
                comparison_region_sources.append((
                    region_source_id,
                    None if region_id is None else str(region_id),
                ))

        # logic.all / logic.any are multi-input operators.  A lone comparison is
        # already an executable condition, so connect it directly to the event.
        # The reachability cleanup below removes an obsolete combiner, if any.
        if len(comparison_refs) == 1:
            event["inputs"]["condition"] = comparison_refs[0]
        else:
            current_logic_id = current["logic_node_id"]
            if current_logic_id is None:
                logic_id = next_id(f"{event_id}_conditions")
                logic = {"id": logic_id, "op": "logic.all@1.0", "inputs": {}, "params": {}}
                nodes[logic_id] = logic
                variant["nodes"].append(logic)
            else:
                logic = nodes[current_logic_id]
                logic_id = current_logic_id
            logic["op"] = f"logic.{logic_mode}@1.0"
            logic["inputs"] = {"conditions": comparison_refs}
            logic["params"] = {
                "combine_scope": (
                    "frame_any"
                    if len(set(comparison_region_sources)) > 1
                    else "by_key"
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
            (node for node in variant["nodes"]
             if node["op"] == "output.alert@1.0" and node["inputs"].get("events") == f"${event_id}"),
            None,
        )
        if alert is not None:
            alert["params"] = {**alert["params"], "label": alert_label.strip()}

        # A card replacement can leave legacy branches detached.  Keep the package
        # executable by retaining only nodes that contribute to declared outputs.
        reachable: set[str] = set()
        pending = [reference[1:] for reference in variant["outputs"].values()
                   if isinstance(reference, str) and reference.startswith("$")]
        while pending:
            node_id = pending.pop()
            if node_id in reachable or node_id not in nodes:
                continue
            reachable.add(node_id)
            for value in nodes[node_id].get("inputs", {}).values():
                references = value if isinstance(value, list) else [value]
                pending.extend(
                    reference[1:] for reference in references
                    if isinstance(reference, str) and reference.startswith("$")
                )
        variant["nodes"] = [node for node in variant["nodes"] if node["id"] in reachable]
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
            "temporal.persist@1.0", "event.from_condition@1.0"
        }:
            raise gr.Error("找不到要编辑的事件规则")
        association = nodes.get(association_id)
        if association is None or association["op"] != "spatial.associate@1.0":
            raise gr.Error("找不到要编辑的目标关联")

        current = next(
            (
                item for item in self.read_event_rule_controls(
                    effective_json, media_type
                )
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
            if index < 0 or index >= len(targets) or not isinstance(targets[index], dict):
                raise gr.Error("候选框必须来自当前技能的检测类别")
            if not targets[index].get("label"):
                raise gr.Error("候选框缺少已声明的类别标签")
            return ground_id, index, targets

        def candidate_reference(
            role: str, candidate_key: str
        ) -> str:
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
                    and node.get("inputs", {}).get("objects") == previous_subject_reference
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
                node for node in variant["nodes"]
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

    def context_confirmation_control_values(
        self, effective_json: str, variant_name: str
    ) -> dict[str, Any] | None:
        """Read explicit secondary-confirmation parameters from one variant."""

        if not (effective_json or "").strip():
            return None
        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(variant_name)
        variant = package.variants.get(key)
        if not variant or variant.status == "unsupported":
            return {
                "labels": [], "selected_labels": [], "enabled": False,
                "confirmation_phrases": "", "padding_fraction": 1.0,
                "crop_long_side": 640,
                "status": f"当前技能没有可编辑的 {key} variant。",
            }
        label_phrases: dict[str, list[str]] = {}
        for node in variant.nodes:
            if node.op != "rex.ground@1.1":
                continue
            for target in node.params.get("targets", []):
                label = target.get("label")
                phrases = target.get("phrases", [])
                if label and phrases:
                    label_phrases.setdefault(label, []).extend(phrases)
        candidate = next(
            (node for node in variant.nodes if node.id == "context_confirmation_candidates"),
            None,
        )
        evidence = next(
            (node for node in variant.nodes if node.id == "context_confirmation_evidence_raw"),
            None,
        )
        crops = next(
            (node for node in variant.nodes if node.id == "context_confirmation_crops"),
            None,
        )
        crop_resize = next(
            (node for node in variant.nodes if node.id == "context_confirmation_crop_resized"),
            None,
        )
        candidate_phrases = set(candidate.params.get("phrases", [])) if candidate else set()
        selected_labels = [
            label for label, phrases in label_phrases.items()
            if candidate_phrases.intersection(phrases)
        ]
        confirmation_phrases = []
        if evidence:
            confirmation_phrases = [
                phrase
                for target in evidence.params.get("targets", [])
                for phrase in target.get("phrases", [])
            ]
        return {
            "labels": list(label_phrases),
            "selected_labels": selected_labels,
            "enabled": candidate is not None,
            "confirmation_phrases": "\n".join(confirmation_phrases),
            "padding_fraction": float(crops.params.get("padding_fraction", 1.0)) if crops else 1.0,
            "crop_long_side": int(crop_resize.params.get("long_side", 640)) if crop_resize else 640,
            "status": (
                "已读取当前 variant 的二次可见性确认分支。"
                if candidate else "当前未启用二次可见性确认；启用后仅复核选中的候选类别。"
            ),
        }

    def apply_context_confirmation_control(
        self,
        effective_json: str,
        variant_name: str,
        enabled: bool,
        candidate_labels: list[str] | None,
        confirmation_text: str,
        padding_fraction: float,
        crop_long_side: int,
    ) -> str:
        """Apply the reusable candidate confirmation template to one variant."""

        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(variant_name)
        data = package.model_dump(mode="json")
        variant = data["variants"].get(key)
        if not variant or variant["status"] == "unsupported":
            raise gr.Error(f"当前技能没有可执行的 {key} variant")
        label_phrases: dict[str, list[str]] = {}
        for node in variant["nodes"]:
            if node["op"] != "rex.ground@1.1":
                continue
            for target in node["params"].get("targets", []):
                label = target.get("label")
                phrases = target.get("phrases", [])
                if label and phrases:
                    label_phrases.setdefault(label, []).extend(phrases)
        selected = list(dict.fromkeys(candidate_labels or []))
        unknown = [label for label in selected if label not in label_phrases]
        if unknown:
            raise gr.Error("待复核类别不存在于当前 variant：" + "、".join(unknown))
        candidate_phrases = [
            phrase for label in selected for phrase in label_phrases[label]
        ]
        confirmation_phrases = [
            item.strip() for item in re.split(r"[\n,;]+", confirmation_text or "")
            if item.strip()
        ]
        try:
            nodes, outputs = apply_context_confirmation(
                variant["nodes"], variant["outputs"], enabled=bool(enabled),
                candidate_phrases=candidate_phrases,
                confirmation_phrases=confirmation_phrases,
                padding_fraction=float(padding_fraction),
                crop_long_side=int(crop_long_side),
            )
        except ValueError as exc:
            raise gr.Error(f"二次可见性确认配置无效：{exc}") from exc
        variant["nodes"] = nodes
        variant["outputs"] = outputs
        updated = SkillPackage.model_validate(data)
        errors = validate_skill_package(updated, self.registry)
        if errors:
            raise gr.Error("二次可见性确认配置无效：" + "；".join(errors))
        return self._dump(updated)

    def apply_preprocessing(
        self,
        effective_json: str,
        media_type: str,
        resize_mode: str,
        long_side: int,
        width: int,
        height: int,
        tile_enabled: bool,
        tile_width: int,
        tile_height: int,
        overlap_x: float,
        overlap_y: float,
        include_full_frame: bool,
        dedup_metric: str,
        dedup_threshold: float,
        interpolation: str = "bilinear",
    ) -> str:
        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        data = package.model_dump(mode="json")
        variant = data["variants"].get(key)
        if not variant or variant["status"] == "unsupported":
            raise gr.Error(f"当前技能没有可执行的 {key} variant")
        nodes = variant["nodes"]
        resize = next(
            (node for node in nodes if node["op"].startswith("image.resize@")),
            None,
        )
        if resize is None:
            raise gr.Error("当前 variant 没有显式 image.resize 节点")
        resize["op"] = "image.resize@1.1"
        resize["params"] = {
            "mode": resize_mode,
            "long_side": int(long_side),
            "width": int(width),
            "height": int(height),
            "interpolation": interpolation,
        }
        tile_id = "preprocess_tiles"
        tile = next((node for node in nodes if node["id"] == tile_id), None)
        primary_ground = next(
            (
                node for node in nodes
                if node["op"].startswith("rex.ground@")
                and node["id"] in {"candidates_raw", "candidates"}
            ),
            None,
        )
        if primary_ground is None:
            primary_ground = next(
                (
                    node for node in nodes
                    if node["op"].startswith("rex.ground@")
                    and node.get("inputs", {}).get("frames")
                    == f"${resize['id']}"
                ),
                None,
            )
        ground_nodes = [primary_ground] if primary_ground is not None else []
        if tile_enabled:
            tile_data = {
                "id": tile_id,
                "op": "image.tile@1.1",
                "inputs": {"frames": f"${resize['id']}"},
                "params": {
                    "tile_width": int(tile_width),
                    "tile_height": int(tile_height),
                    "overlap_x": float(overlap_x),
                    "overlap_y": float(overlap_y),
                    "include_full_frame": bool(include_full_frame),
                },
                "enabled": True,
            }
            if tile is None:
                first_ground = min(
                    (nodes.index(node) for node in ground_nodes),
                    default=len(nodes),
                )
                nodes.insert(first_ground, tile_data)
            else:
                nodes[nodes.index(tile)] = tile_data
            for ground in ground_nodes:
                ground["inputs"]["frames"] = f"${tile_id}"
        elif tile is not None:
            nodes.remove(tile)
            for ground in ground_nodes:
                if ground["inputs"].get("frames") == f"${tile_id}":
                    ground["inputs"]["frames"] = f"${resize['id']}"
        for node in nodes:
            if node["op"] == "objects.deduplicate@1.0":
                node["params"] = {
                    "metric": dedup_metric,
                    "threshold": float(dedup_threshold),
                    "keep": "first",
                }
        updated = SkillPackage.model_validate(data)
        errors = validate_skill_package(updated, self.registry)
        if errors:
            raise gr.Error("前处理配置无效：" + "；".join(errors))
        return self._dump(updated)

    def apply_video_sampling(
        self,
        effective_json: str,
        mode: str,
        fps: float,
        interval_seconds: float,
        frame_step: int,
        start_seconds: float,
        end_seconds: float | None,
        max_frames: int | None,
    ) -> str:
        package = SkillPackage.model_validate_json(effective_json)
        data = package.model_dump(mode="json")
        variant = data["variants"].get("video")
        if not variant or variant["status"] == "unsupported":
            raise gr.Error("当前技能没有可执行的 video variant")
        sample = next(
            (node for node in variant["nodes"] if node["op"].startswith("video.sample@")),
            None,
        )
        if sample is None:
            raise gr.Error("video variant 没有显式抽帧节点")
        if mode == "original_fps":
            mode = "frame_step"
            frame_step = 1
        sample["op"] = "video.sample@1.1"
        sample["params"] = {
            "mode": mode,
            "fps": float(fps),
            "interval_seconds": float(interval_seconds),
            "frame_step": int(frame_step),
            "start_seconds": float(start_seconds),
            "end_seconds": normalize_end_seconds(end_seconds),
            "max_frames": (
                None
                if max_frames in (None, "") or float(max_frames) <= 0
                else int(max_frames)
            ),
        }
        updated = SkillPackage.model_validate(data)
        errors = validate_skill_package(updated, self.registry)
        if errors:
            raise gr.Error("抽帧配置无效：" + "；".join(errors))
        return self._dump(updated)

    def apply_output_configuration(
        self,
        effective_json: str,
        media_type: str,
        size_mode: str,
        width: int | None,
        height: int | None,
        fps_mode: str,
        fps: float | None,
    ) -> str:
        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        data = package.model_dump(mode="json")
        variant = data["variants"].get(key)
        if not variant or variant["status"] == "unsupported":
            raise gr.Error(f"当前技能没有可配置的 {key} variant")
        draw = next(
            (
                node
                for node in variant["nodes"]
                if node["op"] == "output.draw@1.0"
            ),
            None,
        )
        if draw is None:
            raise gr.Error("当前 variant 没有 output.draw 节点")
        params = dict(draw.get("params", {}))
        params.update({
            "output_size_mode": size_mode,
            "output_width": None if width in (None, "") else int(width),
            "output_height": None if height in (None, "") else int(height),
            "output_fps_mode": fps_mode,
            "output_fps": None if fps in (None, "") else float(fps),
        })
        draw["params"] = params
        updated = SkillPackage.model_validate(data)
        errors = validate_skill_package(updated, self.registry)
        if errors:
            raise gr.Error("结果媒体配置无效：" + "；".join(errors))
        return self._dump(updated)

    def apply_manual_roi(
        self,
        effective_json: str,
        media_type: str,
        node_id: str,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
    ) -> str:
        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        data = package.model_dump(mode="json")
        variant = data["variants"].get(key)
        if not variant or variant["status"] == "unsupported":
            raise gr.Error(f"当前技能没有可执行的 {key} variant")
        region = next(
            (node for node in variant["nodes"] if node["id"] == node_id.strip()),
            None,
        )
        if region is None or not region["op"].startswith("region."):
            raise gr.Error("请输入现有区域节点 ID；ROI 不是全局必填配置")
        region.update({
            "op": "region.manual@1.0",
            "inputs": {},
            "params": {
                "shape": "rectangle",
                "points": [
                    [min(x0, x1), min(y0, y1)],
                    [max(x0, x1), max(y0, y1)],
                ],
            },
        })
        updated = SkillPackage.model_validate(data)
        errors = validate_skill_package(updated, self.registry)
        if errors:
            raise gr.Error("ROI 配置无效：" + "；".join(errors))
        return self._dump(updated)

    def apply_manual_roi_points(
        self,
        effective_json: str,
        media_type: str,
        node_id: str,
        shape: str,
        points_json: str,
        region_key: str = "",
        region_label: str = "",
    ) -> str:
        """Bind normalized rectangle/polygon points to one explicit region node."""

        try:
            raw_points = json.loads(points_json)
            points = [[float(value) for value in point] for point in raw_points]
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise gr.Error("ROI 点必须是 JSON 坐标数组，例如 [[0.1,0.2],[0.9,0.8]]") from exc
        if shape not in {"rectangle", "polygon"}:
            raise gr.Error("ROI 形状必须是 rectangle 或 polygon")
        required = 2 if shape == "rectangle" else 3
        if len(points) != 2 if shape == "rectangle" else len(points) < required:
            detail = "恰好 2 个角点" if shape == "rectangle" else "至少 3 个顶点"
            raise gr.Error(f"{shape} 需要{detail}")
        if any(
            len(point) != 2 or any(value < 0.0 or value > 1.0 for value in point)
            for point in points
        ):
            raise gr.Error("ROI 坐标必须是 [0,1] 内的二维归一化坐标")

        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        data = package.model_dump(mode="json")
        variant = data["variants"].get(key)
        if not variant or variant["status"] == "unsupported":
            raise gr.Error(f"当前技能没有可配置的 {key} variant")
        region = next(
            (node for node in variant["nodes"] if node["id"] == node_id.strip()),
            None,
        )
        if region is None or not region["op"].startswith("region."):
            raise gr.Error("请输入现有区域节点 ID")

        if region["op"] == "region.manual_set@1.0" or region_key.strip():
            target_key = region_key.strip()
            if not target_key:
                raise gr.Error("命名区域集合需要填写区域 key，例如 lane_left")
            regions = list(region.get("params", {}).get("regions", []))
            replacement = {
                "id": target_key,
                "label": region_label.strip() or target_key,
                "shape": shape,
                "points": points,
            }
            index = next(
                (i for i, item in enumerate(regions) if item.get("id") == target_key),
                None,
            )
            if index is None:
                regions.append(replacement)
            else:
                regions[index] = replacement
            region.update({
                "op": "region.manual_set@1.0",
                "inputs": {},
                "params": {"regions": regions},
            })
        else:
            region.update({
                "op": "region.manual@1.0",
                "inputs": {},
                "params": {"shape": shape, "points": points},
            })

        updated = SkillPackage.model_validate(data)
        errors = validate_skill_package(updated, self.registry)
        if errors:
            raise gr.Error("ROI 配置无效：" + "；".join(errors))
        return self._dump(updated)

    def apply_manual_direction(
        self,
        effective_json: str,
        media_type: str,
        node_id: str,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        direction_key: str = "global",
    ) -> str:
        """Replace an inferred direction node with an explicit arrow vector."""

        vector = [float(x1) - float(x0), float(y1) - float(y0)]
        if abs(vector[0]) + abs(vector[1]) <= 1e-9:
            raise gr.Error("方向箭头的起点和终点不能相同")
        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        data = package.model_dump(mode="json")
        variant = data["variants"].get(key)
        if not variant or variant["status"] == "unsupported":
            raise gr.Error(f"当前技能没有可配置的 {key} variant")
        direction = next(
            (node for node in variant["nodes"] if node["id"] == node_id.strip()),
            None,
        )
        if direction is None:
            raise gr.Error("请输入现有方向节点 ID")

        target_key = direction_key.strip() or "global"
        if target_key == "global":
            direction.update({
                "op": "direction.manual@1.0",
                "inputs": {},
                "params": {"vector": vector},
            })
        else:
            directions = []
            if direction.get("op") == "direction.manual_set@1.0":
                directions = list(direction.get("params", {}).get("directions", []))
            replacement = {"key": target_key, "vector": vector}
            index = next(
                (i for i, item in enumerate(directions) if item.get("key") == target_key),
                None,
            )
            if index is None:
                directions.append(replacement)
            else:
                directions[index] = replacement
            direction.update({
                "op": "direction.manual_set@1.0",
                "inputs": {},
                "params": {"directions": directions},
            })

        updated = SkillPackage.model_validate(data)
        errors = validate_skill_package(updated, self.registry)
        if errors:
            raise gr.Error("方向配置无效：" + "；".join(errors))
        return self._dump(updated)

    def ingest_media(self, media_path: str, timestamp: float = 0.0):
        if not media_path:
            raise gr.Error("请先上传图片或视频")
        try:
            asset = self.asset_store.ingest(media_path)
            frame = extract_annotation_frame(asset.stored_path, timestamp)
        except (ValueError, FileNotFoundError) as exc:
            raise gr.Error(str(exc)) from exc
        metadata = asdict(asset)
        state = {
            "asset_path": asset.stored_path,
            "asset_id": asset.asset_id,
            "media_type": asset.media_type,
            "timestamp": frame.timestamp,
            "frame_index": frame.frame_index,
            "points": [],
            "tool": "rectangle",
        }
        status = (
            f"✅ 原始媒体已保存 · {asset.width}×{asset.height}"
            + (f" · {asset.fps:g} FPS · {asset.frame_count} 帧" if asset.fps else "")
            + f" · SHA-256 {asset.asset_id[:12]}…"
        )
        return asset.stored_path, metadata, frame.image, state, status

    def refresh_annotation_preview(
        self,
        effective_json: str,
        media_type: str,
        asset_path: str,
        timestamp: float,
        state: dict | None = None,
    ):
        if not asset_path:
            raise gr.Error("请先上传媒体")
        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        frame = extract_annotation_frame(asset_path, timestamp)
        if frame.media_type != key:
            raise gr.Error(f"标注媒体是 {frame.media_type}，当前 variant 是 {key}")
        current = dict(state or {})
        current.update({
            "asset_path": str(Path(asset_path).resolve()),
            "media_type": frame.media_type,
            "timestamp": frame.timestamp,
            "frame_index": frame.frame_index,
        })
        current.setdefault("points", [])
        current.setdefault("tool", "rectangle")
        annotations = annotations_from_package(package, key)
        preview = render_annotation_workspace(
            frame.image,
            annotations,
            draft_tool=current["tool"],
            draft_points=current["points"],
        )
        return preview, current, configuration_status(package)

    def annotation_slots(self, effective_json: str, media_type: str):
        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        rows = [
            item
            for item in configuration_status(package)
            if item["media_type"] == key
        ]
        choices = [
            (
                f"{item['label']} · {item['kind']} · "
                + (
                    "当前已配置"
                    if item["active"] and item["configured"]
                    else "当前待配置"
                    if item["active"]
                    else "备用模式（绑定后激活）"
                ),
                item["slot_id"],
            )
            for item in rows
        ]
        return choices, rows

    def annotation_slot_options(
        self, effective_json: str, media_type: str
    ) -> tuple[list[tuple[str, str]], str]:
        """Provide a valid disabled dropdown value when no scene input is needed."""

        choices, _ = self.annotation_slots(effective_json, media_type)
        if not choices:
            return [("无需场景标注", NO_ANNOTATION_SLOT)], NO_ANNOTATION_SLOT
        wizard = self.annotation_wizard_state(effective_json, media_type)
        return choices, wizard["current_slot"] or choices[0][1]

    def annotation_slots_with_selection(
        self,
        effective_json: str,
        media_type: str,
        selected_slot_id: str | None,
    ) -> list[dict[str, Any]]:
        """Return slot status rows with the active UI selection made explicit."""

        _, rows = self.annotation_slots(effective_json, media_type)
        return [
            {**row, "selected": row["slot_id"] == selected_slot_id}
            for row in rows
        ]

    def annotation_wizard_state(
        self, effective_json: str, media_type: str
    ) -> dict[str, Any]:
        """Build a generic, dependency-aware checklist for annotation slots."""

        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        variant = package.variants[key]
        nodes = {node.id: node for node in variant.nodes}
        status_by_id = {
            item["slot_id"]: item
            for item in configuration_status(package)
            if item["media_type"] == key
        }
        slot_by_id = {slot.slot_id: slot for slot in variant.configuration_slots}

        ordered = []
        remaining = list(variant.configuration_slots)
        emitted: set[str] = set()
        while remaining:
            ready = [
                slot for slot in remaining
                if slot.key_source_slot_id is None
                or slot.key_source_slot_id in emitted
                or slot.key_source_slot_id not in slot_by_id
            ]
            if not ready:
                ready = [remaining[0]]
            for slot in ready:
                ordered.append(slot)
                emitted.add(slot.slot_id)
                remaining.remove(slot)

        rows = []
        for slot in ordered:
            node = nodes.get(slot.binding.node_id)
            params = node.params if node is not None else {}
            configured_items: list[str] = []
            pending_items: list[str] = []
            if slot.kind == "region":
                if status_by_id[slot.slot_id]["configured"]:
                    configured_items = [slot.slot_id]
                else:
                    pending_items = [slot.slot_id]
            elif slot.kind == "region_set":
                configured_items = [
                    item["id"] for item in params.get("regions", [])
                    if isinstance(item, dict) and item.get("id")
                ]
                pending_items = ["new_item"]
            elif slot.kind == "direction":
                if status_by_id[slot.slot_id]["configured"]:
                    configured_items = [slot.slot_id]
                else:
                    pending_items = [slot.slot_id]
            else:
                configured_items = [
                    item["key"] for item in params.get("directions", [])
                    if isinstance(item, dict) and item.get("key")
                ]
                if slot.key_source_slot_id:
                    source = slot_by_id.get(slot.key_source_slot_id)
                    source_node = nodes.get(source.binding.node_id) if source else None
                    expected = [
                        item["id"]
                        for item in (
                            source_node.params.get("regions", [])
                            if source_node is not None else []
                        )
                        if isinstance(item, dict) and item.get("id")
                    ]
                    pending_items = ['await_source'] if not expected else [
                        item for item in expected if item not in configured_items
                    ]
                elif not configured_items:
                    pending_items = ["new_item"]
            rows.append({
                **status_by_id[slot.slot_id],
                "depends_on": slot.key_source_slot_id,
                "configured_items": configured_items,
                "pending_items": pending_items,
                "help_text": slot.help_text,
            })

        current = next(
            (
                row
                for row in rows
                if row["active"]
                and [
                    item
                    for item in row["pending_items"]
                    if item not in {"new_item", "await_source"}
                ]
            ),
            next(
                (
                    row
                    for row in rows
                    if row["active"]
                    and row["kind"] == "region_set"
                    and "new_item" in row["pending_items"]
                ),
                next(
                    (row for row in rows if row["active"] and row["pending_items"]),
                    None,
                ),
            ),
        )
        return {
            "slots": rows,
            "current_slot": current["slot_id"] if current else None,
            "current_item": current["pending_items"][0] if current else None,
            "complete": not any(
                row["active"] and row["required"] and not row["configured"]
                for row in rows
            ),
        }

    def annotation_wizard_markdown(
        self, effective_json: str, media_type: str
    ) -> str:
        wizard = self.annotation_wizard_state(effective_json, media_type)
        if not wizard["slots"]:
            automatic_regions = self._automatic_region_labels(effective_json, media_type)
            if automatic_regions:
                return (
                    "**无需手工绘制区域。** 当前流程会自动生成区域："
                    + "、".join(automatic_regions)
                    + "（不可手工编辑）。"
                )
            return "**无需场景标注。** 该技能可以直接运行。"
        lines = ["### 配置向导"]
        for index, slot in enumerate(wizard["slots"], start=1):
            configured = "、".join(slot["configured_items"]) or "无"
            pending = "、".join(
                "等待上游区域" if item == "await_source" else ("可添加新区域" if item == "new_item" else item)
                for item in slot["pending_items"]
            ) or "无"
            state = "已完成" if slot["configured"] else "待完成"
            dependency = (
                f"；依赖 `{slot['depends_on']}` 的命名项"
                if slot["depends_on"] else ""
            )
            lines.append(
                f"{index}. **{slot['label']}** (`{slot['slot_id']}` / "
                f"`{slot['kind']}`)：{state}{dependency}  "
            )
            lines.append(f"   已配置：{configured}；待配置：{pending}")
        if wizard["complete"]:
            lines.append("\n✅ 所有必需标注均已完成，可以运行。")
        else:
            current_item = wizard["current_item"]
            if current_item == "new_item":
                hint = "，添加一个命名项"
            elif current_item:
                hint = f" 的 `{current_item}`"
            else:
                hint = ""
            lines.append(
                f"\n➡️ 下一步：配置 `{wizard['current_slot']}`{hint}。"
            )
        return "\n".join(lines)

    def annotation_wizard_defaults(
        self, effective_json: str, media_type: str, slot_id: str | None
    ) -> tuple[str, str, str]:
        """Return tool and item defaults for the selected generic slot."""

        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        wizard = self.annotation_wizard_state(effective_json, media_type)
        slot_id = slot_id or wizard["current_slot"]
        slot = next(
            (item for item in package.variants[key].configuration_slots
             if item.slot_id == slot_id),
            None,
        )
        if slot is None:
            return "rectangle", "", ""
        row = next(item for item in wizard["slots"] if item["slot_id"] == slot.slot_id)
        pending = [
            item
            for item in row["pending_items"]
            if item not in {"new_item", "await_source"}
        ]
        item_id = pending[0] if pending else ""
        if slot.kind == "region_set" and not item_id:
            item_id = f"{slot.slot_id}_{len(row['configured_items']) + 1}"
        tool = "direction" if slot.kind in {"direction", "direction_set"} else (
            "polygon" if "polygon" in slot.allowed_shapes else "rectangle"
        )
        return tool, item_id, item_id

    def annotation_tool_choices(
        self, effective_json: str, media_type: str, slot_id: str | None
    ) -> list[str]:
        """Return drawing tools valid for the selected slot and its direction link."""

        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        slot = next(
            (
                item
                for item in package.variants[key].configuration_slots
                if item.slot_id == slot_id
            ),
            None,
        )
        if slot is None:
            return ["rectangle", "polygon"]
        if slot.kind in {"direction", "direction_set"}:
            return ["direction"]
        choices = list(slot.allowed_shapes or ["rectangle", "polygon"])
        has_linked_direction = any(
            item.kind in {"direction", "direction_set"}
            and item.key_source_slot_id == slot.slot_id
            for item in package.variants[key].configuration_slots
        )
        if has_linked_direction and "direction" not in choices:
            choices.append("direction")
        return choices

    def annotation_tool_selection_defaults(
        self,
        effective_json: str,
        media_type: str,
        slot_id: str | None,
        tool: str,
    ) -> tuple[str, str, str, str, dict]:
        """Resolve a tool click to its compatible slot and a fresh draft.

        A direction arrow selected from a named-region slot belongs to that
        slot's linked direction slot.  Resolving this before drawing keeps the
        slot, bound region ID, and canvas state in sync.
        """

        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        slots = package.variants[key].configuration_slots
        wizard = self.annotation_wizard_state(effective_json, media_type)
        current_slot_id = slot_id or wizard["current_slot"]
        current_slot = next(
            (item for item in slots if item.slot_id == current_slot_id), None
        )
        if current_slot is None and slots:
            current_slot = slots[0]

        target_slot = current_slot
        if current_slot is not None and tool == "direction":
            if current_slot.kind in {"region", "region_set"}:
                target_slot = next(
                    (
                        item
                        for item in slots
                        if item.kind in {"direction", "direction_set"}
                        and item.key_source_slot_id == current_slot.slot_id
                    ),
                    current_slot,
                )
        elif current_slot is not None and tool in {"rectangle", "polygon"}:
            if current_slot.kind in {"direction", "direction_set"}:
                target_slot = next(
                    (
                        item
                        for item in slots
                        if item.slot_id == current_slot.key_source_slot_id
                        and item.kind in {"region", "region_set"}
                    ),
                    current_slot,
                )

        if target_slot is None:
            return "", tool, "", "", {"tool": tool, "points": []}

        default_tool, item_id, item_label = self.annotation_wizard_defaults(
            effective_json, media_type, target_slot.slot_id
        )
        if target_slot.kind in {"direction", "direction_set"}:
            selected_tool = "direction"
        else:
            allowed_shapes = target_slot.allowed_shapes or ["rectangle", "polygon"]
            selected_tool = tool if tool in allowed_shapes else default_tool
        return (
            target_slot.slot_id,
            selected_tool,
            item_id,
            item_label,
            {"tool": selected_tool, "points": []},
        )

    def annotation_selection_defaults(
        self,
        effective_json: str,
        media_type: str,
        slot_id: str | None,
        state: dict | None = None,
    ) -> tuple[str, str, str, dict]:
        """Start a fresh draft whenever the annotation target changes."""

        if not effective_json:
            return "rectangle", "", "", {"tool": "rectangle", "points": []}
        tool, item_id, item_label = self.annotation_wizard_defaults(
            effective_json, media_type, slot_id
        )
        return tool, item_id, item_label, {"tool": tool, "points": []}

    def annotation_overview(self, effective_json: str, media_type: str) -> str:
        """Describe whether the current workflow needs manual scene input."""

        if not effective_json:
            return "请先创建或加载技能，再判断是否需要场景标注。"
        choices, _ = self.annotation_slots(effective_json, media_type)
        automatic_regions = self._automatic_region_labels(effective_json, media_type)
        if not choices:
            if automatic_regions:
                return (
                    "此技能使用自动生成区域："
                    + "、".join(automatic_regions)
                    + "；自动生成区域（不可手工编辑），运行时会随检测结果更新。"
                )
            return "此技能无需标注场景，可直接去“04 运行与结果”。"
        labels = "、".join(choice.split(" · ", 1)[0] for choice, _ in choices)
        suffix = (
            "；同时保留自动生成区域能力：" + "、".join(automatic_regions)
            + "（兼容旧配置，不可手工编辑且默认不参与判定）"
            if automatic_regions else ""
        )
        return f"此技能需要场景标注：{labels}。使用当前任务媒体完成一次绘制后即可运行{suffix}。"

    def _automatic_region_labels(self, effective_json: str, media_type: str) -> list[str]:
        """Return read-only region producers so automatic ROIs are visible in 02 标注."""

        if not effective_json:
            return []
        package = SkillPackage.model_validate_json(effective_json)
        variant = package.variants.get(_variant_key(media_type))
        if variant is None or variant.status == "unsupported":
            return []
        return [
            node.id
            for node in variant.nodes
            if node.op == "region.from_objects@1.0"
        ]

    def _render_annotation_state(
        self,
        effective_json: str,
        media_type: str,
        asset_path: str,
        timestamp: float,
        state: dict,
    ):
        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        frame = extract_annotation_frame(asset_path, timestamp)
        annotations = annotations_from_package(package, key)
        preview = render_annotation_workspace(
            frame.image,
            annotations,
            draft_tool=state.get("tool"),
            draft_points=state.get("points", []),
        )
        points_json = json.dumps(
            state.get("points", []), ensure_ascii=False
        )
        status = (
            f"当前 {state.get('tool')} 已选 {len(state.get('points', []))} 个点；"
            "坐标为原媒体归一化坐标。"
        )
        return preview, state, points_json, status

    def add_annotation_point(
        self,
        effective_json: str,
        media_type: str,
        asset_path: str,
        timestamp: float,
        tool: str,
        state: dict | None,
        x: float,
        y: float,
    ):
        if not asset_path:
            raise gr.Error("请先上传媒体")
        frame = extract_annotation_frame(asset_path, timestamp)
        current = dict(state or {})
        if current.get("tool") != tool:
            current["points"] = []
        current["tool"] = tool
        points = list(current.get("points", []))
        limit = 2 if tool in {"rectangle", "direction"} else None
        if limit is not None and len(points) >= limit:
            points = []
        points.append(
            normalize_canvas_point(x, y, frame.image.width, frame.image.height)
        )
        current["points"] = points
        return self._render_annotation_state(
            effective_json, media_type, asset_path, timestamp, current
        )

    def set_annotation_drag(
        self,
        effective_json: str,
        media_type: str,
        asset_path: str,
        timestamp: float,
        tool: str,
        state: dict | None,
        drag_json: str,
    ):
        """Convert a browser drag on the original-media canvas into two points."""

        if tool not in {"rectangle", "direction"}:
            raise gr.Error("只有矩形和方向箭头使用拖拽绘制")
        if not asset_path:
            raise gr.Error("请先选择当前任务媒体")
        try:
            drag = json.loads(drag_json)
            start_x, start_y = drag["start"]
            end_x, end_y = drag["end"]
            canvas_size = drag.get("canvas_size")
        except (TypeError, KeyError, ValueError, json.JSONDecodeError) as exc:
            raise gr.Error("拖拽数据无效") from exc
        frame = extract_annotation_frame(asset_path, timestamp)
        try:
            canvas_width, canvas_height = (
                canvas_size if canvas_size is not None else frame.image.size
            )
            canvas_width = float(canvas_width)
            canvas_height = float(canvas_height)
            if canvas_width <= 0 or canvas_height <= 0:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise gr.Error("拖拽画布尺寸无效") from exc
        current = dict(state or {})
        current["tool"] = tool
        current["points"] = [
            normalize_canvas_point(start_x, start_y, canvas_width, canvas_height),
            normalize_canvas_point(end_x, end_y, canvas_width, canvas_height),
        ]
        return self._render_annotation_state(
            effective_json, media_type, asset_path, timestamp, current
        )

    def undo_annotation_point(
        self,
        effective_json: str,
        media_type: str,
        asset_path: str,
        timestamp: float,
        state: dict | None,
    ):
        current = dict(state or {})
        tool = current.get("tool")
        points = list(current.get("points", []))
        if tool in {"rectangle", "direction"}:
            # A drag shape is atomic: undo clears the whole draft.
            current["points"] = []
        else:
            current["points"] = points[:-1]
        return self._render_annotation_state(
            effective_json, media_type, asset_path, timestamp, current
        )

    def clear_annotation_points(
        self,
        effective_json: str,
        media_type: str,
        asset_path: str,
        timestamp: float,
        state: dict | None,
    ):
        current = dict(state or {})
        current["points"] = []
        return self._render_annotation_state(
            effective_json, media_type, asset_path, timestamp, current
        )

    def reverse_annotation_direction(
        self,
        effective_json: str,
        media_type: str,
        asset_path: str,
        timestamp: float,
        state: dict | None,
    ):
        """Flip the two draft direction points so an arrow drawn backwards is
        corrected with one click. The arrow is the normal driving direction;
        a track moving opposite to it is judged as wrong-way."""

        current = dict(state or {})
        points = list(current.get("points", []))
        if current.get("tool") != "direction" or len(points) != 2:
            raise gr.Error("请先用“方向箭头”工具画好两个端点，再反转方向")
        current["points"] = [points[1], points[0]]
        return self._render_annotation_state(
            effective_json, media_type, asset_path, timestamp, current
        )

    def bind_annotation(
        self,
        effective_json: str,
        media_type: str,
        slot_id: str | None,
        tool: str,
        points_json: str,
        item_id: str = "",
        item_label: str = "",
    ):
        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        try:
            points = json.loads(points_json)
            if not isinstance(points, list):
                raise ValueError
            points = [[float(value) for value in point] for point in points]
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise gr.Error("标注点必须是归一化二维坐标 JSON") from exc
        slots = package.variants[key].configuration_slots
        if not slot_id and len(slots) == 1:
            slot_id = slots[0].slot_id
        slot = next((item for item in slots if item.slot_id == slot_id), None)
        if slot is None:
            if not slots:
                raise gr.Error("当前技能不需要场景标注，可直接运行")
            raise gr.Error("请先在“要绘制的区域/方向”中选择一个配置槽")
        # Gradio can deliver the radio value before its paired dropdown update.
        # The tool has an unambiguous slot family, so recover from that race.
        rerouted_for_tool = False
        if tool == "direction" and slot.kind in {"region", "region_set"}:
            direction_slot = next(
                (
                    item
                    for item in slots
                    if item.kind in {"direction", "direction_set"}
                    and item.key_source_slot_id == slot.slot_id
                ),
                None,
            )
            if direction_slot is not None:
                slot = direction_slot
                slot_id = slot.slot_id
                rerouted_for_tool = True
        elif tool in {"rectangle", "polygon"} and slot.kind in {
            "direction", "direction_set"
        }:
            region_slot = next(
                (
                    item
                    for item in slots
                    if item.slot_id == slot.key_source_slot_id
                    and item.kind in {"region", "region_set"}
                ),
                None,
            )
            if region_slot is not None:
                slot = region_slot
                slot_id = slot.slot_id
                rerouted_for_tool = True
                item_id = ""
                item_label = ""
        # Derive the named target when the UI-provided item_id is missing or
        # stale, so saving an arrow (or the next region) never fails because a
        # textbox/dropdown state lagged behind the package.
        if slot.kind == "region_set":
            node = next(
                (item for item in package.variants[key].nodes if item.id == slot.binding.node_id),
                None,
            )
            existing = [
                it.get("id") for it in (node.params.get("regions", []) if node else [])
                if isinstance(it, dict) and it.get("id")
            ]
            if rerouted_for_tool or not item_id or not str(item_id).strip():
                item_id = f"{slot.slot_id}_{len(existing) + 1}"
                item_label = item_label or item_id
        elif slot.kind == "direction_set":
            node = next(
                (item for item in package.variants[key].nodes if item.id == slot.binding.node_id),
                None,
            )
            existing = [
                it.get("key") for it in (node.params.get("directions", []) if node else [])
                if isinstance(it, dict) and it.get("key")
            ]
            source_slot = next(
                (item for item in slots if item.slot_id == slot.key_source_slot_id),
                None,
            )
            expected = []
            if source_slot is not None:
                source_node = next(
                    (
                        item
                        for item in package.variants[key].nodes
                        if item.id == source_slot.binding.node_id
                    ),
                    None,
                )
                expected = [
                    it.get("id")
                    for it in (source_node.params.get("regions", []) if source_node else [])
                    if isinstance(it, dict) and it.get("id")
                ]
            missing = [rid for rid in expected if rid not in existing]
            requested = str(item_id).strip() if item_id else ""
            if requested in missing:
                item_id = requested
            elif missing:
                item_id = missing[0]
                item_label = item_label or item_id
            elif requested in expected:
                item_id = requested
            elif not requested:
                raise ValueError("请先选择要绑定方向的命名区域")
            else:
                raise ValueError(
                    f"方向箭头必须绑定已保存区域 ID，当前 `{requested}` 无效"
                )
        try:
            if slot.kind == "region":
                if tool not in {"rectangle", "polygon"}:
                    raise ValueError("区域槽必须使用矩形或多边形工具")
                updated = self.configuration_binder.bind_region(
                    package,
                    media_type=key,
                    slot_id=slot_id,
                    shape=tool,
                    points=points,
                )
            elif slot.kind == "region_set":
                if tool not in {"rectangle", "polygon"}:
                    raise ValueError("命名区域槽必须使用矩形或多边形工具")
                updated = self.configuration_binder.bind_named_region(
                    package,
                    media_type=key,
                    slot_id=slot_id,
                    region_id=item_id,
                    label=item_label,
                    shape=tool,
                    points=points,
                )
            elif slot.kind == "direction":
                if tool != "direction" or len(points) != 2:
                    raise ValueError("方向槽必须使用方向工具并提供两个点")
                updated = self.configuration_binder.bind_direction(
                    package,
                    media_type=key,
                    slot_id=slot_id,
                    start=points[0],
                    end=points[1],
                )
            else:
                if tool != "direction" or len(points) != 2:
                    raise ValueError("命名方向槽必须使用方向工具并提供两个点")
                updated = self.configuration_binder.bind_named_direction(
                    package,
                    media_type=key,
                    slot_id=slot_id,
                    key=item_id,
                    start=points[0],
                    end=points[1],
                )
        except ValueError as exc:
            raise gr.Error(str(exc)) from exc
        return (
            self._dump(updated),
            configuration_status(updated),
            f"✅ 已绑定配置槽 {slot_id}；坐标保存在原媒体归一化坐标系。",
        )

    def named_item_choices(self, effective_json: str, media_type: str, slot_id: str):
        """List the saved named items of a slot so the user can pick one to delete."""

        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        variant = package.variants.get(key)
        if variant is None or variant.status == "unsupported":
            return []
        slot = next(
            (item for item in variant.configuration_slots if item.slot_id == slot_id),
            None,
        )
        if slot is None:
            return []
        node = next(
            (item for item in variant.nodes if item.id == slot.binding.node_id),
            None,
        )
        if node is None:
            return []
        if slot.kind == "region_set":
            return [item.get("id") for item in node.params.get("regions", []) if item.get("id")]
        if slot.kind == "direction_set":
            return [item.get("key") for item in node.params.get("directions", []) if item.get("key")]
        return []

    def delete_named_annotation(
        self,
        effective_json: str,
        media_type: str,
        slot_id: str,
        item_id: str,
    ):
        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        if not item_id or not str(item_id).strip():
            raise gr.Error("请先在“删除已保存标注”下拉框中选择要删除的车道或箭头")
        variant = package.variants.get(key)
        slot = next(
            (
                item
                for item in (variant.configuration_slots if variant else [])
                if item.slot_id == slot_id
            ),
            None,
        )
        if slot is None:
            raise gr.Error(f"找不到配置槽 {slot_id}")
        try:
            if slot.kind == "direction_set":
                updated = self.configuration_binder.delete_named_direction(
                    package,
                    media_type=key,
                    slot_id=slot_id,
                    key=str(item_id).strip(),
                )
            else:
                updated = self.configuration_binder.delete_named_region(
                    package,
                    media_type=key,
                    slot_id=slot_id,
                    region_id=str(item_id).strip(),
                )
        except ValueError as exc:
            raise gr.Error(str(exc)) from exc
        return (
            self._dump(updated),
            configuration_status(updated),
            f"✅ 已删除 {item_id}；若删除的是车道，其同名方向也已同步清理。",
        )

    def inspect_media(
        self, effective_json: str, media_type: str, media_path: str
    ):
        if not media_path:
            raise gr.Error("请先上传媒体")
        package = SkillPackage.model_validate_json(effective_json)
        key = detect_media_type(media_path)
        package.select_variant(key)
        policy = inspect_execution_policy(
            package, key, media_path, self.registry
        )
        data = asdict(policy)
        warning = "；".join(policy.warnings) or "无时长警告"
        text = (
            f"抽样 {policy.sampled_frame_count} 帧；预计 Rex 调用 "
            f"{policy.rex_call_count} 次；粗略耗时 {policy.estimated_processing_seconds:.1f}s。"
            f"{warning}"
        )
        return text, data

    @staticmethod
    def runtime_media_summary(media_path: str, media_type: str) -> str:
        """Make the one shared task-media state explicit at execution time."""

        if not media_path:
            return (
                "**本次运行媒体：尚未选择。** 请返回“01 创建技能”的“当前任务媒体”"
                "上传或加载素材。"
            )
        name = Path(media_path).name
        return (
            f"**本次将运行：** `{name}`（{_variant_key(media_type)}）。"
            "来自“01 创建技能”的当前任务媒体；标注和运行共用这同一份文件。"
        )

    def result_contract(self, effective_json: str, media_type: str) -> dict[str, dict[str, Any]]:
        """Derive result applicability from the selected executable DAG."""

        package = SkillPackage.model_validate_json(effective_json)
        variant = package.select_variant(_variant_key(media_type))
        nodes = {node.id: node for node in variant.nodes}

        def resolved_output_type(node_id: str, seen: set[str] | None = None) -> str:
            """Resolve registry union types through the node's typed entity input."""

            seen = set(seen or ())
            if node_id in seen or node_id not in nodes:
                return ""
            seen.add(node_id)
            node = nodes[node_id]
            definition = self.registry.require(node.op)
            if definition.output_type not in {"EntitySet", "CountableSet"}:
                return definition.output_type
            for input_name, expected_type in definition.input_types.items():
                if expected_type not in {"EntitySet", "CountableSet"}:
                    continue
                ref = node.inputs.get(input_name)
                if isinstance(ref, str) and ref.startswith("$"):
                    concrete = resolved_output_type(ref[1:], seen)
                    if concrete:
                        return concrete
            return definition.output_type

        output_types = {
            resolved_output_type(node.id)
            for ref in variant.outputs.values()
            if isinstance(ref, str)
            and ref.startswith("$")
            and (node := nodes.get(ref[1:])) is not None
        }
        instruction = package.original_instruction.lower()
        semantic_event_expected = (
            package.semantic_ir.mode == "workflow"
            or any(constraint.temporal for constraint in package.semantic_ir.constraints)
            or any(
                marker in instruction
                for marker in ("事件", "告警", "报警", "事故", "摔倒", "逆行", "闯入")
            )
        )

        def item(applicable: bool, yes: str, no: str) -> dict[str, Any]:
            return {"applicable": applicable, "reason": yes if applicable else no}

        contract = {
            "detections": item(
                bool({"ObjectSet", "TrackSet"} & output_types),
                "工作流声明了目标框或带逐帧框的轨迹输出",
                "没有目标框或带框轨迹输出",
            ),
            "tracks": item(
                "TrackSet" in output_types,
                "工作流包含跟踪节点并声明轨迹输出",
                "此工作流没有 TrackSet 输出",
            ),
            "events": item(
                "EventSet" in output_types or semantic_event_expected,
                (
                    "工作流声明了事件输出"
                    if "EventSet" in output_types
                    else "用户语义要求事件结果，但当前工作流未声明 EventSet；本次会显示为空并提示检查编译"
                ),
                "此工作流没有事件/持续条件输出",
            ),
            "measurements": item(
                "ScalarSet" in output_types,
                "工作流声明了计数或数值测量输出",
                "此工作流没有数值测量输出",
            ),
            "regions": item(
                "RegionSet" in output_types,
                "工作流声明了 ROI/命名区域输出",
                "此工作流没有区域输出",
            ),
            "directions": item(
                "VectorSet" in output_types,
                "工作流声明了方向参考输出",
                "此工作流没有方向输出",
            ),
            "constraints": item(True, "语义原子账本始终可解释", ""),
            "trace": item(True, "运行后始终保存节点级 Trace", ""),
        }
        contract["events"]["declared"] = "EventSet" in output_types
        return contract

    @staticmethod
    def format_result_sections(
        contract: dict[str, dict[str, Any]], raw: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        """Make empty-but-applicable distinct from structurally absent results."""

        sections = {}
        for key, info in contract.items():
            items = raw.get(key, [])
            if key == "detections" and not items:
                items = [
                    sample
                    for track in raw.get("tracks", [])
                    for sample in track.get("history", [])
                    if isinstance(track, dict) and isinstance(sample, dict)
                ]
            if not info["applicable"]:
                status = f"不适用 · {info['reason']}"
            else:
                count = len(items) if isinstance(items, list) else 0
                status = f"适用 · 本次 {count} 条"
            sections[key] = {
                "applicable": bool(info["applicable"]),
                "status": status,
                "reason": info["reason"],
                "items": items if info["applicable"] else [],
            }
            if key == "events":
                diagnostics = (
                    raw.get("event_diagnostics", []) if info["applicable"] else []
                )
                if info["applicable"] and not info.get("declared", True):
                    diagnostics = [{
                        "code": "semantic_event_output_missing",
                        "reason": info["reason"],
                    }, *diagnostics]
                sections[key]["diagnostics"] = diagnostics
        return sections

    def run_skill(
        self,
        generated_json: str,
        effective_json: str,
        media_type: str,
        media_path: str,
    ):
        if self.rex is None:
            raise gr.Error("Rex 服务尚未配置")
        if not media_path:
            raise gr.Error("请先上传媒体")
        generated = SkillPackage.model_validate_json(generated_json)
        effective = SkillPackage.model_validate_json(effective_json)
        key = detect_media_type(media_path)
        errors = validate_skill_package(effective, self.registry)
        if errors:
            raise gr.Error("运行前校验失败：" + "；".join(errors))
        effective.select_variant(key)
        record = SkillPackageRuntime(
            self.registry, rex=self.rex, run_store=self.run_store
        ).run(generated, effective, media_path)
        result = json.loads((record.run_dir / "result.json").read_text("utf-8"))
        trace = json.loads((record.run_dir / "trace.json").read_text("utf-8"))
        sections = self.format_result_sections(
            self.result_contract(effective_json, key),
            {
                "detections": result["detections"],
                "tracks": result["tracks"],
                "events": result["events"],
                "event_diagnostics": result.get("event_diagnostics", []),
                "measurements": result["measurements"],
                "regions": result["regions"],
                "directions": result["directions"],
                "constraints": result["constraint_summary"],
                "trace": trace,
            },
        )
        (record.run_dir / "result_contract.json").write_text(
            json.dumps(sections, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        annotated_image = annotated_video = None
        if record.annotated_media:
            if record.annotated_media.suffix.lower() == ".mp4":
                annotated_video = str(record.annotated_media)
            else:
                annotated_image = str(record.annotated_media)
        status = (
            f"✅ 运行完成｜任务目标：{result['task_target']}｜variant：{key}｜"
            f"detections {len(result['detections'])}｜tracks {len(result['tracks'])}｜"
            f"events {len(result['events'])}。此状态表示 runtime_executed，"
            "不等于案例语义验收通过。"
        )
        return (
            annotated_image,
            annotated_video,
            sections["detections"],
            sections["tracks"],
            sections["events"],
            sections["measurements"],
            sections["regions"],
            sections["directions"],
            sections["constraints"],
            sections["trace"],
            str(record.run_dir),
            status,
        )


def build_v2_app(controller: V2AppController) -> gr.Blocks:
    css = """
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=Space+Grotesk:wght@400;500;600;700&display=swap');
    :root {
      --color-primary: #7C3AED;
      --color-on-primary: #FFFFFF;
      --color-secondary: #6366F1;
      --color-accent: #EC4899;
      --color-background: #FAF5FF;
      --color-foreground: #0F172A;
      --color-muted-bg: #F7F3FD;
      --color-border: #EFE7FC;
      --color-destructive: #DC2626;
      --color-ring: #7C3AED;
      --vs-ink: #0F172A;
      --vs-muted: #5F5470;
      --vs-border: #EFE7FC;
      --vs-surface: #ffffff;
      --vs-canvas: #FAF5FF;
      --vs-primary: #7C3AED;
      --vs-primary-strong: #5B21B6;
      --vs-secondary: #6366F1;
      --vs-accent: #EC4899;
      --vs-destructive: #DC2626;
      --vs-shadow: 0 1px 2px rgba(15, 23, 42, .05);
      --vs-shadow-md: 0 4px 6px rgba(76, 29, 149, .08);
      --vs-shadow-raised: 0 10px 15px rgba(76, 29, 149, .10);
      --vs-shadow-xl: 0 20px 25px rgba(76, 29, 149, .15);
      --vs-font-heading: "Space Grotesk", "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
      --vs-font-body: "DM Sans", "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
    }
    body, .gradio-container {
      background: var(--vs-canvas) !important;
      color: var(--vs-ink) !important;
      font-family: var(--vs-font-body) !important;
    }
    .gradio-container {
      max-width: 1540px !important;
      padding: 22px clamp(16px, 3.2vw, 48px) 56px !important;
    }
    .vs-hero {
      position: relative; overflow: hidden; padding: 30px 32px;
      border-radius: 16px; color: #fdfaff;
      background: linear-gradient(112deg, #3B0764 0%, #6D28D9 46%, #C026D3 78%, #EC4899 100%);
      box-shadow: var(--vs-shadow-xl);
    }
    .vs-hero:before {content:""; position:absolute; width:220px; height:220px; left:-90px; bottom:-150px; background:rgba(255,255,255,.07); border-radius:36px; transform:rotate(24deg);}
    .vs-hero:after {content:""; position:absolute; width:410px; height:410px; right:-150px; top:-280px; border:1px solid rgba(249, 168, 212, .28); border-radius:50%; box-shadow:0 0 0 44px rgba(249,168,212,.07),0 0 0 88px rgba(249,168,212,.04);}
    .vs-kicker {margin:0 0 6px; font-family:var(--vs-font-heading); font-size:11px; font-weight:700; letter-spacing:.14em; color:#F0ABFC !important;}
    .vs-hero h1 {position:relative; z-index:1; margin:0; color:#fff !important; font-family:var(--vs-font-heading); font-weight:700; font-size:clamp(28px,3.2vw,40px); line-height:1.2; letter-spacing:-.01em;}
    .vs-hero p {position:relative; z-index:1; max-width:780px; margin:10px 0 0; color:#EDE9FE !important; font-size:15px; line-height:1.6;}
    .vs-hero .vs-badges {position:relative; z-index:1; display:flex; flex-wrap:wrap; gap:8px; margin-top:16px;}
    .vs-badge {display:inline-flex; align-items:center; border:1px solid rgba(255,255,255,.28); border-radius:999px; padding:4px 12px; background:rgba(255,255,255,.12); color:#fdfaff !important; font-size:12px; font-weight:600; backdrop-filter:blur(4px);}
    .vs-workflow {display:grid; grid-template-columns:repeat(5, minmax(0, 1fr)); gap:0; margin:20px 0; border:1px solid var(--vs-border); border-radius:12px; overflow:hidden; background:#fff; box-shadow:var(--vs-shadow-md);}
    .vs-step {min-height:76px; padding:14px 16px; border-right:1px solid var(--vs-border); background:#fff; transition:background .2s ease;}
    .vs-step:hover {background:var(--color-muted-bg);}
    .vs-step:last-child {border-right:0;}
    .vs-step-index {display:block; margin-bottom:5px; font-family:var(--vs-font-heading); background:linear-gradient(90deg, var(--vs-primary), var(--vs-accent)); -webkit-background-clip:text; background-clip:text; color:transparent; font-size:11px; font-weight:700; letter-spacing:.1em;}
    .vs-step strong {display:block; color:var(--vs-ink); font-family:var(--vs-font-heading); font-size:14px; font-weight:600;}
    .vs-step span {display:block; margin-top:3px; color:var(--vs-muted); font-size:12px; line-height:1.4;}
    .vs-source-card {margin:0 0 16px; padding:13px 15px; border:1px solid #DDD6FE; border-left:4px solid var(--vs-primary); border-radius:8px; background:#F3EFFF; color:#4C1D95; line-height:1.55;}
    .vs-source-card strong {color:#3B0764;}
    .status-card {margin:0 0 16px; padding:12px 15px; border:1px solid #FBCFE8; border-left:4px solid var(--vs-accent); border-radius:8px; background:#fff; box-shadow:var(--vs-shadow);}
    .status-card h3 {margin:0 0 2px !important; color:var(--vs-ink) !important; font-family:var(--vs-font-heading); font-size:14px !important;}
    .status-card p {margin:0 !important; color:var(--vs-muted);}
    .tab-nav {gap:0 !important; padding:0 !important; border:1px solid var(--vs-border) !important; border-radius:12px !important; background:var(--color-muted-bg) !important; overflow:hidden !important;}
    .tab-nav button {min-height:48px !important; border-radius:0 !important; border-right:1px solid var(--vs-border) !important; color:#6B5E85 !important; font-family:var(--vs-font-heading); font-weight:600 !important; cursor:pointer !important; transition:background .2s ease, color .2s ease, box-shadow .2s ease !important;}
    .tab-nav button:hover {color:var(--vs-primary) !important;}
    .tab-nav button:last-child {border-right:0 !important;}
    .tab-nav button.selected {background:#fff !important; color:var(--vs-primary-strong) !important; box-shadow:inset 0 -3px 0 var(--vs-accent) !important;}
    .tabitem {padding-top:20px !important;}
    .vs-section {padding:24px; border:1px solid var(--vs-border); border-radius:12px; background:var(--vs-surface); box-shadow:var(--vs-shadow-md);}
    .vs-section h2, .vs-section h3 {color:var(--vs-ink); font-family:var(--vs-font-heading);}
    .vs-section-copy {margin:0 0 16px; color:var(--vs-muted); line-height:1.6;}
    .vs-guide {display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:10px; margin:0 0 16px;}
    .vs-guide-item {padding:12px; border:1px solid var(--vs-border); border-radius:8px; background:var(--color-muted-bg); transition:box-shadow .2s ease, transform .2s ease;}
    .vs-guide-item:hover {box-shadow:var(--vs-shadow-md); transform:translateY(-2px);}
    .vs-guide-item b {display:block; color:var(--vs-primary-strong); font-size:12px;}
    .vs-guide-item span {display:block; margin-top:4px; color:var(--vs-muted); font-size:12px; line-height:1.4;}
    .vs-quick-path {display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:12px; margin:0 0 16px;}
    .vs-path {padding:16px; border:1px solid var(--vs-border); border-radius:12px; background:var(--color-muted-bg); transition:box-shadow .2s ease, transform .2s ease, border-color .2s ease;}
    .vs-path:hover {box-shadow:var(--vs-shadow-raised); transform:translateY(-2px); border-color:#DDD6FE;}
    .vs-path b {color:var(--vs-primary-strong); font-family:var(--vs-font-heading); font-size:14px;}
    .vs-path p {margin:6px 0 0; color:var(--vs-muted); font-size:12px; line-height:1.45;}
    .vs-source-mode {margin:0 0 16px !important;}
    .vs-source-mode .wrap {display:grid !important; grid-template-columns:repeat(3,minmax(0,1fr)) !important; gap:10px !important; border:0 !important; background:transparent !important;}
    .vs-source-mode label {min-height:58px !important; margin:0 !important; padding:12px !important; border:1px solid var(--vs-border) !important; border-radius:8px !important; background:#fff !important; color:#5F5470 !important; font-weight:600 !important; cursor:pointer !important; transition:border-color .2s ease, background .2s ease, box-shadow .2s ease !important;}
    .vs-source-mode label:has(input:checked) {border-color:var(--vs-primary) !important; background:#F3EFFF !important; box-shadow:inset 3px 0 0 var(--vs-primary) !important; color:var(--vs-primary-strong) !important;}
    .vs-source-mode label:hover {border-color:#C4B5FD !important; box-shadow:var(--vs-shadow-md) !important;}
    .vs-status-output textarea {min-height:72px !important; background:var(--color-muted-bg) !important; color:#4C1D95 !important;}
    .vs-tool-hint {margin:0 0 10px; padding:10px 14px; border:1px dashed #C4B5FD; border-radius:8px; background:#FBF8FF; color:#5B21B6 !important; font-size:13px;}
    .vs-tool-hint p {margin:0 !important; color:#5B21B6 !important;}
    .gr-group, .gr-form, .gr-box {border-radius:12px !important;}
    .gradio-container .styler {background: transparent !important;}
    .gr-button-primary, button.primary {background:var(--vs-accent) !important; border:0 !important; color:#fff !important; box-shadow:0 4px 10px rgba(236,72,153,.25) !important;}
    .gr-button-primary:hover, button.primary:hover {opacity:.92 !important; transform:translateY(-1px); box-shadow:0 8px 16px rgba(236,72,153,.3) !important;}
    button.secondary {background:transparent !important; border:2px solid var(--vs-primary) !important; color:var(--vs-primary) !important;}
    button.secondary:hover {background:#F3EFFF !important;}
    button.stop {border-radius:10px !important; border-color:var(--vs-destructive) !important; color:var(--vs-destructive) !important;}
    .gr-button, button {min-height:42px !important; border-radius:8px !important; font-weight:600 !important; cursor:pointer !important; transition:box-shadow .2s ease, background .2s ease, border-color .2s ease, transform .2s ease, opacity .2s ease !important;}
    .gr-button:hover, button:hover {box-shadow:var(--vs-shadow-md);}
    textarea, input, .wrap {border-radius:8px !important;}
    textarea:focus, input:focus {border-color:var(--color-ring) !important; box-shadow:0 0 0 3px rgba(124,58,237,.15) !important;}
    .gradio-container label span {color:#3B3650; font-weight:600;}
    .prose h1, .prose h2, .prose h3 {color:var(--vs-ink); font-family:var(--vs-font-heading);}
    .prose p {color:var(--vs-muted);}
    .gr-accordion {border:1px solid var(--vs-border) !important; border-radius:12px !important; background:var(--color-muted-bg) !important;}
    .gr-accordion .label-wrap {font-weight:700 !important; color:var(--vs-primary-strong) !important; cursor:pointer !important;}
    .vs-condition-card {margin:0 0 12px !important; padding:14px !important; border:1px solid #DDD6FE !important; border-left:4px solid var(--vs-primary) !important; border-radius:8px !important; background:#FFF !important; box-shadow:var(--vs-shadow) !important;}
    .vs-condition-card:nth-of-type(even) {border-left-color:var(--vs-secondary) !important;}
    .vs-condition-card .prose {margin-bottom:0 !important;}
    .vs-condition-card .prose p {margin:0 !important; color:var(--vs-primary-strong) !important; font-family:var(--vs-font-heading) !important; font-size:14px !important; font-weight:700 !important;}
    .vs-condition-delete {min-width:40px !important; width:40px !important; color:var(--vs-destructive) !important; border-color:#FECACA !important; background:#FFF7F7 !important;}
    .vs-event-policy {margin-top:14px !important; padding:14px !important; border:1px solid var(--vs-border) !important; border-radius:8px !important; background:#FBF8FF !important;}
    .vs-card-state {display:none !important;}
    .gr-json, .gr-code {border-radius:12px !important; overflow:hidden !important;}
    .gr-json, .gr-code, .cm-editor {font-family:"Cascadia Code", Consolas, monospace !important;}
    .vs-annotation-canvas {position:relative !important; user-select:none !important;}
    .vs-annotation-canvas.vs-dragging {cursor:crosshair !important;}
    .vs-annotation-canvas .image-container, .vs-annotation-canvas img {touch-action:none !important;}
    .vs-result-media {max-width:960px !important; margin:0 auto !important;}
    .vs-result-media img, .vs-result-media video {max-height:560px !important; width:100% !important; object-fit:contain !important;}
    .vs-result-media img, .vs-result-media video {cursor:zoom-in !important;}
    #vs-result-media-modal {display:none; position:fixed; inset:0; z-index:10000; padding:24px; background:rgba(20,16,31,.78); overflow:auto;}
    #vs-result-media-modal.is-open {display:flex; align-items:flex-start; justify-content:center;}
    #vs-result-media-modal .vs-media-modal-shell {position:relative; width:max-content; min-width:min(92vw,720px); max-width:none; margin:auto; padding:48px 18px 18px; border-radius:8px; background:#171221; box-shadow:0 20px 60px rgba(0,0,0,.45);}
    #vs-result-media-modal img, #vs-result-media-modal video {display:block; width:auto; height:auto; max-width:none; max-height:none; margin:auto;}
    #vs-result-media-modal .vs-media-modal-close {position:absolute; top:10px; right:12px; min-height:34px !important; padding:6px 12px; border:1px solid #E9D5FF; border-radius:6px; background:#fff; color:#4C1D95; cursor:pointer;}
    button:focus-visible, input:focus-visible, textarea:focus-visible, [role="tab"]:focus-visible, .label-wrap:focus-visible {outline:3px solid rgba(124,58,237,.4) !important; outline-offset:2px !important;}
    ::selection {background:rgba(124,58,237,.18);}
    @media (max-width: 980px) {
      .vs-workflow {grid-template-columns:repeat(2,minmax(0,1fr));}
      .vs-step {border-bottom:1px solid var(--vs-border);}
      .vs-step:nth-child(2n) {border-right:0;}
      .vs-guide {grid-template-columns:repeat(2,minmax(0,1fr));}
      .vs-quick-path {grid-template-columns:1fr;}
      .vs-source-mode .wrap {grid-template-columns:1fr !important;}
      .gradio-container {padding:16px !important;}
      .vs-hero {padding:24px 22px;}
    }
    @media (max-width: 560px) {
      .vs-workflow, .vs-guide {grid-template-columns:1fr;}
      .vs-step {border-right:0;}
      .vs-hero h1 {font-size:30px;}
    }
    @media (prefers-reduced-motion: reduce) {
      *, *:before, *:after {scroll-behavior:auto !important; transition:none !important; animation:none !important;}
    }
    """
    annotation_drag_js = """
    () => {
      const tool = () => document.querySelector('#vs-annotation-tool input:checked')?.value;
      const bind = () => {
        const root = document.querySelector('#vs-annotation-canvas');
        if (!root || root.dataset.dragBound === 'true') return;
        root.dataset.dragBound = 'true';
        let start = null;
        let preview = null;
        const imageBox = () => root.querySelector('img')?.getBoundingClientRect();
        const point = (event) => {
          const box = imageBox();
          if (!box) return null;
          return [
            Math.max(0, Math.min(box.width, event.clientX - box.left)),
            Math.max(0, Math.min(box.height, event.clientY - box.top)),
          ];
        };
        const clearPreview = () => {
          if (!preview) return;
          const node = preview.svg || preview;
          if (node && typeof node.remove === 'function') node.remove();
          preview = null;
        };
        const makeArrowPreview = () => {
          const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
          svg.style.cssText = 'position:absolute;pointer-events:none;z-index:5;overflow:visible;';
          const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
          line.setAttribute('stroke', '#EC4899');
          line.setAttribute('stroke-width', '3');
          line.setAttribute('stroke-linecap', 'round');
          const head = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
          head.setAttribute('fill', '#EC4899');
          svg.appendChild(line);
          svg.appendChild(head);
          return { svg, line, head };
        };
        root.addEventListener('pointerdown', (event) => {
          if (!['rectangle', 'direction'].includes(tool())) return;
          start = point(event);
          if (!start) return;
          event.preventDefault();
          event.stopPropagation();
          root.classList.add('vs-dragging');
          const box = root.getBoundingClientRect();
          if (tool() === 'direction') {
            preview = makeArrowPreview();
            const image = imageBox();
            const host = root.getBoundingClientRect();
            preview.svg.style.left = `${image.left - host.left}px`;
            preview.svg.style.top = `${image.top - host.top}px`;
            preview.svg.style.width = `${image.width}px`;
            preview.svg.style.height = `${image.height}px`;
            root.appendChild(preview.svg);
          } else {
            preview = document.createElement('div');
            preview.style.cssText = 'position:absolute;pointer-events:none;border:2px solid #EC4899;background:rgba(236,72,153,.10);z-index:5;border-radius:4px;';
            preview.dataset.rootLeft = String(box.left);
            preview.dataset.rootTop = String(box.top);
            root.appendChild(preview);
          }
          root.setPointerCapture?.(event.pointerId);
        }, true);
        root.addEventListener('pointermove', (event) => {
          if (!start || !preview) return;
          const end = point(event);
          if (!end) return;
          if (tool() === 'direction') {
            preview.line.setAttribute('x1', start[0]);
            preview.line.setAttribute('y1', start[1]);
            preview.line.setAttribute('x2', end[0]);
            preview.line.setAttribute('y2', end[1]);
            const dx = end[0] - start[0];
            const dy = end[1] - start[1];
            const len = Math.hypot(dx, dy) || 1;
            const ux = dx / len;
            const uy = dy / len;
            const headLen = 14;
            const spread = 7;
            const bx = end[0] - ux * headLen;
            const by = end[1] - uy * headLen;
            const lx = bx - uy * spread;
            const ly = by + ux * spread;
            const rx = bx + uy * spread;
            const ry = by - ux * spread;
            preview.head.setAttribute('points', `${end[0]},${end[1]} ${lx},${ly} ${rx},${ry}`);
          } else {
            const image = imageBox();
            const host = root.getBoundingClientRect();
            const left = Math.min(start[0], end[0]) + image.left - host.left;
            const top = Math.min(start[1], end[1]) + image.top - host.top;
            preview.style.left = `${left}px`;
            preview.style.top = `${top}px`;
            preview.style.width = `${Math.abs(end[0] - start[0])}px`;
            preview.style.height = `${Math.abs(end[1] - start[1])}px`;
          }
        }, true);
        root.addEventListener('pointerup', (event) => {
          if (!start || !['rectangle', 'direction'].includes(tool())) return;
          const end = point(event);
          event.preventDefault();
          event.stopPropagation();
          root.classList.remove('vs-dragging');
          clearPreview();
          if (end) {
            const target = document.querySelector('#vs-annotation-drag textarea');
            const image = imageBox();
            if (target && image) {
              target.value = JSON.stringify({
                start,
                end,
                canvas_size: [image.width, image.height],
              });
              target.dispatchEvent(new Event('input', {bubbles: true}));
            }
          }
          start = null;
        }, true);
      };
      new MutationObserver(bind).observe(document.body, {childList: true, subtree: true});
      bind();
      const modal = document.querySelector('#vs-result-media-modal');
      const modalImage = document.querySelector('#vs-result-media-original-image');
      const modalVideo = document.querySelector('#vs-result-media-original-video');
      const closeModal = () => {
        if (!modal) return;
        modal.classList.remove('is-open');
        if (modalVideo) { modalVideo.pause(); modalVideo.removeAttribute('src'); modalVideo.load(); }
        if (modalImage) modalImage.removeAttribute('src');
      };
      const openModal = (media) => {
        if (!modal || !modalImage || !modalVideo) return;
        const source = media.currentSrc || media.src;
        if (!source) return;
        const isVideo = media.tagName === 'VIDEO';
        modalImage.style.display = isVideo ? 'none' : 'block';
        modalVideo.style.display = isVideo ? 'block' : 'none';
        if (isVideo) { modalVideo.src = source; modalVideo.controls = true; }
        else modalImage.src = source;
        modal.classList.add('is-open');
      };
      document.addEventListener('click', (event) => {
        const close = event.target.closest?.('[data-vs-close-media-modal]');
        if (close || event.target === modal) { closeModal(); return; }
        const media = event.target.closest?.('.vs-result-media img, .vs-result-media video');
        if (media) { event.preventDefault(); openModal(media); }
      }, true);
      document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeModal(); });
    }
    """
    with gr.Blocks(title="Vision Skill Builder V2", css=css, js=annotation_drag_js) as demo:
        gr.HTML(
            """
            <section class="vs-hero">
              <p class="vs-kicker">VISION SKILL BUILDER / V2</p>
              <h1>创建、检查并运行视觉技能</h1>
                      <p>一句话先生成可编辑技能；需要时补充区域或方向参考；最后在图片或视频上运行并查看可解释结果。</p>
              <div class="vs-badges"><span class="vs-badge">自然语言生成</span><span class="vs-badge">可编辑规则</span><span class="vs-badge">图片与视频</span><span class="vs-badge">结果与证据</span></div>
            </section>
            """,
            padding=False,
        )
        gr.HTML(
            """
            <div id="vs-result-media-modal" aria-modal="true" role="dialog" aria-label="原尺寸结果媒体">
              <div class="vs-media-modal-shell">
                <button type="button" class="vs-media-modal-close" data-vs-close-media-modal>关闭</button>
                <img id="vs-result-media-original-image" alt="原尺寸标注结果">
                <video id="vs-result-media-original-video" controls></video>
              </div>
            </div>
            """,
            visible=True,
        )
        gr.HTML(
            """
            <section aria-label="按五步完成一次视觉任务">
              <div class="vs-workflow">
                <div class="vs-step"><span class="vs-step-index">01 创建技能</span><strong>选技能和媒体</strong><span>一句话、预置示例或历史版本，再选任务媒体</span></div>
                <div class="vs-step"><span class="vs-step-index">02 标注场景</span><strong>手工区域 / 方向</strong><span>规则需要空间或方向参考时，先在任务媒体上绘制</span></div>
                <div class="vs-step"><span class="vs-step-index">03 审核配置</span><strong>确认并调优</strong><span>关联已标注区域，再调整阈值、持续和告警</span></div>
                <div class="vs-step"><span class="vs-step-index">04 运行与结果</span><strong>上传并执行</strong><span>先看标注媒体，再看事件和证据</span></div>
                <div class="vs-step"><span class="vs-step-index">05 技能资产</span><strong>保存并复用</strong><span>把确认过的配置保存为独立版本</span></div>
              </div>
            </section>
            """,
            padding=False,
        )
        generated_state = gr.Textbox(visible=False, label="Generated SkillPackage state")
        annotation_state = gr.JSON({}, visible=False, label="Annotation workspace state")
        current_preset_state = gr.Textbox(
            "", visible=False, label="Current preset state"
        )
        current_source = gr.Markdown(
            "### 当前实际执行来源\n尚未生成或加载技能。",
            elem_classes="status-card",
        )
        with gr.Tabs(elem_classes="tab-nav"):
            with gr.Tab("01 创建"):
                gr.HTML(
                    """
                    <section class="vs-source-card">
                      <strong>从这里开始。生成后如需区域或方向，先进入“02 标注”；再在“03 审核”关联区域并调整事件规则。</strong>
                      <span> 新任务：用一句话创建。先体验：加载预置示例。已有经验：打开保存版本继续修改。</span>
                    </section>
                    <div class="vs-quick-path">
                      <div class="vs-path"><b>新建技能</b><p>描述目标、属性、关系或事件，系统生成可修改的执行规则。</p></div>
                      <div class="vs-path"><b>运行预置示例</b><p>加载已验证技能和默认素材，最快看到图片或视频结果。</p></div>
                      <div class="vs-path"><b>复用已有版本</b><p>加载自己的保存版本，改好后另存，新旧版本互不覆盖。</p></div>
                    </div>
                    """,
                    padding=False,
                )
                source_mode = gr.Radio(
                    ["自然语言生成", "预置演示技能", "已保存技能"],
                    value="自然语言生成",
                    label="选择开始方式（互斥）",
                    elem_classes="vs-source-mode",
                )
                with gr.Group(visible=True, elem_classes="vs-section") as natural_group:
                    gr.Markdown("### 用一句话创建\n只写要识别的目标、属性、关系或事件；ROI、切片和抽帧在下一步按需配置。")
                    instruction = gr.Textbox(
                        label="一句自然语言",
                        lines=3,
                        placeholder="例如：检测穿红色上衣、灰色裤子的人",
                    )
                    with gr.Row():
                        skill_id = gr.Textbox(
                            "my_visual_skill",
                            label="技能标识（英文，字母开头，可含数字、_、-）",
                        )
                        display_name = gr.Textbox("我的视觉技能", label="显示名称")
                    media_choice = gr.Radio(
                        ["仅图片", "仅视频", "图片和视频"],
                        value="图片和视频",
                        label="媒体能力",
                    )
                    compile_button = gr.Button("生成技能并继续", variant="primary")
                with gr.Group(visible=False, elem_classes="vs-section") as preset_group:
                    gr.Markdown("### 加载预置演示\n系统会一并加载已验证技能和对应的默认媒体，随后直接去“04 运行与结果”。")
                    preset = gr.Dropdown(controller.preset_names(), label="预置演示技能")
                    preset_button = gr.Button("加载预置", variant="primary")
                with gr.Group(visible=False, elem_classes="vs-section") as saved_group:
                    gr.Markdown("### 打开保存版本\n仅自定义版本可以删除；预置技能不可删除。")
                    saved = gr.Dropdown(controller.saved_skill_choices(), label="已保存技能")
                    with gr.Row():
                        saved_button = gr.Button("加载保存版本", variant="primary")
                        delete_button = gr.Button("删除选中自定义版本", variant="stop")
                source_status = gr.Textbox(
                    label="生成/加载状态", interactive=False, elem_classes="vs-status-output"
                )
                configuration_guidance = gr.Markdown(
                    "### 识别出的原子能力\n生成或加载技能后，这里会说明原文约束、当前配置和下一步。",
                    elem_classes="status-card",
                )
                with gr.Group(elem_classes="vs-section"):
                    gr.Markdown("### 当前任务媒体\n预置演示会自动带入默认素材；自定义技能在这里上传一次，后续标注和运行都使用这同一份媒体。")
                    task_target = gr.Textbox(label="任务目标", interactive=False)
                    with gr.Row():
                        run_variant = gr.Radio(
                            ["image", "video"], value="image", label="实际执行 variant"
                        )
                        media = gr.File(
                            label="当前任务媒体（图片或视频）",
                            type="filepath",
                        )
                    clear_task_media_button = gr.Button(
                        "清除任务媒体", variant="secondary"
                    )

            with gr.Tab("02 标注"):
                gr.HTML(ANNOTATION_GUIDANCE_MARKDOWN, padding=False)
                annotation_overview = gr.Markdown(
                    "此技能无需标注场景，可直接去“04 运行与结果”。",
                    elem_classes="status-card",
                )
                gr.Markdown(
                    "**通用标注向导**：当规则要求一个或多个命名区域时，在当前媒体上选择矩形或多边形并点击“保存并继续下一项”；需要更多区域时点击“添加另一个区域”。区域/车道数量无需预先确定，内部 ID 由系统自动生成，用户只需按需填写显示名称。当规则还要求逐区域方向参考时，全部区域保存后，再依次绘制方向箭头。箭头的业务含义以当前技能规则为准；画反时可点「反转方向（方向箭头）」。",
                    elem_classes="vs-tool-hint",
                )
                annotation_wizard = gr.Markdown(
                    "### 配置向导\n当前技能没有待配置的区域或方向。",
                    elem_classes="status-card",
                )
                with gr.Group(elem_classes="vs-section"):
                    gr.Markdown("### ① 准备标注画布\n画布使用「01 创建」中选好的任务媒体；视频任务可指定取哪一秒的画面来标注。")
                    with gr.Row():
                        annotation_timestamp = gr.Number(
                            0.0, label="视频标注帧时间（秒，图片任务忽略）"
                        )
                        prepare_annotation_button = gr.Button(
                            "加载画布", variant="secondary"
                        )
                    annotation_status = gr.Textbox(label="标注状态", interactive=False)
                    annotation_asset_path = gr.Textbox(
                        label="当前内容寻址媒体路径", interactive=False, visible=False
                    )
                    annotation_metadata = gr.JSON(label="原始媒体元数据", visible=False)
                    with gr.Row():
                        annotation_variant = gr.Radio(
                            ["image", "video"], value="image", label="标注媒体类型"
                        )
                        annotation_slot = gr.Dropdown(
                            label="要绘制的区域/方向（技能需要几个就画几个）"
                        )
                    configuration_slots_view = gr.JSON(
                        label="配置槽状态（当前选择已标记）", visible=True
                    )
                with gr.Group(elem_classes="vs-section"):
                    gr.Markdown("### ② 选择工具、在画布上绘制，然后保存")
                    annotation_canvas = gr.Image(
                        label="标注画布（在原图上直接绘制）",
                        type="pil",
                        interactive=False,
                        elem_id="vs-annotation-canvas",
                        elem_classes="vs-annotation-canvas",
                    )
                    annotation_tool = gr.Radio(
                        [
                            ("矩形", "rectangle"),
                            ("多边形", "polygon"),
                            ("方向箭头", "direction"),
                        ],
                        value="rectangle",
                        label="标注工具",
                        elem_id="vs-annotation-tool",
                    )
                    tool_hint = gr.Markdown(
                        "**矩形**：在画布上按住左键拖拽，松开后点击「保存并继续下一项」。",
                        elem_classes="vs-tool-hint",
                    )
                    with gr.Accordion("区域显示名称（可选）", open=False):
                        with gr.Row():
                            annotation_item_id = gr.Textbox(
                                label="系统内部 ID", visible=False
                            )
                            annotation_item_label = gr.Textbox(
                                label="显示名称（留空则自动命名）"
                            )
                        preset_media_candidates = gr.JSON(
                            label="预置素材候选", visible=False
                        )
                    annotation_points = gr.Textbox(
                        "[]", visible="hidden", elem_id="vs-annotation-points"
                    )
                    annotation_drag = gr.Textbox(
                        "", visible="hidden", elem_id="vs-annotation-drag"
                    )
                    with gr.Row():
                        annotation_delete_target = gr.Dropdown(
                            label="删除已保存标注（先选择要删除的车道或箭头）",
                            choices=[],
                            value=None,
                        )
                        delete_annotation_button = gr.Button(
                            "删除已保存标注", variant="stop"
                        )
                    with gr.Row():
                        undo_annotation_button = gr.Button("撤销上一步", variant="secondary")
                        clear_annotation_button = gr.Button("清空重画", variant="secondary")
                        reverse_direction_button = gr.Button(
                            "反转方向（方向箭头）", variant="secondary"
                        )
                        bind_annotation_button = gr.Button(
                            "保存并继续下一项", variant="primary"
                        )
                        add_region_button = gr.Button(
                            "添加另一个区域", variant="secondary"
                        )
                    with gr.Accordion("预置素材管理（高级）", open=False):
                        set_default_media_button = gr.Button(
                            "将当前任务媒体设为预置默认素材", variant="secondary"
                        )

            with gr.Tab("03 审核"):
                gr.HTML(
                    """
                    <section class="vs-section">
                      <h2>审核系统理解，按业务含义调整规则</h2>
                      <p class="vs-section-copy"><strong>大多数用户只需使用“业务规则配置”。</strong>按目标、区域、条件、持续时间和告警方式修改即可；原子节点与端口连接仅放在页面下方的专业模式中。</p>
                      <div class="vs-guide">
                        <div class="vs-guide-item"><b>检测慢 / 原图太大</b><span>用「图像缩放」降低输入分辨率。</span></div>
                        <div class="vs-guide-item"><b>视频长 / 运行久</b><span>用「视频抽帧」减少实际处理帧数。</span></div>
                        <div class="vs-guide-item"><b>小目标漏检</b><span>用「切片增强」，如远处车辆、小碎片。</span></div>
                        <div class="vs-guide-item"><b>输出有要求</b><span>用「结果媒体」指定清晰度或 FPS。</span></div>
                      </div>
                    </section>
                    """,
                    padding=False,
                )
                with gr.Group(elem_classes="vs-section"):
                    gr.Markdown("### 执行参数\n先选择图片或视频流程，点击“读取当前参数”查看真实生效值；修改任何配置卡片后，状态会显示在下方。")
                    variant_choice = gr.Radio(
                        ["image variant", "video variant"],
                        value="image variant",
                        label="当前编辑的执行流程（variant）",
                    )
                    event_rule_summary = gr.Markdown(
                        "### 事件判定\n生成或加载技能后，这里会说明是否需要配置持续时间。"
                    )
                    read_execution_button = gr.Button("读取当前参数", variant="secondary")
                    config_status = gr.Textbox(
                        label="配置状态",
                        interactive=False,
                        elem_classes="vs-status-output",
                        value="尚未修改配置。默认参数可直接运行。",
                    )

                with gr.Accordion("图像缩放 resize ｜ 原图过大、检测慢时使用", open=False):
                    gr.Markdown(
                        "**什么时候用**：原图分辨率很高导致检测慢，或需要统一输入尺寸。"
                        "**怎么配**：选“按长边缩放”并把长边设为 960~1280，通常就能明显提速且不影响精度；不确定就保持原尺寸。"
                    )
                    resize_mode = gr.Radio(
                        [
                            ("保持原尺寸（默认，推荐）", "identity"),
                            ("按长边缩放（提速常用）", "long_side"),
                            ("等比缩放到指定尺寸内", "contain"),
                            ("拉伸到指定尺寸（会变形）", "stretch"),
                        ],
                        value="identity",
                        label="缩放模式",
                    )
                    with gr.Row():
                        long_side = gr.Number(
                            1280, precision=0, label="长边像素", visible=False
                        )
                        resize_width = gr.Number(
                            1280, precision=0, label="目标宽度", visible=False
                        )
                        resize_height = gr.Number(
                            720, precision=0, label="目标高度", visible=False
                        )
                        resize_interpolation = gr.Radio(
                            ["nearest", "bilinear", "bicubic"],
                            value="bilinear",
                            label="插值方式（默认 bilinear 即可）",
                        )
                    resize_apply_button = gr.Button("应用缩放配置", variant="primary")
                with gr.Accordion("视频抽帧 ｜ 视频长、运行慢时使用（仅视频流程）", open=False):
                    gr.Markdown(
                        "**什么时候用**：视频几十秒以上、运行一次要等很久。"
                        "**怎么配**：默认每秒 1 帧；需要更细的时间粒度时再提高目标 FPS。"
                        "也可用起止时间只分析片段。注意抽帧会改变检测结果的时间粒度。"
                    )
                    sample_mode = gr.Radio(
                        [
                            ("保持原始 FPS（默认，逐帧处理）", "original_fps"),
                            ("目标 FPS（默认 1 帧/秒）", "fps"),
                            ("固定时间间隔（每 N 秒 1 帧）", "interval"),
                            ("固定帧步长（每 N 帧取 1 帧）", "frame_step"),
                        ],
                        value="fps",
                        label="抽帧模式",
                    )
                    with gr.Row():
                        sample_fps = gr.Number(1.0, label="目标 FPS", visible=False)
                        interval_seconds = gr.Number(
                            1.0, label="间隔秒数", visible=False
                        )
                        frame_step = gr.Number(
                            1, precision=0, label="帧步长", visible=False
                        )
                    with gr.Row():
                        start_seconds = gr.Number(0.0, label="起始秒（从第几秒开始）")
                        end_seconds = gr.Number(None, label="结束秒（留空=到结尾）")
                        max_frames = gr.Number(
                            None, precision=0, label="最多处理帧数（留空=不限）"
                        )
                    sample_button = gr.Button("应用抽帧配置", variant="primary")
                with gr.Accordion(
                    "业务规则配置（原事件规则编辑，推荐）｜目标、区域、条件、持续与告警",
                    open=True,
                ):
                    gr.Markdown(
                        "**业务事件快捷配置，按 3 步完成：** ① 选择要调整的业务事件；② 修改条件卡；③ 设置持续与告警并应用。"
                        "目标类别决定识别什么，统计范围决定在哪里判断，条件关系决定全部满足还是任一满足。"
                        "区域形状和数量仍在“02 标注”修改。"
                    )
                    event_rule_event = gr.Dropdown(
                        choices=[], label="要编辑的事件规则", interactive=True
                    )
                    event_rule_scope = gr.Dropdown(
                        choices=[], label="统计范围（由一句话决定）", interactive=False
                    )
                    gr.Markdown(
                        "#### ② 判断条件（条件设置）\n每张卡是一条用户可读的业务条件。全画面、所有标注区域和指定区域会真实写入执行流程。"
                        "“全部手工标注区域”是范围选择，不是单独区域；要删除具体区域请回到“02 标注”。"
                    )
                    event_rule_card_state = gr.Textbox(
                        value="[]", container=False, elem_classes=["vs-card-state"]
                    )
                    event_rule_cards = []
                    for card_index in range(1, 7):
                        with gr.Group(visible=False, elem_classes=["vs-condition-card"]) as card_group:
                            with gr.Row():
                                gr.Markdown(f"**条件 {card_index}**")
                                card_enabled = gr.Checkbox(
                                    True, label="启用", min_width=74
                                )
                                card_delete = gr.Button(
                                    "删除", size="sm", elem_classes=["vs-condition-delete"]
                                )
                            with gr.Row():
                                card_source = gr.Dropdown(
                                    choices=[],
                                    label=f"条件 {card_index}：区域与统计量",
                                    interactive=True,
                                )
                                card_categories = gr.Dropdown(
                                    choices=[],
                                    multiselect=True,
                                    label=f"条件 {card_index}：目标类别",
                                    interactive=True,
                                )
                                card_operator = gr.Dropdown(
                                    [">", ">=", "=", "<=", "<", "==", "!="],
                                    value=">=",
                                    label=f"条件 {card_index}：比较符",
                                )
                                card_value = gr.Number(0, label=f"条件 {card_index}：阈值")
                            event_rule_cards.append({
                                "group": card_group,
                                "enabled": card_enabled,
                                "delete": card_delete,
                                "source": card_source,
                                "categories": card_categories,
                                "operator": card_operator,
                                "value": card_value,
                            })
                    event_rule_add_condition = gr.Button("添加条件", variant="secondary")
                    with gr.Group(
                        visible=False,
                        elem_classes=["vs-condition-card"],
                    ) as event_rule_association_group:
                        gr.Markdown(
                            "#### 目标框关联\n"
                            "选择同一帧中需要关联的主体和证据类别；阈值表示两框重叠比例。"
                        )
                        event_rule_association = gr.Dropdown(
                            choices=[],
                            label="要编辑的目标关联",
                            interactive=True,
                        )
                        with gr.Row():
                            event_rule_association_subject = gr.Dropdown(
                                choices=[],
                                label="主体候选框",
                                interactive=True,
                            )
                            event_rule_association_object = gr.Dropdown(
                                choices=[],
                                label="关联候选框",
                                interactive=True,
                            )
                            event_rule_association_threshold = gr.Slider(
                                0.0,
                                1.0,
                                0.3,
                                step=0.05,
                                label="框重叠阈值",
                            )
                    # Keep the legacy two-condition reader on isolated hidden
                    # fields.  Sharing the visible card components made its
                    # asynchronous refresh overwrite card-specific choices.
                    event_rule_category_node = gr.Textbox(value="", visible=False)
                    event_rule_categories = gr.Dropdown(
                        choices=[], multiselect=True, value=[], visible=False,
                    )
                    event_rule_condition_1 = gr.Dropdown(choices=[], visible=False)
                    event_rule_operator_1 = gr.Dropdown(
                        [">", ">=", "=", "<=", "<", "==", "!="], visible=False,
                    )
                    event_rule_value_1 = gr.Number(visible=False)
                    event_rule_condition_2_row = gr.Group(visible=False)
                    event_rule_condition_2 = gr.Dropdown(choices=[], visible=False)
                    event_rule_operator_2 = gr.Dropdown(
                        [">", ">=", "=", "<=", "<", "==", "!="], visible=False,
                    )
                    event_rule_value_2 = gr.Number(visible=False)
                    event_rule_region_overrides = gr.Dataframe(
                        headers=["已标注区域"], datatype=["str"], type="array",
                        value=[], visible=False,
                    )
                    event_rule_legacy_apply_probe = gr.Button(visible=False)
                    with gr.Group(elem_classes=["vs-event-policy"]):
                        gr.Markdown("**事件触发策略**\n下列配置作用于整组启用条件，避免多个条件各自持续导致含义不清。")
                        with gr.Row():
                            event_rule_logic = gr.Radio(
                                [("全部条件同时满足（AND）", "all"), ("任一条件满足（OR）", "any")],
                                value="all",
                                label="条件关系",
                            )
                            event_rule_seconds = gr.Number(
                                1.0, minimum=0, label="持续时间（秒）"
                            )
                            event_rule_gap = gr.Number(
                                0.5, minimum=0, label="允许中断（秒）"
                            )
                            event_rule_trigger = gr.Radio(
                                [("只触发一次", "once"), ("达到阈值后重复触发", "repeat")],
                                value="once",
                                label="触发方式",
                            )
                        event_rule_alert = gr.Textbox(label="告警名称")
                    with gr.Row():
                        event_rule_read_button = gr.Button(
                            "读取当前事件规则", variant="secondary"
                        )
                        event_rule_apply_button = gr.Button(
                            "应用事件规则", variant="primary"
                        )
                    event_rule_status = gr.Textbox(
                        label="当前规则说明（只读）",
                        interactive=False,
                        value="生成或加载技能后，在这里读取可编辑事件原子。",
                    )
                with gr.Accordion("切片增强与去重 ｜ 小目标漏检时使用", open=False):
                    gr.Markdown(
                        "**什么时候用**：目标在画面里很小（远处车辆、路面小碎片、高空作业人员）导致漏检。"
                        "**怎么配**：勾选“切片增强”，把大图切成 640×640 小块分别检测再合并；"
                        "切片会有重复框，用去重合并（IoS 0.5 是稳妥默认，一般不用改）。"
                    )
                    tile_enabled = gr.Checkbox(False, label="启用切片增强（小目标场景打开）")
                    with gr.Column(visible=False) as tile_options:
                        include_full = gr.Checkbox(
                            True, label="同时保留整图检测（建议保持勾选，大小目标兼顾）"
                        )
                        with gr.Row():
                            tile_width = gr.Number(640, precision=0, label="切片宽度")
                            tile_height = gr.Number(640, precision=0, label="切片高度")
                            overlap_x = gr.Slider(
                                0, 0.9, 0.2, step=0.05, label="横向重叠比例"
                            )
                            overlap_y = gr.Slider(
                                0, 0.9, 0.2, step=0.05, label="纵向重叠比例"
                            )
                        with gr.Row():
                            dedup_metric = gr.Radio(
                                [
                                    ("IoS（按较小框重叠，推荐）", "ios"),
                                    ("IoU（按整体重叠）", "iou"),
                                ],
                                value="ios",
                                label="去重指标",
                            )
                            dedup_threshold = gr.Slider(
                                0, 1, 0.5, step=0.05, label="去重阈值（越高越宽松）"
                            )
                    preprocess_button = gr.Button("应用切片/去重配置", variant="primary")
                with gr.Accordion("候选框二次可见性确认（可选）", open=False):
                    gr.Markdown(
                        "**何时使用**：切片已找回候选框，但某个类别容易被相似物体误报时。"
                        "它先保留全图/切片的召回结果，再对选中类别裁出带上下文的局部图复核；"
                        "未选中的类别不受影响。\n\n"
                        "**怎么配**：先点击“读取当前确认配置”，选择待复核的检测类别，"
                        "再填写能确认目标真实存在的英文可见证据短语。保存后这条复核链会写入 Effective SkillPackage。"
                    )
                    context_enabled = gr.Checkbox(
                        False, label="启用候选框二次可见性确认"
                    )
                    context_targets = gr.Dropdown(
                        choices=[], multiselect=True, label="待复核检测类别"
                    )
                    context_phrases = gr.Textbox(
                        lines=3,
                        label="确认可见证据提示词",
                        placeholder="每行一个英文短语，例如：complete trash bin with visible container body",
                    )
                    with gr.Row():
                        context_padding = gr.Slider(
                            0, 1, 1.0, step=0.05, label="上下文边距比例"
                        )
                        context_long_side = gr.Number(
                            640, precision=0, minimum=64, label="复核裁剪长边"
                        )
                    with gr.Row():
                        context_read_button = gr.Button("读取当前确认配置", variant="secondary")
                        context_apply_button = gr.Button("应用二次确认配置", variant="primary")
                    context_status = gr.Textbox(
                        label="二次确认配置状态", interactive=False,
                        value="默认关闭。它是切片召回后的可选复核，不会替代切片或全图检测。",
                    )
                with gr.Accordion("结果媒体尺寸与 FPS ｜ 对输出清晰度/流畅度有要求时使用", open=False):
                    gr.Markdown(
                        "**什么时候用**：需要把标注结果导出为固定分辨率，或让结果视频按指定帧率播放。"
                        "**怎么配**：保持“原始媒体尺寸 + 按采样时间线”即可，结果和原素材一致；"
                        "只有对外交付有明确规格时才选固定值。"
                    )
                    with gr.Row():
                        output_size_mode = gr.Radio(
                            [
                                ("原始媒体尺寸（默认，推荐）", "source"),
                                ("处理后尺寸（跟随 resize）", "processed"),
                                ("固定尺寸", "fixed"),
                            ],
                            value="source",
                            label="结果媒体尺寸",
                        )
                        output_width = gr.Number(
                            1280, precision=0, label="结果宽度", visible=False
                        )
                        output_height = gr.Number(
                            720, precision=0, label="结果高度", visible=False
                        )
                    with gr.Row():
                        output_fps_mode = gr.Radio(
                            [
                                ("按采样时间线（默认，时长一致）", "sample_timeline"),
                                ("原始视频 FPS（更流畅，文件更大）", "source"),
                                ("固定 FPS", "fixed"),
                            ],
                            value="sample_timeline",
                            label="结果视频 FPS",
                        )
                        output_fps = gr.Number(
                            25.0, label="固定结果 FPS", visible=False
                        )
                    output_config_button = gr.Button("应用结果媒体配置", variant="primary")
                with gr.Accordion(
                    "高级原子编排（专业模式）｜节点、连接、复杂时序与结果契约",
                    open=False,
                ):
                    editor_overview = gr.Markdown(
                        "### 统一规则编排中心（专业模式）\n仅在业务规则配置无法表达需求时使用。"
                    )
                    gr.Markdown(
                        "这里展示执行层原子、节点 ID、输入端口、Recipe 和 EventPattern。"
                        "它与上方业务规则配置共享同一份 SkillEditorDocument；专业修改不会被普通表单静默覆盖。"
                    )
                    unified_status = gr.Textbox(
                        label="统一配置状态", interactive=False,
                        value="生成或加载技能后，读取 LLM 生成的完整配置。",
                    )
                    editor_history = gr.JSON(
                        value={"undo": [], "redo": []}, visible=False
                    )
                    with gr.Row():
                        unified_undo_button = gr.Button("撤销", variant="secondary")
                        unified_redo_button = gr.Button("重做", variant="secondary")
                        unified_restore_button = gr.Button("恢复 LLM 生成结果", variant="secondary")
                    with gr.Row():
                        unified_branch = gr.Dropdown(
                            choices=[], label="业务分支（名称 + 内部 ID）"
                        )
                        unified_action = gr.Dropdown(
                            ["新增原子", "复制原子", "删除原子", "替换能力", "连接原子", "断开连接"],
                            value="新增原子", label="组合编辑动作",
                        )
                    with gr.Row():
                        unified_branch_action = gr.Dropdown(
                            ["新增分支", "复制分支", "重命名分支", "启用/停用", "上移", "下移", "删除分支"],
                            value="新增分支", label="业务分支动作",
                        )
                        unified_new_branch_id = gr.Textbox(
                            label="新分支 ID", placeholder="例如 branch_accident"
                        )
                        unified_branch_name = gr.Textbox(
                            label="分支显示名称", placeholder="例如 区域3交通事故"
                        )
                        unified_branch_button = gr.Button("执行分支编辑", variant="secondary")
                    with gr.Row():
                        atomic_node = gr.Dropdown(
                            choices=[], label="原子节点（名称 + 来源 ID）"
                        )
                        unified_operator = gr.Dropdown(
                            choices=[], label="原子能力（完整注册表）"
                        )
                        unified_new_node_id = gr.Textbox(
                            label="新节点 ID", placeholder="例如 region_people_count"
                        )
                    with gr.Row():
                        unified_source_node = gr.Dropdown(choices=[], label="连接：来源原子")
                        unified_target_node = gr.Dropdown(choices=[], label="连接：目标原子")
                        unified_port = gr.Textbox(
                            label="目标输入端口", placeholder="例如 objects / conditions / events"
                        )
                        unified_mutate_button = gr.Button("执行组合编辑", variant="secondary")
                    recipes = build_recipe_catalog()
                    with gr.Row():
                        unified_recipe = gr.Dropdown(
                            choices=[
                                (f"{item.display_name}（{item.recipe_id}）", item.recipe_id)
                                for item in recipes.values()
                            ],
                            value=next(iter(recipes)) if recipes else None,
                            label="插入可复用组合 Recipe",
                        )
                        unified_recipe_button = gr.Button("插入到当前业务分支", variant="secondary")
                    gr.Markdown("#### 当前原子关键参数（用户覆盖层）")
                    with gr.Row():
                        atomic_parameter = gr.Dropdown(
                            choices=[], label="关键参数"
                        )
                    atomic_value = gr.Code(
                        label="参数值（JSON；普通文本可直接填写）", language="json", lines=5
                    )
                    with gr.Row():
                        atomic_read_button = gr.Button("读取完整配置", variant="secondary")
                        atomic_apply_button = gr.Button("保存参数到草稿", variant="primary")
                        atomic_reset_button = gr.Button("恢复生成值", variant="secondary")
                    atomic_status = gr.Textbox(label="原子配置状态", interactive=False)
                    with gr.Accordion("复杂事件编排 EventPattern", open=False):
                        gr.Markdown(
                            "支持同时有效、时间窗内全部完成、先后顺序、重叠、N 选 M、缺失和重复等组合；"
                            "每个阶段可独立配置持续时间、身份范围和允许中断。"
                        )
                        unified_patterns = gr.Code(
                            label="EventPattern 列表（JSON）", language="json", lines=14
                        )
                        unified_patterns_button = gr.Button("保存复杂事件编排到草稿", variant="secondary")
                    with gr.Accordion("待确认条件与结果契约", open=False):
                        with gr.Row():
                            unified_pending_choice = gr.Dropdown(
                                choices=[], label="需用户确认的不确定条件"
                            )
                            unified_pending_value = gr.Code(
                                label="确认值（JSON 或文本）", language="json", lines=3
                            )
                            unified_pending_button = gr.Button("确认并写入草稿", variant="secondary")
                        unified_pending = gr.JSON(label="待确认条件（02 实际标注或 03 用户确认）")
                        unified_results = gr.Code(
                            label="用户结果契约（数值、方向、目标、轨迹、事件、时间线、标注媒体等）",
                            language="json", lines=10,
                        )
                        unified_results_button = gr.Button("保存结果与证据契约到草稿", variant="secondary")
                    unified_apply_button = gr.Button(
                        "完整校验并应用为当前运行版本", variant="primary"
                    )
                    with gr.Accordion("完整 V3 编辑文档（审计）", open=False):
                        atomic_rows = gr.JSON(label="原子参数清单")
                        editor_document = gr.Code(
                            label="SkillEditorDocument@3.0（当前唯一配置源）", language="json", lines=16
                        )
                with gr.Accordion("模型输入提示词（调试）", open=False):
                    gr.Markdown(
                        "**什么时候用**：模型漏检、误检或需要比较不同英文表述时。"
                        "选择一个 Rex 检测节点，修改它发送给模型的视觉查询。"
                        "**不会改动规则语义或其它节点**；系统始终自动追加固定的框坐标输出协议。"
                    )
                    grounding_prompt_node = gr.Dropdown(
                        choices=[],
                        label="要编辑的模型检测节点",
                        interactive=True,
                    )
                    grounding_prompt_text = gr.Textbox(
                        lines=3,
                        label="模型检测提示词",
                        placeholder="例如：Someone fell down",
                    )
                    with gr.Row():
                        grounding_prompt_read_button = gr.Button(
                            "读取当前提示词", variant="secondary"
                        )
                        grounding_prompt_apply_button = gr.Button(
                            "应用到当前节点", variant="primary"
                        )
                        grounding_prompt_reset_button = gr.Button(
                            "还原默认短语提示词", variant="secondary"
                        )
                    grounding_prompt_status = gr.Textbox(
                        label="模型提示词说明",
                        interactive=False,
                        value="生成或加载技能后，读取当前 Rex 检测节点的视觉查询。",
                    )
                with gr.Accordion("高级审计与手动编辑 ｜ 检查 LLM 语义、直接改 JSON、保存版本", open=False):
                    gr.Markdown(
                        "**什么时候用**：怀疑 LLM 理解错了你的描述（看 Semantic IR 和未解析条件）；"
                        "需要直接编辑完整 SkillPackage JSON；或把调好的配置保存为新版本。普通使用不需要展开。"
                    )
                    with gr.Row():
                        semantic = gr.Code(label="Semantic IR（LLM 理解的语义）", language="json", lines=18)
                        unresolved = gr.JSON(label="未解析条件（LLM 没听懂的部分）")
                    effective = gr.Code(
                        label="Effective SkillPackage（唯一执行配置，可手动修改）",
                        language="json",
                        lines=22,
                    )
                    with gr.Row():
                        load_variant_button = gr.Button(
                            "读取当前 variant JSON", variant="secondary"
                        )
                        apply_variant_button = gr.Button(
                            "写回 variant 并校验", variant="secondary"
                        )
                    variant_status = gr.Textbox(label="variant 状态", interactive=False)
                    variant_editor = gr.Code(
                        label="当前 WorkflowVariant JSON",
                        language="json",
                        lines=12,
                        visible=False,
                    )
                    with gr.Row():
                        validate_button = gr.Button("校验完整配置", variant="secondary")
                        diff_button = gr.Button("查看 Generated / Effective Diff", variant="secondary")
                        save_button = gr.Button("保存为新版本", variant="primary")
                    with gr.Row():
                        save_id = gr.Textbox(label="保存技能标识（可自定义）")
                        save_display = gr.Textbox(label="保存显示名称（可自定义）")
                    validation = gr.Textbox(label="校验结果", lines=4)
                    diff_output = gr.Code(label="配置 Diff", lines=10)
                    saved_path = gr.Textbox(label="保存路径")
            with gr.Tab("04 运行"):
                gr.HTML(
                    """
                    <section class="vs-section">
                      <h2>执行当前技能并查看结果</h2>
                      <p class="vs-section-copy">这里运行的是页面中当前 Effective SkillPackage，而不是隐藏的预置配置。任务媒体已在第一步选定；完成后先看标注结果，再检查事件、轨迹与节点证据。</p>
                      <div class="vs-guide">
                        <div class="vs-guide-item"><b>1. 目标与 variant</b><span>必须与实际上传的媒体类型一致。</span></div>
                        <div class="vs-guide-item"><b>2. 调用估算</b><span>视频会明确显示抽样帧数、调用次数和时长警告。</span></div>
                        <div class="vs-guide-item"><b>3. 运行</b><span>执行的是当前 Effective 配置，不是隐藏预置。</span></div>
                        <div class="vs-guide-item"><b>4. 验证结果</b><span>先比对标注媒体；需要排查时再展开结构化结果和 Trace。</span></div>
                      </div>
                    </section>
                    """,
                    padding=False,
                )
                with gr.Group(elem_classes="vs-section"):
                    gr.Markdown("### ① 检查并运行\n任务媒体已在“01 创建技能”中选择。预置演示加载后可直接检查和运行。")
                    run_media_summary = gr.Markdown(
                        "**本次运行媒体：尚未选择。** 请返回“01 创建技能”的“当前任务媒体”上传或加载素材。",
                        elem_classes="vs-source-card",
                    )
                    with gr.Row():
                        inspect_button = gr.Button("检查媒体与调用估算", variant="secondary")
                        run_button = gr.Button("运行当前 Effective 技能", variant="primary")
                    policy_text = gr.Textbox(label="调用估算", interactive=False)
                    with gr.Accordion("媒体策略与调用明细（高级）", open=False):
                        policy_json = gr.JSON(label="媒体策略（30 秒推荐 / warn-only）")
                    run_status = gr.Textbox(label="运行状态", lines=3)
                    run_dir = gr.Textbox(label="运行产物目录", interactive=False)
                with gr.Group(elem_classes="vs-section"):
                    gr.Markdown("### ② 先看可视化结果\n运行完成后，这里只显示与媒体类型匹配的结果（图片任务出图，视频任务出视频）。")
                    gr.Markdown("点击结果媒体可查看原尺寸；按 Esc 或关闭按钮返回。")
                    with gr.Row():
                        annotated_image = gr.Image(
                            label="标注图片", visible=False, elem_classes="vs-result-media"
                        )
                        annotated_video = gr.Video(
                            label="标注视频", visible=False, elem_classes="vs-result-media"
                        )
                with gr.Group(elem_classes="vs-section"):
                    gr.Markdown("### ③ 按需查看证据与运行细节")
                    with gr.Tabs():
                        with gr.Tab("检测结果"):
                            detections = gr.JSON(label="检测结果")
                        with gr.Tab("轨迹结果"):
                            tracks = gr.JSON(label="轨迹结果")
                        with gr.Tab("事件结果"):
                            events = gr.JSON(label="事件结果")
                        with gr.Tab("数值结果"):
                            measurements = gr.JSON(label="数值结果")
                        with gr.Tab("区域结果"):
                            regions = gr.JSON(label="区域结果")
                        with gr.Tab("方向结果"):
                            directions = gr.JSON(label="方向结果")
                        with gr.Tab("语义原子解释"):
                            constraints = gr.JSON(label="语义原子解释")
                        with gr.Tab("逐节点 Trace"):
                            trace = gr.JSON(label="逐节点 Trace")

            with gr.Tab("05 资产"):
                gr.HTML(
                    """
                    <section class="vs-section">
                      <h2>技能资产与固定能力</h2>
                      <p class="vs-section-copy">在这里把当前 Effective SkillPackage 保存为可复用版本，或加载、删除此前确认过的自定义版本。保存的是当前可执行配置，预置技能不会被删除或覆盖。</p>
                    </section>
                    """,
                    padding=False,
                )
                with gr.Group(elem_classes="vs-section"):
                    gr.Markdown("### 保存当前配置\n保存后生成独立版本；同一个技能标识会自动递增版本号。")
                    with gr.Row():
                        asset_save_id = gr.Textbox(label="资产保存技能标识")
                        asset_save_display = gr.Textbox(label="资产保存显示名称")
                    asset_save_button = gr.Button("保存为独立版本", variant="primary")
                    asset_save_path = gr.Textbox(label="资产保存路径", interactive=False)
                with gr.Group(elem_classes="vs-section"):
                    gr.Markdown("### 已保存版本\n加载会写回当前 Effective SkillPackage；删除只影响选中的自定义版本。")
                    asset_saved = gr.Dropdown(
                        controller.saved_skill_choices(), label="已保存版本"
                    )
                    with gr.Row():
                        asset_load_button = gr.Button("加载选中版本", variant="primary")
                        asset_delete_button = gr.Button("删除选中版本", variant="stop")
                    asset_status = gr.Textbox(label="资产操作状态", interactive=False)
                with gr.Accordion("Operator Registry（高级参考）", open=False):
                    gr.JSON(controller.registry.planner_catalog(), label="Operator Registry")
                    gr.JSON(
                        {
                            "media": ["image", "video", "image+video"],
                            "dedup": {
                                "IoS": "intersection / min(area_a, area_b)",
                                "IoU": "intersection / union",
                            },
                            "tracking": {
                                "default": "IoU matching",
                                "ByteTrack": "requires reliable detection scores",
                                "Deep SORT": "requires an appearance/ReID encoder",
                            },
                        },
                        label="固定能力说明",
                    )

        def _switch_source(mode):
            return (
                gr.update(visible=mode == "自然语言生成"),
                gr.update(visible=mode == "预置演示技能"),
                gr.update(visible=mode == "已保存技能"),
                "",
                "",
                "",
                {},
                "### 当前实际执行来源\n尚未生成或加载技能。",
            )

        def _expand_loaded(generated, effective_json, semantic_json, status, source):
            semantic_data = json_object_or_empty(semantic_json)
            package_data = json_object_or_empty(effective_json)
            return (
                generated,
                effective_json,
                semantic_json,
                semantic_data.get("unresolved", []),
                status,
                source,
                package_data.get("original_instruction", ""),
            )

        def _unresolved_of(semantic_json):
            return json_object_or_empty(semantic_json).get("unresolved", [])

        def _load_asset(selection):
            generated, effective_json, semantic_json, status, source = (
                controller.load_saved_skill(selection)
            )
            return (
                generated,
                effective_json,
                semantic_json,
                status,
                source,
                _instruction_of(effective_json),
            )

        def _refresh_saved_choices():
            choices = controller.saved_skill_choices()
            return gr.update(choices=choices), gr.update(choices=choices, value=None)

        def _instruction_of(effective_json):
            return json_object_or_empty(effective_json).get(
                "original_instruction", ""
            )

        def _temporal_summary(effective_json, media_type):
            return controller.temporal_rules_markdown(effective_json, media_type)

        def _configuration_guidance(effective_json, media_type):
            return controller.configuration_guidance_markdown(
                effective_json, media_type
            )

        def _slot_updates(effective_json, media_type):
            if not effective_json:
                return (
                    gr.update(choices=[], value=None),
                    [],
                    "尚未生成或加载技能。",
                    "### 配置向导\n请先创建或加载技能。",
                )
            try:
                choices, rows = controller.annotation_slots(effective_json, media_type)
            except (ValueError, TypeError):
                return (
                    gr.update(choices=[], value=None),
                    [],
                    "技能尚未生成成功，无法读取场景标注配置。",
                    "### 配置向导\n暂时无法读取配置槽。",
                )
            choices, value = controller.annotation_slot_options(
                effective_json, media_type
            )
            return (
                gr.update(choices=choices, value=value, interactive=bool(rows)),
                controller.annotation_slots_with_selection(
                    effective_json, media_type, value
                ),
                controller.annotation_overview(effective_json, media_type),
                controller.annotation_wizard_markdown(effective_json, media_type),
            )

        def _prepare_annotation(effective_json, media_type, path, timestamp, state):
            if not effective_json or not path:
                return (
                    gr.update(),
                    dict(state or {}),
                    [],
                    gr.update(choices=[], value=None, interactive=False),
                    "请先加载技能和任务媒体，再开始标注。",
                    "### 配置向导\n请先加载技能和任务媒体。",
                    gr.update(choices=["rectangle", "polygon"], value="rectangle"),
                    gr.update(value=""),
                    gr.update(value=""),
                    gr.update(choices=[], value=None),
                )
            preview, new_state, rows = controller.refresh_annotation_preview(
                effective_json, media_type, path, timestamp, state
            )
            choices, _ = controller.annotation_slots(effective_json, media_type)
            wizard = controller.annotation_wizard_state(effective_json, media_type)
            value = wizard["current_slot"] or (choices[0][1] if choices else None)
            tool, item_id, item_label = controller.annotation_wizard_defaults(
                effective_json, media_type, value
            )
            delete_choices = controller.named_item_choices(
                effective_json, media_type, value
            )
            return (
                preview,
                new_state,
                controller.annotation_slots_with_selection(
                    effective_json, media_type, value
                ),
                gr.update(choices=choices, value=value),
                controller.annotation_overview(effective_json, media_type),
                controller.annotation_wizard_markdown(effective_json, media_type),
                gr.update(
                    choices=controller.annotation_tool_choices(
                        effective_json, media_type, value
                    ),
                    value=tool,
                ),
                gr.update(value=item_id),
                gr.update(value=item_label),
                gr.update(choices=delete_choices, value=None),
            )

        def _ingest_task_media(path, timestamp):
            if not path:
                return controller.cleared_task_media_state()
            stored_path, metadata, preview, state, status = controller.ingest_media(
                path, timestamp
            )
            media_type = state["media_type"]
            return (
                stored_path,
                metadata,
                preview,
                state,
                status,
                media_type,
                media_type,
                controller.runtime_media_summary(stored_path, media_type),
                controller.editor_variant_for_media(media_type),
            )

        def _sync_run_variant(effective_json, preferred):
            return controller.preferred_executable_variant(
                effective_json, preferred
            )

        source_mode.change(
            _switch_source,
            source_mode,
            [
                natural_group,
                preset_group,
                saved_group,
                generated_state,
                effective,
                semantic,
                unresolved,
                current_source,
            ],
        )
        compile_button.click(
            controller.compile_skill,
            [instruction, media_choice, skill_id, display_name],
            [generated_state, effective, semantic, source_status, current_source],
        ).then(
            _unresolved_of,
            semantic,
            unresolved,
        ).then(_instruction_of, effective, task_target).then(
            lambda choice: "video" if choice == "仅视频" else "image",
            media_choice,
            annotation_variant,
        ).then(
            controller.preferred_executable_variant,
            [effective, annotation_variant],
            annotation_variant,
        ).then(
            _sync_run_variant,
            [effective, annotation_variant],
            run_variant,
        ).then(
            controller.editor_variant_for_media,
            annotation_variant,
            variant_choice,
        ).then(
            _slot_updates,
            [effective, annotation_variant],
            [annotation_slot, configuration_slots_view, annotation_overview, annotation_wizard],
        ).then(
            _temporal_summary,
            [effective, annotation_variant],
            event_rule_summary,
        ).then(
            _configuration_guidance,
            [effective, annotation_variant],
            configuration_guidance,
        )
        preset_button.click(
            controller.load_preset_bundle,
            [preset, annotation_timestamp],
            [
                generated_state,
                effective,
                semantic,
                source_status,
                current_source,
                annotation_variant,
                run_variant,
                annotation_asset_path,
                annotation_metadata,
                preset_media_candidates,
                media,
                task_target,
                annotation_canvas,
                annotation_state,
                annotation_status,
                current_preset_state,
                annotation_points,
                run_media_summary,
                variant_choice,
            ],
        ).then(
            _unresolved_of,
            semantic,
            unresolved,
        ).then(
            controller.preferred_executable_variant,
            [effective, annotation_variant],
            annotation_variant,
        ).then(
            _sync_run_variant,
            [effective, annotation_variant],
            run_variant,
        ).then(
            controller.editor_variant_for_media,
            annotation_variant,
            variant_choice,
        ).then(
            _slot_updates,
            [effective, annotation_variant],
            [annotation_slot, configuration_slots_view, annotation_overview, annotation_wizard],
        ).then(
            _temporal_summary,
            [effective, annotation_variant],
            event_rule_summary,
        ).then(
            _configuration_guidance,
            [effective, annotation_variant],
            configuration_guidance,
        )
        saved_button.click(
            controller.load_saved_skill,
            saved,
            [generated_state, effective, semantic, source_status, current_source],
        ).then(_unresolved_of, semantic, unresolved).then(
            controller.preferred_executable_variant,
            [effective, annotation_variant],
            annotation_variant,
        ).then(
            _sync_run_variant,
            [effective, annotation_variant],
            run_variant,
        ).then(
            controller.editor_variant_for_media,
            annotation_variant,
            variant_choice,
        ).then(
            _slot_updates,
            [effective, annotation_variant],
            [annotation_slot, configuration_slots_view, annotation_overview, annotation_wizard],
        ).then(
            _temporal_summary,
            [effective, annotation_variant],
            event_rule_summary,
        ).then(
            _configuration_guidance,
            [effective, annotation_variant],
            configuration_guidance,
        )
        delete_button.click(controller.delete_saved_skill, saved, source_status).then(
            lambda: gr.update(choices=controller.saved_skill_choices(), value=None),
            outputs=saved,
        )
        def _read_atomic_updates(
            effective_json, document_json, variant_name, source_mode_value
        ):
            catalog = controller.editor_service.operator_catalog()
            if not effective_json:
                empty_choice = gr.update(choices=[], value=None)
                return (
                    "",
                    "请先在 01 生成或加载技能；这里不会把空状态当作配置错误。",
                    empty_choice,
                    empty_choice,
                    gr.update(
                        choices=[
                            (f"{item['display_name']}（{item['operator']}）", item["operator"])
                            for item in catalog
                        ],
                        value=None,
                    ),
                    empty_choice,
                    empty_choice,
                    empty_choice,
                    "",
                    "[]",
                    empty_choice,
                    [],
                    "[]",
                    catalog,
                    "### 统一规则编排中心（专业模式）\n生成或加载技能后再读取底层原子配置。",
                )
            values = controller.unified_editor_controls(
                effective_json, document_json, variant_name, source_mode_value
            )
            overview = (
                "### 统一规则编排中心（专业模式）\n"
                f"当前注册 {len(catalog)} 种可插拔原子能力；参数覆盖、图结构、业务分支、"
                "EventPattern、待确认条件与结果契约统一保存在下方 V3 文档。"
            )
            return (*values, catalog, overview)

        _unified_editor_outputs = [
            editor_document, unified_status, unified_branch, atomic_node,
            unified_operator, unified_source_node, unified_target_node,
            atomic_parameter, atomic_value, unified_patterns, unified_pending_choice,
            unified_pending, unified_results, atomic_rows, editor_overview,
        ]

        def _record_editor_change(method, editor_json, history, *args):
            updated, status = method(editor_json, *args)
            state = dict(history or {})
            undo = list(state.get("undo", []))
            if updated != editor_json:
                undo.append(editor_json)
            return updated, status, {"undo": undo[-50:], "redo": []}

        def _undo_editor(editor_json, history):
            state = dict(history or {})
            undo, redo = list(state.get("undo", [])), list(state.get("redo", []))
            if not undo:
                return editor_json, "没有可撤销的修改。", state
            previous = undo.pop()
            redo.append(editor_json)
            return previous, "已撤销上一步配置修改。", {"undo": undo, "redo": redo[-50:]}

        def _redo_editor(editor_json, history):
            state = dict(history or {})
            undo, redo = list(state.get("undo", [])), list(state.get("redo", []))
            if not redo:
                return editor_json, "没有可重做的修改。", state
            following = redo.pop()
            undo.append(editor_json)
            return following, "已重做配置修改。", {"undo": undo[-50:], "redo": redo}

        def _restore_generated(
            effective_json, editor_json, history, source_mode_value
        ):
            if not effective_json:
                return editor_json, "请先在 01 生成或加载技能。", dict(history or {})
            restored = controller._dump(
                build_editor_document(
                    SkillPackage.model_validate_json(effective_json),
                    source_type={
                        "自然语言生成": "natural_language",
                        "预置演示技能": "preset",
                        "已保存技能": "legacy",
                    }.get(source_mode_value, "legacy"),
                )
            )
            state = dict(history or {})
            undo = [*state.get("undo", []), editor_json][-50:]
            return restored, "已恢复当前 LLM/已加载运行包生成的配置。", {"undo": undo, "redo": []}

        atomic_read_button.click(
            _read_atomic_updates,
            [effective, editor_document, variant_choice, source_mode],
            _unified_editor_outputs,
        )
        atomic_node.change(
            controller.unified_node_parameters,
            [editor_document, variant_choice, atomic_node],
            [atomic_parameter, atomic_value],
        )
        atomic_parameter.change(
            controller.unified_parameter_value,
            [editor_document, variant_choice, atomic_node, atomic_parameter],
            atomic_value,
        )
        atomic_apply_button.click(
            lambda doc, history, node, parameter, value: _record_editor_change(
                controller.unified_apply_parameter, doc, history, node, parameter, value
            ),
            [editor_document, editor_history, atomic_node, atomic_parameter, atomic_value],
            [editor_document, atomic_status, editor_history],
        )
        atomic_reset_button.click(
            lambda doc, history, node, parameter: _record_editor_change(
                controller.unified_reset_parameter, doc, history, node, parameter
            ),
            [editor_document, editor_history, atomic_node, atomic_parameter],
            [editor_document, atomic_status, editor_history],
        ).then(
            controller.unified_node_parameters,
            [editor_document, variant_choice, atomic_node],
            [atomic_parameter, atomic_value],
        )
        unified_mutate_button.click(
            lambda doc, history, *args: _record_editor_change(
                controller.unified_mutate_graph, doc, history, *args
            ),
            [
                editor_document, editor_history,
                variant_choice,
                unified_action,
                atomic_node,
                unified_new_node_id,
                unified_operator,
                unified_source_node,
                unified_target_node,
                unified_port,
                unified_branch,
            ],
            [editor_document, unified_status, editor_history],
        ).then(
            _read_atomic_updates,
            [effective, editor_document, variant_choice, source_mode],
            _unified_editor_outputs,
        )
        unified_branch_button.click(
            lambda doc, history, *args: _record_editor_change(
                controller.unified_mutate_branch, doc, history, *args
            ),
            [
                editor_document, editor_history, variant_choice, unified_branch_action,
                unified_branch, unified_new_branch_id, unified_branch_name,
            ],
            [editor_document, unified_status, editor_history],
        ).then(
            _read_atomic_updates,
            [effective, editor_document, variant_choice, source_mode],
            _unified_editor_outputs,
        )
        unified_recipe_button.click(
            lambda doc, history, media_type, recipe_id, branch_id: _record_editor_change(
                controller.unified_insert_recipe,
                doc,
                history,
                media_type,
                recipe_id,
                branch_id,
            ),
            [editor_document, editor_history, variant_choice, unified_recipe, unified_branch],
            [editor_document, unified_status, editor_history],
        ).then(
            _read_atomic_updates,
            [effective, editor_document, variant_choice, source_mode],
            _unified_editor_outputs,
        )
        unified_patterns_button.click(
            lambda doc, history, patterns: _record_editor_change(
                controller.unified_apply_patterns, doc, history, patterns
            ),
            [editor_document, editor_history, unified_patterns],
            [editor_document, unified_status, editor_history],
        )
        unified_pending_button.click(
            lambda doc, history, decision, value: _record_editor_change(
                controller.unified_resolve_pending, doc, history, decision, value
            ),
            [editor_document, editor_history, unified_pending_choice, unified_pending_value],
            [editor_document, unified_status, editor_history],
        ).then(
            _read_atomic_updates,
            [effective, editor_document, variant_choice, source_mode],
            _unified_editor_outputs,
        )
        unified_results_button.click(
            lambda doc, history, results: _record_editor_change(
                controller.unified_apply_results, doc, history, results
            ),
            [editor_document, editor_history, unified_results],
            [editor_document, unified_status, editor_history],
        )
        for button, handler in (
            (unified_undo_button, _undo_editor),
            (unified_redo_button, _redo_editor),
        ):
            button.click(
                handler,
                [editor_document, editor_history],
                [editor_document, unified_status, editor_history],
            ).then(
                _read_atomic_updates,
                [effective, editor_document, variant_choice, source_mode],
                _unified_editor_outputs,
            )
        unified_restore_button.click(
            _restore_generated,
            [effective, editor_document, editor_history, source_mode],
            [editor_document, unified_status, editor_history],
        ).then(
            _read_atomic_updates,
            [effective, editor_document, variant_choice, source_mode],
            _unified_editor_outputs,
        )
        unified_apply_button.click(
            controller.unified_validate_apply,
            editor_document,
            [editor_document, effective, unified_status],
        )
        validate_button.click(controller.validate_json, effective, validation)
        diff_button.click(controller.diff, [generated_state, effective], diff_output)
        save_button.click(
            controller.save_skill_bundle,
            [effective, editor_document, save_id, save_display],
            saved_path,
        ).then(
            lambda: gr.update(choices=controller.saved_skill_choices()),
            outputs=saved,
        )
        asset_save_button.click(
            controller.save_skill_bundle,
            [effective, editor_document, asset_save_id, asset_save_display],
            asset_save_path,
        ).then(
            lambda path: f"已保存当前 Effective SkillPackage：{path}",
            asset_save_path,
            asset_status,
        ).then(
            _refresh_saved_choices,
            outputs=[saved, asset_saved],
        )
        asset_load_button.click(
            _load_asset,
            asset_saved,
            [
                generated_state,
                effective,
                semantic,
                source_status,
                current_source,
                task_target,
            ],
        ).then(
            lambda status: status,
            source_status,
            asset_status,
        ).then(
            _unresolved_of,
            semantic,
            unresolved,
        ).then(
            controller.preferred_executable_variant,
            [effective, annotation_variant],
            annotation_variant,
        ).then(
            _sync_run_variant,
            [effective, annotation_variant],
            run_variant,
        ).then(
            controller.editor_variant_for_media,
            annotation_variant,
            variant_choice,
        ).then(
            _slot_updates,
            [effective, annotation_variant],
            [annotation_slot, configuration_slots_view, annotation_overview, annotation_wizard],
        ).then(
            _temporal_summary,
            [effective, annotation_variant],
            event_rule_summary,
        ).then(
            _configuration_guidance,
            [effective, annotation_variant],
            configuration_guidance,
        )
        asset_delete_button.click(
            controller.delete_saved_skill,
            asset_saved,
            asset_status,
        ).then(
            _refresh_saved_choices,
            outputs=[saved, asset_saved],
        )
        def _apply_feedback(effective_json):
            result = controller.validate_json(effective_json)
            return result, result

        def _sync_field_visibility(resize_m, sample_m, tile_on, size_m, fps_m):
            return (
                gr.update(visible=resize_m == "long_side"),
                gr.update(visible=resize_m in ("contain", "stretch")),
                gr.update(visible=resize_m in ("contain", "stretch")),
                gr.update(visible=sample_m == "fps"),
                gr.update(visible=sample_m == "interval"),
                gr.update(visible=sample_m == "frame_step"),
                gr.update(visible=bool(tile_on)),
                gr.update(visible=size_m == "fixed"),
                gr.update(visible=size_m == "fixed"),
                gr.update(visible=fps_m == "fixed"),
            )

        _visibility_inputs = [
            resize_mode, sample_mode, tile_enabled, output_size_mode, output_fps_mode,
        ]
        _visibility_outputs = [
            long_side, resize_width, resize_height,
            sample_fps, interval_seconds, frame_step,
            tile_options, output_width, output_height, output_fps,
        ]
        resize_mode.change(
            lambda m: (
                gr.update(visible=m == "long_side"),
                gr.update(visible=m in ("contain", "stretch")),
                gr.update(visible=m in ("contain", "stretch")),
            ),
            resize_mode,
            [long_side, resize_width, resize_height],
        )
        sample_mode.change(
            lambda m: (
                gr.update(visible=m == "fps"),
                gr.update(visible=m == "interval"),
                gr.update(visible=m == "frame_step"),
            ),
            sample_mode,
            [sample_fps, interval_seconds, frame_step],
        )
        tile_enabled.change(
            lambda on: gr.update(visible=bool(on)), tile_enabled, tile_options
        )
        output_size_mode.change(
            lambda m: (gr.update(visible=m == "fixed"),) * 2,
            output_size_mode,
            [output_width, output_height],
        )
        output_fps_mode.change(
            lambda m: gr.update(visible=m == "fixed"), output_fps_mode, output_fps
        )

        def _load_variant_editor(effective_json, variant_name):
            dump, status = controller.select_variant(effective_json, variant_name)
            return gr.update(value=dump, visible=True), status

        load_variant_button.click(
            _load_variant_editor,
            [effective, variant_choice],
            [variant_editor, variant_status],
        )
        def _read_execution_updates(effective_json, variant_name):
            media_type = "video" if variant_name.startswith("video") else "image"
            values = controller.read_execution_controls(effective_json, media_type)
            if values is None:
                return (
                    *(gr.skip() for _ in range(20)),
                    "请先生成或加载技能，再读取当前参数。",
                )
            sample_values = tuple(
                values.get(name, gr.skip())
                for name in (
                    "sample_mode", "fps", "interval_seconds", "frame_step",
                    "start_seconds", "end_seconds", "max_frames",
                )
            )
            return (
                values["resize_mode"], values["long_side"], values["width"],
                values["height"], values["interpolation"],
                values["tile_enabled"], values["tile_width"],
                values["tile_height"], values["overlap_x"],
                values["overlap_y"], values["include_full_frame"],
                values["dedup_metric"], values["dedup_threshold"],
                *sample_values,
                "已读取当前 Effective 配置的真实参数。",
            )

        read_execution_button.click(
            _read_execution_updates,
            [effective, variant_choice],
            [
                resize_mode, long_side, resize_width, resize_height,
                resize_interpolation, tile_enabled, tile_width, tile_height,
                overlap_x, overlap_y, include_full, dedup_metric,
                dedup_threshold, sample_mode, sample_fps, interval_seconds,
                frame_step, start_seconds, end_seconds, max_frames, config_status,
            ],
        ).then(
            _sync_field_visibility, _visibility_inputs, _visibility_outputs
        )

        def _read_event_rule_updates(
            effective_json, variant_name, selected_id=None
        ):
            empty = (
                gr.update(choices=[], value=None), "",
                gr.update(choices=[], value=[]), gr.update(choices=[], value=None), gr.update(choices=[], value=None),
                ">=", 0.0, gr.update(visible=False),
                gr.update(choices=[], value=None), ">=", 0.0, "all", 1.0,
                0.5, "once", "", "当前流程没有可编辑事件；普通检测无需配置事件规则。",
                gr.update(value=[], visible=False),
            )
            if not effective_json:
                return empty
            media_type = "video" if variant_name.startswith("video") else "image"
            controls = controller.read_event_rule_controls(effective_json, media_type)
            if not controls:
                return empty
            selected = next(
                (item for item in controls if item["event_id"] == selected_id),
                controls[0],
            )
            comparisons = selected["comparisons"]
            first = comparisons[0] if comparisons else None
            second = comparisons[1] if len(comparisons) > 1 else None
            choices = [
                (f"{item['event_label']}（{item['event_id']}）", item["event_id"])
                for item in controls
            ]
            comparison_choices = []
            for item in comparisons:
                region_choices = item.get("region_choices", [])
                if region_choices:
                    comparison_choices.extend(
                        (
                            f"{item['measure']} · 区域{region_index}：{region['label']} ({region['id']})",
                            f"{item['node_id']}@@{region['id']}",
                        )
                        for region_index, region in enumerate(region_choices, start=1)
                    )
                    comparison_choices.append(
                        (
                            f"{item['measure']} · 全部手工标注区域",
                            item["node_id"],
                        )
                    )
                else:
                    comparison_choices.append((item["measure"], item["node_id"]))

            def _comparison_selection(item):
                if not item:
                    return None
                region_id = item.get("region_id")
                return (
                    f"{item['node_id']}@@{region_id}"
                    if region_id is not None
                    else item["node_id"]
                )
            scope_labels = {
                "global": "全画面",
                "region": "每个命名区域（在“02 标注”绘制或修改区域）",
                "track": "每条目标轨迹",
            }
            more_conditions = max(0, len(comparisons) - 2)
            suffix = (
                f"；另有 {more_conditions} 条条件保留原值，可在高级 JSON 中编辑"
                if more_conditions else ""
            )
            status = (
                f"当前规则：{selected['event_label']}；范围为 {selected['scope_label']}；"
                f"共 {len(comparisons)} 条可比较条件{suffix}。"
            )
            if selected["condition_kind"] == "direction":
                status = (
                    f"当前规则：{selected['event_label']}；{selected['condition_summary']}；"
                    "这是方向/空间关系，不是数量或速度比较。"
                    "请到“02 标注”配置车道区域和参考方向箭头；"
                    f"持续 {selected['seconds']:g} 秒后触发。"
                )
            elif selected["condition_kind"] == "state":
                state = selected.get("state_condition") or {}
                status = (
                    f"当前规则：{selected['event_label']}；{selected['condition_summary']}；"
                    f"状态原子：{state.get('label', state.get('node_id', '状态条件'))}。"
                    "系统按逐帧目标关联/状态结果判断，不需要数值比较卡；"
                    f"持续 {selected['seconds']:g} 秒后触发。"
                )
            return (
                gr.update(choices=choices, value=selected["event_id"]),
                selected["category_node_id"] or "",
                gr.update(
                    choices=selected["categories"],
                    value=selected["selected_categories"],
                ),
                gr.update(
                    choices=[
                        (scope_labels[scope], scope)
                        for scope in selected["scope_choices"]
                    ],
                    value=selected["scope"],
                ),
                gr.update(
                    choices=comparison_choices,
                    value=_comparison_selection(first),
                    interactive=first is not None,
                ),
                first["operator"] if first else ">=",
                first["value"] if first else 0.0,
                gr.update(visible=second is not None),
                gr.update(
                    choices=comparison_choices,
                    value=_comparison_selection(second),
                    interactive=second is not None,
                ),
                second["operator"] if second else ">=",
                second["value"] if second else 0.0,
                gr.update(
                    value=selected["logic"], interactive=len(comparisons) > 1
                ),
                selected["seconds"],
                selected["gap_tolerance_seconds"],
                selected["trigger_mode"],
                selected["event_label"],
                status,
                gr.update(
                    value=[],
                    visible=False,
                ),
            )

        def _read_selected_event_rule_values(
            effective_json, variant_name, selected_id=None
        ):
            values = _read_event_rule_updates(
                effective_json, variant_name, selected_id
            )
            return values[1:]

        event_rule_outputs = [
            event_rule_event, event_rule_category_node, event_rule_categories,
            event_rule_scope, event_rule_condition_1, event_rule_operator_1,
            event_rule_value_1, event_rule_condition_2_row,
            event_rule_condition_2, event_rule_operator_2, event_rule_value_2,
            event_rule_logic, event_rule_seconds, event_rule_gap,
            event_rule_trigger, event_rule_alert, event_rule_status,
            event_rule_region_overrides,
        ]

        event_rule_card_outputs = [event_rule_card_state]
        for card in event_rule_cards:
            event_rule_card_outputs.extend([
                card["group"], card["enabled"], card["source"],
                card["categories"], card["operator"], card["value"],
            ])

        def _card_selection(item):
            if item is None:
                return None
            region_id = item.get("region_id")
            return (
                f"{item['source_template_id']}@@{region_id}"
                if region_id is not None else item["source_template_id"]
            )

        def _event_card_updates(effective_json, variant_name, selected_id=None):
            if not effective_json:
                empty = [json.dumps([False] * len(event_rule_cards))]
                for _ in event_rule_cards:
                    empty.extend([
                        gr.update(visible=False), False,
                        gr.update(choices=[], value=None),
                        gr.update(choices=[], value=[]), ">=", 0.0,
                    ])
                return tuple(empty)
            media_type = "video" if variant_name.startswith("video") else "image"
            controls = controller.read_event_rule_controls(effective_json, media_type)
            selected = next(
                (item for item in controls if item["event_id"] == selected_id),
                controls[0] if controls else None,
            )
            if selected is None or selected["condition_kind"] != "comparison":
                return _event_card_updates("", variant_name)
            canonical_source_ids: dict[tuple[str, tuple[str, ...]], str] = {}
            source_items = []
            for item in selected["comparisons"]:
                fixed_region = item.get("fixed_region") or {}
                source_key = (
                    item["measure"],
                    tuple(region["id"] for region in item.get("region_choices", [])),
                    fixed_region.get("id"),
                )
                canonical_id = canonical_source_ids.setdefault(source_key, item["node_id"])
                item["source_template_id"] = canonical_id
                if canonical_id == item["node_id"]:
                    source_items.append(item)

            choices = []
            for item in source_items:
                regions = item.get("region_choices", [])
                fixed_region = item.get("fixed_region")
                if fixed_region:
                    choices.append((
                        f"{item['measure']} · {fixed_region['label']} ({fixed_region['id']})",
                        item["source_template_id"],
                    ))
                elif regions:
                    # A regional count can be converted into the separate
                    # measure.count atom.  Other regional measures (such as
                    # region speed) do not yet have a compatible global atom,
                    # so never present an option that would be misleading.
                    if item["measure"] == "每个命名区域内目标数量":
                        choices.append((
                            "全画面目标数量",
                            f"{item['source_template_id']}@@__global__",
                        ))
                    choices.extend([
                        (
                            f"{item['measure']} · 区域{position}：{region['label']} ({region['id']})",
                            f"{item['source_template_id']}@@{region['id']}",
                        )
                        for position, region in enumerate(regions, start=1)
                    ])
                    choices.append((
                        f"{item['measure']} · 全部手工标注区域",
                        item["source_template_id"],
                    ))
                else:
                    choices.append((
                        f"{item['measure']} · 全部手工标注区域（请先在“02 标注”绘制）",
                        item["source_template_id"],
                    ))
            comparisons = selected["comparisons"]
            values = [json.dumps([
                index < len(comparisons) for index in range(len(event_rule_cards))
            ])]
            default = comparisons[0] if comparisons else None
            for index, _ in enumerate(event_rule_cards):
                item = comparisons[index] if index < len(comparisons) else default
                active = item is not None and index < len(comparisons)
                values.extend([
                    gr.update(visible=active), active,
                    gr.update(choices=choices, value=_card_selection(item), interactive=item is not None),
                    gr.update(choices=selected["categories"], value=selected["selected_categories"]),
                    item["operator"] if item else ">=",
                    item["value"] if item else 0.0,
                ])
            return tuple(values)

        association_card_outputs = [
            event_rule_association_group,
            event_rule_association,
            event_rule_association_subject,
            event_rule_association_object,
            event_rule_association_threshold,
        ]

        def _association_card_updates(
            effective_json, variant_name, event_id=None, association_id=None
        ):
            empty = (
                gr.update(visible=False),
                gr.update(choices=[], value=None),
                gr.update(choices=[], value=None),
                gr.update(choices=[], value=None),
                0.3,
            )
            if not effective_json:
                return empty
            media_type = "video" if variant_name.startswith("video") else "image"
            controls = controller.read_event_rule_controls(effective_json, media_type)
            event = next(
                (item for item in controls if item["event_id"] == event_id),
                controls[0] if controls else None,
            )
            associations = (event or {}).get("associations", [])
            if not associations:
                return empty
            selected = next(
                (item for item in associations if item["node_id"] == association_id),
                associations[0],
            )
            association_choices = [
                (f"{item['label']}（{item['node_id']}）", item["node_id"])
                for item in associations
            ]
            candidate_choices = [
                (f"{item['label']}（{item['key']}）", item["key"])
                for item in selected["candidates"]
            ]
            return (
                gr.update(visible=True),
                gr.update(choices=association_choices, value=selected["node_id"]),
                gr.update(choices=candidate_choices, value=selected["subject"]["key"]),
                gr.update(choices=candidate_choices, value=selected["object"]["key"]),
                selected["threshold"],
            )

        def _add_event_card(card_state):
            try:
                state = json.loads(card_state or "[]")
            except (TypeError, json.JSONDecodeError):
                state = []
            state = [bool(state[index]) if index < len(state) else False
                     for index in range(len(event_rule_cards))]
            try:
                state[state.index(False)] = True
            except ValueError as exc:
                raise gr.Error("单个事件最多配置 6 个条件") from exc
            return [json.dumps(state), *[gr.update(visible=active) for active in state]]

        def _remove_event_card(index, card_state):
            try:
                state = json.loads(card_state or "[]")
            except (TypeError, json.JSONDecodeError):
                state = []
            state = [bool(state[position]) if position < len(state) else False
                     for position in range(len(event_rule_cards))]
            state[index] = False
            return [json.dumps(state), *[gr.update(visible=active) for active in state]]

        event_rule_add_condition.click(
            _add_event_card,
            event_rule_card_state,
            [event_rule_card_state, *[card["group"] for card in event_rule_cards]],
        )
        for card_index, card in enumerate(event_rule_cards):
            card["delete"].click(
                lambda state, index=card_index: _remove_event_card(index, state),
                event_rule_card_state,
                [event_rule_card_state, *[item["group"] for item in event_rule_cards]],
            )
        event_rule_read_button.click(
            _read_event_rule_updates,
            [effective, variant_choice, event_rule_event],
            event_rule_outputs,
        ).then(
            _event_card_updates,
            [effective, variant_choice, event_rule_event],
            event_rule_card_outputs,
        ).then(
            _association_card_updates,
            [effective, variant_choice, event_rule_event],
            association_card_outputs,
        )
        event_rule_event.input(
            _read_selected_event_rule_values,
            [effective, variant_choice, event_rule_event],
            event_rule_outputs[1:],
        ).then(
            _event_card_updates,
            [effective, variant_choice, event_rule_event],
            event_rule_card_outputs,
        ).then(
            _association_card_updates,
            [effective, variant_choice, event_rule_event],
            association_card_outputs,
        )
        event_rule_association.input(
            _association_card_updates,
            [
                effective, variant_choice, event_rule_event,
                event_rule_association,
            ],
            association_card_outputs,
        )

        def _region_overrides_from_table(
            effective_json, variant_name, event_id, comparison_ids, table
        ):
            controls = controller.read_event_rule_controls(
                effective_json,
                "video" if variant_name.startswith("video") else "image",
            )
            selected = next(
                (item for item in controls if item["event_id"] == event_id),
                None,
            )
            if selected is None:
                raise gr.Error("找不到要编辑的事件规则")
            display_to_id = {
                f"{item['label']} ({item['id']})": item["id"]
                for item in selected.get("regions", [])
            }
            display_to_id.update({
                item["id"]: item["id"] for item in selected.get("regions", [])
            })
            rows = table.tolist() if hasattr(table, "tolist") else (table or [])
            overrides = {}
            operator_overrides = {}
            uses_operator_columns = any(
                len(row) >= 1 + 2 * len(comparison_ids)
                for row in rows if row
            )
            for row in rows:
                if not row or row[0] is None:
                    continue
                region_id = display_to_id.get(str(row[0]).strip())
                if region_id is None:
                    raise gr.Error("区域行必须保留已标注区域名称，不能自行修改")
                values = {}
                operators = {}
                for index, comparison_id in enumerate(comparison_ids, start=1):
                    if uses_operator_columns:
                        operator_index = 1 + 2 * (index - 1)
                        value_index = operator_index + 1
                        operator = row[operator_index] if operator_index < len(row) else None
                        value = row[value_index] if value_index < len(row) else None
                    else:
                        operator = None
                        value = row[index] if index < len(row) else None
                    if operator is not None and str(operator).strip():
                        normalized = str(operator).strip()
                        if normalized not in {">", ">=", "=", "<=", "<", "==", "!="}:
                            raise gr.Error("区域专属比较符必须是 >、>=、=、<=、<、== 或 !=")
                        operators[comparison_id] = normalized
                    if value is None or str(value).strip().lower() in {"", "nan"}:
                        continue
                    try:
                        values[comparison_id] = float(value)
                    except (TypeError, ValueError) as exc:
                        raise gr.Error("区域覆盖阈值必须是数字") from exc
                if values:
                    overrides[region_id] = values
                if operators:
                    operator_overrides[region_id] = operators
            return overrides, operator_overrides

        def _apply_event_rule(
            effective_json, variant_name, event_id, category_node_id, categories,
            scope, first_id, first_operator, first_value, second_id,
            second_operator, second_value, logic_mode, seconds, gap,
            trigger_mode, alert_label, region_overrides_table,
        ):
            def _decode_selection(selection):
                if not selection:
                    return None, None
                if "@@" not in str(selection):
                    return str(selection), None
                comparison_id, region_id = str(selection).split("@@", 1)
                return comparison_id, region_id

            first_comparison_id, first_region_id = _decode_selection(first_id)
            second_comparison_id, second_region_id = _decode_selection(second_id)
            selected_comparisons = [
                (first_comparison_id, first_region_id),
                (second_comparison_id, second_region_id),
            ]
            selected_comparisons = [item for item in selected_comparisons if item[0]]
            comparison_ids = [item[0] for item in selected_comparisons]
            region_bindings = [item[1] for item in selected_comparisons]
            comparison_operators = [first_operator]
            comparison_values = [first_value]
            if second_id:
                comparison_operators.append(second_operator)
                comparison_values.append(second_value)
            region_overrides, region_operator_overrides = _region_overrides_from_table(
                effective_json,
                variant_name,
                event_id,
                comparison_ids,
                region_overrides_table,
            )
            return controller.apply_event_rule_control(
                effective_json,
                variant_name,
                event_id,
                category_node_id or None,
                categories,
                comparison_ids,
                comparison_operators[:len(comparison_ids)],
                comparison_values[:len(comparison_ids)],
                logic_mode,
                seconds,
                gap,
                trigger_mode,
                alert_label,
                scope=scope,
                region_overrides=region_overrides,
                region_operator_overrides=region_operator_overrides,
                region_bindings=region_bindings,
            )

        event_rule_card_inputs = []
        for card in event_rule_cards:
            event_rule_card_inputs.extend([
                card["enabled"], card["source"], card["categories"],
                card["operator"], card["value"],
            ])

        def _apply_event_rule_cards(
            effective_json, variant_name, event_id, card_state, logic_mode,
            seconds, gap, trigger_mode, alert_label, association_id,
            association_subject, association_object, association_threshold,
            *card_values,
        ):
            try:
                state = json.loads(card_state or "[]")
            except (TypeError, json.JSONDecodeError):
                state = []
            cards = []
            for index, active in enumerate(state[:len(event_rule_cards)]):
                offset = index * 5
                enabled, source, categories, operator, value = card_values[offset:offset + 5]
                if not active or not enabled:
                    continue
                if not source:
                    raise gr.Error(f"条件 {index + 1} 需要选择区域与统计量")
                if "@@" in str(source):
                    template_id, region_id = str(source).split("@@", 1)
                else:
                    template_id, region_id = str(source), None
                cards.append({
                    "template_id": template_id,
                    "region_id": region_id,
                    "categories": list(categories or []),
                    "operator": operator,
                    "value": value,
                })
            updated = controller.apply_event_rule_cards(
                effective_json,
                variant_name,
                event_id,
                cards,
                logic_mode,
                seconds,
                gap,
                trigger_mode,
                alert_label,
            )
            if not association_id:
                return updated
            media_type = "video" if variant_name.startswith("video") else "image"
            return controller.apply_event_association(
                updated,
                media_type,
                event_id,
                association_id,
                association_subject,
                association_object,
                association_threshold,
            )

        # Retains the stable internal API used by saved UI-client integrations.
        # It is intentionally not connected to a visible control.
        event_rule_legacy_apply_probe.click(
            _apply_event_rule,
            [
                effective, variant_choice, event_rule_event, event_rule_category_node,
                event_rule_categories, event_rule_scope, event_rule_condition_1,
                event_rule_operator_1, event_rule_value_1, event_rule_condition_2,
                event_rule_operator_2, event_rule_value_2, event_rule_logic,
                event_rule_seconds, event_rule_gap, event_rule_trigger,
                event_rule_alert, event_rule_region_overrides,
            ],
            effective,
        )

        event_rule_apply_button.click(
            _apply_event_rule_cards,
            [
                effective, variant_choice, event_rule_event, event_rule_card_state,
                event_rule_logic, event_rule_seconds, event_rule_gap,
                event_rule_trigger, event_rule_alert, event_rule_association,
                event_rule_association_subject, event_rule_association_object,
                event_rule_association_threshold, *event_rule_card_inputs,
            ],
            effective,
        ).then(_apply_feedback, effective, [config_status, validation]).then(
            _read_event_rule_updates,
            [effective, variant_choice, event_rule_event],
            event_rule_outputs,
        ).then(
            _event_card_updates,
            [effective, variant_choice, event_rule_event],
            event_rule_card_outputs,
        ).then(
            _association_card_updates,
            [effective, variant_choice, event_rule_event],
            association_card_outputs,
        ).then(
            lambda effective_json, variant_name: controller.temporal_rules_markdown(
                effective_json,
                "video" if variant_name.startswith("video") else "image",
            ),
            [effective, variant_choice],
            event_rule_summary,
        ).then(
            _slot_updates,
            [effective, annotation_variant],
            [annotation_slot, configuration_slots_view, annotation_overview, annotation_wizard],
        ).then(
            _configuration_guidance,
            [effective, annotation_variant],
            configuration_guidance,
        )
        effective.change(
            _read_event_rule_updates,
            [effective, variant_choice],
            event_rule_outputs,
        ).then(
            _event_card_updates,
            [effective, variant_choice, event_rule_event],
            event_rule_card_outputs,
        ).then(
            _association_card_updates,
            [effective, variant_choice, event_rule_event],
            association_card_outputs,
        ).then(
            _read_atomic_updates,
            [effective, editor_document, variant_choice, source_mode],
            _unified_editor_outputs,
        )
        variant_choice.change(
            _read_event_rule_updates,
            [effective, variant_choice],
            event_rule_outputs,
        ).then(
            _event_card_updates,
            [effective, variant_choice, event_rule_event],
            event_rule_card_outputs,
        ).then(
            _association_card_updates,
            [effective, variant_choice, event_rule_event],
            association_card_outputs,
        )
        variant_choice.change(
            _configuration_guidance,
            [effective, variant_choice],
            configuration_guidance,
        )

        variant_choice.change(
            lambda effective_json, variant_name: controller.temporal_rules_markdown(
                effective_json,
                "video" if variant_name.startswith("video") else "image",
            ),
            [effective, variant_choice],
            event_rule_summary,
        )
        apply_variant_button.click(
            controller.apply_variant_json,
            [effective, variant_choice, variant_editor],
            effective,
        ).then(_apply_feedback, effective, [config_status, validation])

        def _read_context_confirmation(effective_json, variant_name):
            values = controller.context_confirmation_control_values(
                effective_json, variant_name
            )
            if values is None:
                return (
                    *(gr.skip() for _ in range(5)),
                    "请先生成或加载技能，再读取确认配置。",
                )
            return (
                gr.update(
                    choices=values["labels"], value=values["selected_labels"]
                ),
                values["enabled"], values["confirmation_phrases"],
                values["padding_fraction"], values["crop_long_side"],
                values["status"],
            )

        _context_outputs = [
            context_targets, context_enabled, context_phrases, context_padding,
            context_long_side, context_status,
        ]
        context_read_button.click(
            _read_context_confirmation, [effective, variant_choice], _context_outputs
        )
        context_apply_button.click(
            controller.apply_context_confirmation_control,
            [
                effective, variant_choice, context_enabled, context_targets,
                context_phrases, context_padding, context_long_side,
            ],
            effective,
        ).then(_apply_feedback, effective, [config_status, validation]).then(
            _read_context_confirmation, [effective, variant_choice], _context_outputs
        )
        variant_choice.change(
            _read_context_confirmation, [effective, variant_choice], _context_outputs
        )

        def _read_grounding_prompt_updates(
            effective_json, variant_name, selected_node_id=None
        ):
            media_type = "video" if variant_name.startswith("video") else "image"
            controls = controller.grounding_prompt_controls(effective_json, media_type)
            if not controls:
                return (
                    gr.update(choices=[], value=None),
                    "",
                    "当前 variant 没有可编辑的 Rex 模型检测节点。",
                )
            selected = next(
                (item for item in controls if item["node_id"] == selected_node_id),
                controls[0],
            )
            choices = [
                (
                    f"{item['label']}（{item['node_id']}） · "
                    f"{'已覆盖' if item['is_override'] else '默认短语'}",
                    item["node_id"],
                )
                for item in controls
            ]
            status = (
                f"当前编辑 {selected['label']}（{selected['node_id']}）。"
                + (
                    "已使用自定义视觉查询；" if selected["is_override"]
                    else "当前为 targets 自动生成的默认短语；"
                )
                + "系统运行时仍会追加固定的框坐标输出协议。"
            )
            return (
                gr.update(choices=choices, value=selected["node_id"]),
                selected["prompt"],
                status,
            )

        _grounding_prompt_outputs = [
            grounding_prompt_node, grounding_prompt_text, grounding_prompt_status,
        ]
        grounding_prompt_read_button.click(
            _read_grounding_prompt_updates,
            [effective, variant_choice, grounding_prompt_node],
            _grounding_prompt_outputs,
        )
        grounding_prompt_node.input(
            _read_grounding_prompt_updates,
            [effective, variant_choice, grounding_prompt_node],
            _grounding_prompt_outputs,
        )
        grounding_prompt_apply_button.click(
            controller.apply_grounding_prompt_control,
            [effective, variant_choice, grounding_prompt_node, grounding_prompt_text],
            effective,
        ).then(_apply_feedback, effective, [config_status, validation]).then(
            _read_grounding_prompt_updates,
            [effective, variant_choice, grounding_prompt_node],
            _grounding_prompt_outputs,
        )
        grounding_prompt_reset_button.click(
            controller.reset_grounding_prompt_control,
            [effective, variant_choice, grounding_prompt_node],
            effective,
        ).then(_apply_feedback, effective, [config_status, validation]).then(
            _read_grounding_prompt_updates,
            [effective, variant_choice, grounding_prompt_node],
            _grounding_prompt_outputs,
        )
        variant_choice.change(
            _read_grounding_prompt_updates,
            [effective, variant_choice, grounding_prompt_node],
            _grounding_prompt_outputs,
        )
        _preprocess_inputs = [
            effective,
            variant_choice,
            resize_mode,
            long_side,
            resize_width,
            resize_height,
            tile_enabled,
            tile_width,
            tile_height,
            overlap_x,
            overlap_y,
            include_full,
            dedup_metric,
            dedup_threshold,
            resize_interpolation,
        ]
        resize_apply_button.click(
            controller.apply_preprocessing,
            _preprocess_inputs,
            effective,
        ).then(_apply_feedback, effective, [config_status, validation])
        preprocess_button.click(
            controller.apply_preprocessing,
            _preprocess_inputs,
            effective,
        ).then(_apply_feedback, effective, [config_status, validation])
        sample_button.click(
            controller.apply_video_sampling,
            [
                effective,
                sample_mode,
                sample_fps,
                interval_seconds,
                frame_step,
                start_seconds,
                end_seconds,
                max_frames,
            ],
            effective,
        ).then(_apply_feedback, effective, [config_status, validation])
        output_config_button.click(
            controller.apply_output_configuration,
            [
                effective,
                variant_choice,
                output_size_mode,
                output_width,
                output_height,
                output_fps_mode,
                output_fps,
            ],
            effective,
        ).then(_apply_feedback, effective, [config_status, validation])
        def _canvas_click(
            effective_json, media_type, path, timestamp, tool, state, evt: gr.SelectData
        ):
            x, y = evt.index
            if tool != "polygon":
                return controller._render_annotation_state(
                    effective_json, media_type, path, timestamp, dict(state or {})
                )
            return controller.add_annotation_point(
                effective_json,
                media_type,
                path,
                timestamp,
                tool,
                state,
                x,
                y,
            )

        def _bind_and_refresh(
            effective_json,
            media_type,
            slot_id,
            tool,
            points_json,
            item_id,
            item_label,
            path,
            timestamp,
            state,
        ):
            updated_json, rows, status = controller.bind_annotation(
                effective_json,
                media_type,
                slot_id,
                tool,
                points_json,
                item_id,
                item_label,
            )
            current = dict(state or {})
            current["tool"] = tool
            current["points"] = []
            preview, current, _, = controller.refresh_annotation_preview(
                updated_json, media_type, path, timestamp, current
            )
            choices, rows = controller.annotation_slots(updated_json, media_type)
            wizard = controller.annotation_wizard_state(updated_json, media_type)
            selected = wizard["current_slot"] or slot_id or (
                choices[0][1] if choices else None
            )
            next_tool, next_item_id, next_item_label = controller.annotation_wizard_defaults(
                updated_json, media_type, selected
            )
            delete_choices = controller.named_item_choices(
                updated_json, media_type, selected
            )
            return (
                updated_json,
                controller.annotation_slots_with_selection(
                    updated_json, media_type, selected
                ),
                status,
                preview,
                current,
                "[]",
                gr.update(choices=choices, value=selected),
                controller.annotation_wizard_markdown(updated_json, media_type),
                gr.update(
                    choices=controller.annotation_tool_choices(
                        updated_json, media_type, selected
                    ),
                    value=next_tool,
                ),
                gr.update(value=next_item_id),
                gr.update(value=next_item_label),
                gr.update(choices=delete_choices, value=None),
            )

        def _add_another_named_region(
            effective_json, media_type, selected_slot, path, timestamp, state
        ):
            package = SkillPackage.model_validate_json(effective_json)
            key = _variant_key(media_type)
            slots = package.variants[key].configuration_slots
            selected = next(
                (slot for slot in slots if slot.slot_id == selected_slot), None
            )
            if selected is None or selected.kind != "region_set":
                selected = next(
                    (slot for slot in slots if slot.kind == "region_set"), None
                )
            if selected is None:
                raise gr.Error("当前技能没有可重复添加的命名区域")
            tool, item_id, item_label, draft = controller.annotation_selection_defaults(
                effective_json, media_type, selected.slot_id
            )
            delete_choices = controller.named_item_choices(
                effective_json, media_type, selected.slot_id
            )
            preview, draft, points_json, _ = controller._render_annotation_state(
                effective_json, media_type, path, timestamp, draft
            )
            return (
                gr.update(value=selected.slot_id),
                gr.update(
                    choices=controller.annotation_tool_choices(
                        effective_json, media_type, selected.slot_id
                    ),
                    value=tool,
                ),
                gr.update(value=item_id),
                gr.update(value=item_label),
                preview,
                draft,
                points_json,
                f"请在画布上绘制 `{item_label}`，然后保存并继续。",
                gr.update(choices=delete_choices, value=None),
                controller.annotation_slots_with_selection(
                    effective_json, media_type, selected.slot_id
                ),
            )

        def _select_annotation_slot(
            effective_json, media_type, slot_id, path, timestamp, state
        ):
            if not effective_json:
                return (
                    gr.update(choices=["rectangle", "polygon"], value="rectangle"),
                    gr.update(value=""),
                    gr.update(value=""),
                    gr.update(choices=[], value=None),
                    gr.update(value=None),
                    dict(state or {}),
                    "[]",
                    "请先加载技能和任务媒体，再开始标注。",
                    [],
                )
            tool, item_id, item_label, draft = controller.annotation_selection_defaults(
                effective_json, media_type, slot_id, state
            )
            if not effective_json or not path:
                return (
                    gr.update(choices=["rectangle", "polygon"], value=tool),
                    gr.update(value=item_id),
                    gr.update(value=item_label),
                    gr.update(choices=[], value=None),
                    gr.update(value=None),
                    draft,
                    "[]",
                    "请先加载技能和任务媒体，再开始标注。",
                    [],
                )
            preview, draft, points_json, _ = controller._render_annotation_state(
                effective_json, media_type, path, timestamp, draft
            )
            return (
                gr.update(
                    choices=controller.annotation_tool_choices(
                        effective_json, media_type, slot_id
                    ),
                    value=tool,
                ),
                gr.update(value=item_id),
                gr.update(value=item_label),
                gr.update(
                    choices=controller.named_item_choices(
                        effective_json, media_type, slot_id
                    ),
                    value=None,
                ),
                preview,
                draft,
                points_json,
                f"已切换到 `{slot_id}`；请重新绘制后再保存。",
                controller.annotation_slots_with_selection(
                    effective_json, media_type, slot_id
                ),
            )

        def _change_annotation_tool(
            effective_json, media_type, slot_id, path, timestamp, tool, state
        ):
            if not effective_json:
                selected_tool = tool or "rectangle"
                return (
                    gr.update(value=slot_id),
                    gr.update(
                        choices=["rectangle", "polygon"],
                        value=selected_tool,
                    ),
                    gr.update(value=""),
                    gr.update(value=""),
                    gr.update(choices=[], value=None),
                    gr.update(),
                    dict(state or {}),
                    "[]",
                    "请先加载技能和任务媒体，再开始标注。",
                    _tool_hints.get(selected_tool, _tool_hints["rectangle"]),
                    [],
                )
            (
                target_slot_id,
                selected_tool,
                item_id,
                item_label,
                draft,
            ) = controller.annotation_tool_selection_defaults(
                effective_json, media_type, slot_id, tool
            )
            if path:
                preview, draft, points_json, status = controller._render_annotation_state(
                    effective_json, media_type, path, timestamp, draft
                )
            else:
                preview = gr.update()
                points_json = "[]"
                status = "已切换标注工具；请加载画布后重新绘制。"
            package = SkillPackage.model_validate_json(effective_json)
            key = _variant_key(media_type)
            target_slot = next(
                (
                    item
                    for item in package.variants[key].configuration_slots
                    if item.slot_id == target_slot_id
                ),
                None,
            )
            if (
                selected_tool == "direction"
                and target_slot is not None
                and target_slot.kind == "direction_set"
                and not item_id
            ):
                status = "请先绘制并保存至少一个命名区域，再绘制方向箭头。"
            return (
                gr.update(value=target_slot_id),
                gr.update(
                    choices=controller.annotation_tool_choices(
                        effective_json, media_type, target_slot_id
                    ),
                    value=selected_tool,
                ),
                gr.update(value=item_id),
                gr.update(value=item_label),
                gr.update(
                    choices=controller.named_item_choices(
                        effective_json, media_type, target_slot_id
                    ),
                    value=None,
                ),
                preview,
                draft,
                points_json,
                status,
                _tool_hints.get(selected_tool, _tool_hints["rectangle"]),
                controller.annotation_slots_with_selection(
                    effective_json, media_type, target_slot_id
                ),
            )

        def _delete_and_refresh(
            effective_json,
            media_type,
            slot_id,
            item_id,
            path,
            timestamp,
            state,
        ):
            updated_json, rows, status = controller.delete_named_annotation(
                effective_json, media_type, slot_id, item_id
            )
            preview, state, _ = controller.refresh_annotation_preview(
                updated_json, media_type, path, timestamp, state
            )
            choices, rows = controller.annotation_slots(updated_json, media_type)
            wizard = controller.annotation_wizard_state(updated_json, media_type)
            selected = wizard["current_slot"] or slot_id or (
                choices[0][1] if choices else None
            )
            delete_choices = controller.named_item_choices(
                updated_json, media_type, slot_id
            )
            return (
                updated_json,
                controller.annotation_slots_with_selection(
                    updated_json, media_type, selected
                ),
                status,
                preview,
                state,
                gr.update(
                    choices=choices,
                    value=selected,
                ),
                controller.annotation_wizard_markdown(updated_json, media_type),
                gr.update(choices=delete_choices, value=None),
            )

        # File.change can race Gradio's internal upload event and dispatch the
        # next dependency with the file payload (observed as apply_preprocessing
        # receiving only [file, timestamp]).  Bind ingestion to the explicit
        # upload lifecycle so selecting a replacement video always reaches the
        # media-ingest callback before downstream controls refresh.
        media.upload(
            _ingest_task_media,
            [media, annotation_timestamp],
            [
                annotation_asset_path,
                annotation_metadata,
                annotation_canvas,
                annotation_state,
                annotation_status,
                annotation_variant,
                run_variant,
                run_media_summary,
                variant_choice,
            ],
        )
        clear_task_media_button.click(
            lambda: (gr.update(value=None), *controller.cleared_task_media_state()),
            None,
            [
                media,
                annotation_asset_path,
                annotation_metadata,
                annotation_canvas,
                annotation_state,
                annotation_status,
                annotation_variant,
                run_variant,
                run_media_summary,
                variant_choice,
            ],
        )
        prepare_annotation_button.click(
            _prepare_annotation,
            [
                effective,
                annotation_variant,
                annotation_asset_path,
                annotation_timestamp,
                annotation_state,
            ],
            [
                annotation_canvas,
                annotation_state,
                configuration_slots_view,
                annotation_slot,
                annotation_overview,
                annotation_wizard,
                annotation_tool,
                annotation_item_id,
                annotation_item_label,
                annotation_delete_target,
            ],
        )
        annotation_canvas.select(
            _canvas_click,
            [
                effective,
                annotation_variant,
                annotation_asset_path,
                annotation_timestamp,
                annotation_tool,
                annotation_state,
            ],
            [annotation_canvas, annotation_state, annotation_points, annotation_status],
        )
        annotation_drag.input(
            controller.set_annotation_drag,
            [
                effective,
                annotation_variant,
                annotation_asset_path,
                annotation_timestamp,
                annotation_tool,
                annotation_state,
                annotation_drag,
            ],
            [annotation_canvas, annotation_state, annotation_points, annotation_status],
        )
        _tool_hints = {
            "rectangle": "**矩形**：在画布上按住左键拖拽，松开后点击「保存并继续下一项」。",
            "polygon": "**多边形**：沿区域边界逐点点击，可用「撤销上一步」修正；点完后点击「保存并继续下一项」。",
            "direction": "**方向箭头**：按住鼠标**顺着车辆正常行驶方向**拖拽（从车尾拖到车头）定义正常方向；与箭头相反的轨迹判为逆行。方向反了可点「反转方向（方向箭头）」。",
        }
        annotation_slot.input(
            _select_annotation_slot,
            [
                effective,
                annotation_variant,
                annotation_slot,
                annotation_asset_path,
                annotation_timestamp,
                annotation_state,
            ],
            [
                annotation_tool,
                annotation_item_id,
                annotation_item_label,
                annotation_delete_target,
                annotation_canvas,
                annotation_state,
                annotation_points,
                annotation_status,
                configuration_slots_view,
            ],
        )
        annotation_tool.change(
            _change_annotation_tool,
            [
                effective,
                annotation_variant,
                annotation_slot,
                annotation_asset_path,
                annotation_timestamp,
                annotation_tool,
                annotation_state,
            ],
            [
                annotation_slot,
                annotation_tool,
                annotation_item_id,
                annotation_item_label,
                annotation_delete_target,
                annotation_canvas,
                annotation_state,
                annotation_points,
                annotation_status,
                tool_hint,
                configuration_slots_view,
            ],
        )
        undo_annotation_button.click(
            controller.undo_annotation_point,
            [
                effective,
                annotation_variant,
                annotation_asset_path,
                annotation_timestamp,
                annotation_state,
            ],
            [annotation_canvas, annotation_state, annotation_points, annotation_status],
        )
        clear_annotation_button.click(
            controller.clear_annotation_points,
            [
                effective,
                annotation_variant,
                annotation_asset_path,
                annotation_timestamp,
                annotation_state,
            ],
            [annotation_canvas, annotation_state, annotation_points, annotation_status],
        )
        reverse_direction_button.click(
            controller.reverse_annotation_direction,
            [
                effective,
                annotation_variant,
                annotation_asset_path,
                annotation_timestamp,
                annotation_state,
            ],
            [annotation_canvas, annotation_state, annotation_points, annotation_status],
        )
        bind_annotation_button.click(
            _bind_and_refresh,
            [
                effective,
                annotation_variant,
                annotation_slot,
                annotation_tool,
                annotation_points,
                annotation_item_id,
                annotation_item_label,
                annotation_asset_path,
                annotation_timestamp,
                annotation_state,
            ],
            [
                effective,
                configuration_slots_view,
                annotation_status,
                annotation_canvas,
                annotation_state,
                annotation_points,
                annotation_slot,
                annotation_wizard,
                annotation_tool,
                annotation_item_id,
                annotation_item_label,
                annotation_delete_target,
            ],
        ).then(
            # Refresh the visible condition cards immediately from the saved
            # annotation JSON.  Do not make this dependent on the legacy rule
            # reader, whose auxiliary updates can be delayed independently.
            _event_card_updates,
            [effective, annotation_variant, event_rule_event],
            event_rule_card_outputs,
        ).then(
            _read_event_rule_updates,
            [effective, annotation_variant, event_rule_event],
            event_rule_outputs,
        ).then(
            _read_atomic_updates,
            [effective, editor_document, annotation_variant, source_mode],
            _unified_editor_outputs,
        )
        add_region_button.click(
            _add_another_named_region,
            [
                effective,
                annotation_variant,
                annotation_slot,
                annotation_asset_path,
                annotation_timestamp,
                annotation_state,
            ],
            [
                annotation_slot,
                annotation_tool,
                annotation_item_id,
                annotation_item_label,
                annotation_canvas,
                annotation_state,
                annotation_points,
                annotation_status,
                annotation_delete_target,
                configuration_slots_view,
            ],
        )
        delete_annotation_button.click(
            _delete_and_refresh,
            [
                effective,
                annotation_variant,
                annotation_slot,
                annotation_delete_target,
                annotation_asset_path,
                annotation_timestamp,
                annotation_state,
            ],
            [
                effective,
                configuration_slots_view,
                annotation_status,
                annotation_canvas,
                annotation_state,
                annotation_slot,
                annotation_wizard,
                annotation_delete_target,
            ],
        ).then(
            _read_event_rule_updates,
            [effective, annotation_variant, event_rule_event],
            event_rule_outputs,
        ).then(
            _event_card_updates,
            [effective, annotation_variant, event_rule_event],
            event_rule_card_outputs,
        ).then(
            _read_atomic_updates,
            [effective, editor_document, annotation_variant, source_mode],
            _unified_editor_outputs,
        )
        set_default_media_button.click(
            controller.set_preset_default_media,
            [current_preset_state, annotation_asset_path],
            [annotation_asset_path, preset_media_candidates, annotation_status],
        )
        inspect_button.click(
            controller.inspect_media,
            [effective, run_variant, media],
            [policy_text, policy_json],
        )
        def _run_with_media_visibility(
            generated, effective_json, editor_json, variant, media_path
        ):
            if editor_json:
                try:
                    document = SkillEditorDocument.model_validate_json(editor_json)
                    package = SkillPackage.model_validate_json(effective_json)
                    if document.skill_template.skill_id == package.skill_id:
                        if document.effective_skill_package is None:
                            raise gr.Error("03 中存在尚未应用的配置草稿，请先完整校验并应用。")
                        if document.validation_report.get("can_run") is False:
                            reasons = [
                                *document.validation_report.get("errors", []),
                                *document.validation_report.get("resource_blockers", []),
                            ]
                            raise gr.Error(
                                "03 配置尚未满足运行条件："
                                + ("；".join(map(str, reasons)) or "请查看待确认项与校验结果")
                            )
                        blockers = [
                            item.prompt
                            for item in document.skill_template.pending_decisions
                            if item.resolution.blocks("run")
                        ]
                        if blockers:
                            raise gr.Error("运行前仍需确认：" + "；".join(blockers))
                except gr.Error:
                    raise
                except Exception as exc:
                    raise gr.Error(f"03 配置文档无效：{exc}") from exc
            img, vid, *rest = controller.run_skill(
                generated, effective_json, variant, media_path
            )
            return (
                gr.update(value=img, visible=img is not None),
                gr.update(value=vid, visible=vid is not None),
                *rest,
            )

        run_button.click(
            _run_with_media_visibility,
            [generated_state, effective, editor_document, run_variant, media],
            [
                annotated_image,
                annotated_video,
                detections,
                tracks,
                events,
                measurements,
                regions,
                directions,
                constraints,
                trace,
                run_dir,
                run_status,
            ],
        )
    return demo


def default_v2_controller() -> V2AppController:
    registry = build_default_registry()
    controller = V2AppController(
        registry=registry,
        package_root=ROOT / "data" / "generated_packages",
        run_root=ROOT / "data" / "runs",
        planner=DeepSeekSemanticPlanner(registry),
        rex=RexGateway(),
    )
    seed_builtin_preset_media(controller.preset_media_catalog, ROOT)
    return controller


if __name__ == "__main__":
    build_v2_app(default_v2_controller()).launch(
        server_name="0.0.0.0",
        server_port=int(os.environ.get("VISION_SKILL_PORT", "6122")),
        show_error=True,
    )


__all__ = [
    "V2AppController",
    "build_v2_app",
    "default_v2_controller",
    "json_object_or_empty",
]

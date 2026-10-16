"""SkillService: extracted V2 responsibilities, preserving public method signatures."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path

from application.v2.skill_assets import (
    load_saved_document,
    parse_saved_selection,
    save_complete_asset,
)
from application.v2.support import MEDIA_CHOICES, ROOT, ApplicationError, _variant_key
from core.business_rule_draft import (
    BusinessDraftError,
    apply_business_rule_draft,
)
from core.editor_generation import build_editor_document
from core.editor_migrations import migrate_editor_document
from core.migration import migrate_v1_spec
from core.persistence import PackageStore, SkillDocumentStore
from core.schema import SkillPackage, VisualSkillSpec
from core.validator import validate_skill_package


class SkillService:
    def preset_names(self) -> list[str]:
        return [path.stem for path in sorted(self.preset_root.glob("P*.json"))]

    def preset_default_media(self, preset_name: str, media_type: str):
        if not preset_name:
            raise ApplicationError("请选择预置演示技能")
        key = _variant_key(media_type)
        asset = self.preset_media_catalog.get_default(preset_name, key)
        if asset is None:
            raise ApplicationError(f"{preset_name} 尚未配置 {key} 默认素材")
        candidates = self.preset_media_catalog.list_candidates(preset_name, key)
        return (
            asset.stored_path,
            key,
            asdict(asset),
            candidates,
            f"✅ 已加载 {preset_name} 的 {key} 默认素材：{asset.original_name}",
        )

    def set_preset_default_media(self, preset_name: str, media_path: str):
        if not preset_name:
            raise ApplicationError("只有当前来源为预置技能时才能设置默认素材")
        if not media_path:
            raise ApplicationError("请先上传或加载素材")
        try:
            asset = self.preset_media_catalog.add_candidate(
                preset_name, media_path, set_default=False
            )
            selected = self.preset_media_catalog.set_default(
                preset_name, asset.media_type, asset.asset_id
            )
        except (ValueError, FileNotFoundError) as exc:
            raise ApplicationError(str(exc)) from exc
        candidates = self.preset_media_catalog.list_candidates(
            preset_name, selected.media_type
        )
        return (
            selected.stored_path,
            candidates,
            f"✅ 已显式设为默认：{preset_name} / {selected.media_type} / {selected.original_name}",
        )

    def saved_skill_choices(self, save_root: str = "") -> list[str]:
        package_store, _ = self._asset_stores(save_root)
        return package_store.list_versions()

    def compile_skill(
        self,
        instruction: str,
        media_choice: str,
        skill_id: str,
        display_name: str,
        previous_effective_json: str = "",
    ):
        if self.planner is None:
            raise ApplicationError("DeepSeek Planner 尚未配置")
        text = instruction.strip()
        identity = skill_id.strip()
        name = display_name.strip()
        if not text or not identity or not name:
            raise ApplicationError("自然语言、技能标识和显示名称都必须填写")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", identity):
            raise ApplicationError(
                "技能标识只能以英文字母开头，由字母、数字、_ 或 - 组成（不能用中文），"
                "例如 loiter_detection；显示名称可以保留中文。"
            )
        requested = MEDIA_CHOICES.get(media_choice)
        if requested is None:
            raise ApplicationError("请选择媒体能力")
        result = self.planner.compile(
            text,
            requested_accept=requested,
            skill_id=identity,
            display_name=name,
            require_business_draft=True,
        )
        if result.package is None:
            detail = "；".join(result.errors) or "语义账本无法无损编译"
            raise ApplicationError(f"需要人工确认：{detail}")
        generated_package = result.package
        package = generated_package
        generated_json = self._dump(generated_package)
        business_draft = getattr(result, "business_draft", None)
        if business_draft is not None:
            try:
                if (
                    media_choice == "图片和视频"
                    and business_draft.get("media_requirement") != "both"
                ):
                    raise BusinessDraftError(
                        "用户明确要求图片和视频，但 LLM 未分别生成两个媒体流程。"
                    )
                editor_document = apply_business_rule_draft(
                    build_editor_document(
                        generated_package, source_type="natural_language"
                    ),
                    business_draft,
                    self.business_capabilities,
                    requested_accept=requested,
                )
                try:
                    editor_document = self.editor_service.apply(editor_document)
                    if editor_document.effective_skill_package is not None:
                        package = editor_document.effective_skill_package
                except Exception as exc:  # noqa: BLE001 — preserved V2 behavior
                    # Keep the reviewable draft when unresolved user input is
                    # the only remaining work. The base package remains the
                    # temporary execution preview and 03 explains the blocker.
                    editor_document.validation_report = {
                        **editor_document.validation_report,
                        "valid": False,
                        "can_run": False,
                        "errors": [str(exc)],
                    }
                self._generated_editor_documents[identity] = editor_document
                self._generated_editor_documents[generated_package.skill_id] = (
                    editor_document
                )
            except (BusinessDraftError, ValueError) as exc:
                raise ApplicationError(
                    f"需要人工确认：业务规则草稿无效：{exc}"
                ) from exc
        package, reused_annotations = self._reuse_matching_manual_annotations(
            package, previous_effective_json
        )
        package_json = self._dump(package)
        semantic_json = self._dump(package.semantic_ir)
        issues = "；".join(issue.message for issue in package.compatibility_issues)
        status = (
            f"✅ Semantic IR + 固定编译器完成；LLM 调用 {result.attempts} 次；"
            f"实际支持 {', '.join(package.input.accept)}。"
        )
        if business_draft is not None:
            status += " 已生成可在 03 审核的业务分支、最终判定和业务输出。"
        if reused_annotations:
            status += f" 已复用当前任务的 {reused_annotations} 个已保存场景标注。"
        if issues:
            status += f"兼容性说明：{issues}"
        source = (
            "### 当前实际执行来源\n"
            f"**自然语言生成** · `{package.skill_id}/v{package.version}` · "
            f"**{package.display_name}**  \n"
            "未使用预置演示技能；运行对象是下方可编辑的 Effective SkillPackage。"
        )
        return generated_json, package_json, semantic_json, status, source

    def load_preset(self, preset_name: str):
        if not preset_name:
            raise ApplicationError("请选择预置演示技能")
        path = self.preset_root / f"{preset_name}.json"
        raw = json.loads(path.read_text("utf-8"))
        if raw.get("schema_version") == "2.0":
            package = SkillPackage.model_validate(raw)
            note = "V2 预置"
        else:
            package = migrate_v1_spec(VisualSkillSpec.model_validate(raw))
            note = "旧预置已显式迁移；语义需重新确认"
        document_path = self.preset_root / "editor_documents" / f"{preset_name}.json"
        if document_path.is_file():
            try:
                document = migrate_editor_document(
                    json.loads(document_path.read_text(encoding="utf-8"))
                )
                if document.skill_template.skill_id != package.skill_id:
                    raise ValueError("技能标识不匹配")
                document.effective_skill_package = package
                self._generated_editor_documents[package.skill_id] = document
            except Exception as exc:
                raise ApplicationError(
                    f"预置业务编排文档无效：{preset_name}：{exc}"
                ) from exc
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
        combined_status = f"{skill_status}；已自动加载 {media_type} 默认素材。"
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

    def load_saved_skill(self, selection: str, save_root: str = ""):
        if not selection or "/v" not in selection:
            raise ApplicationError("请选择已保存技能")
        skill_id, version = parse_saved_selection(selection)
        package_store, document_store = self._asset_stores(save_root)
        try:
            package = package_store.load(skill_id, version)
            if package.skill_id != skill_id or package.version != version:
                raise ValueError("运行包的技能标识或版本与所选保存版本不匹配")
            document, note = load_saved_document(
                package, document_store, self.configuration_service
            )
            # Safe metadata migrations precede the new clean baseline.
            document = self.business_rule_editor.prepare(document)
            document.version = package.version
            document = self.configuration_service.rebase_saved_snapshot(
                document, package
            )
        except (ValueError, OSError, KeyError) as exc:
            raise ApplicationError(
                f"加载已保存技能失败：{exc}；未覆盖当前编辑文档。"
            ) from exc
        # Replace the cache only after the selected pair has fully validated.
        self._generated_editor_documents[package.skill_id] = document
        text = self._dump(package)
        source = (
            "### 当前实际执行来源\n"
            f"**已保存技能** · `{selection}` · **{package.display_name}**  \n"
            "自然语言输入和预置均未参与当前技能。"
        )
        return (
            text,
            text,
            self._dump(package.semantic_ir),
            f"已加载 {selection}；{note}",
            source,
        )

    def save_skill(
        self,
        effective_json: str,
        skill_id: str = "",
        display_name: str = "",
        *,
        store: PackageStore | None = None,
    ) -> str:
        package = SkillPackage.model_validate_json(effective_json)
        errors = validate_skill_package(package, self.registry)
        if errors:
            raise ApplicationError("保存前校验失败：" + "；".join(errors))
        try:
            return str(
                (store or self.package_store).save(
                    package,
                    skill_id=skill_id.strip() or None,
                    display_name=display_name.strip() or None,
                )
            )
        except (ValueError, FileNotFoundError, OSError) as exc:
            raise ApplicationError(str(exc)) from exc

    def asset_save_root(self) -> str:
        """Return the common editable base directory for saved skill assets."""

        return str(self.package_store.root.parent.resolve())

    def _asset_stores(self, save_root: str) -> tuple[PackageStore, SkillDocumentStore]:
        value = str(save_root or "").strip()
        if not value:
            return self.package_store, self.document_store
        root = Path(value).expanduser()
        if not root.is_absolute():
            root = ROOT / root
        root = root.resolve()
        if root.exists() and not root.is_dir():
            raise ApplicationError(f"资产保存目录不是文件夹：{root}")
        return (
            PackageStore(root / "generated_packages"),
            SkillDocumentStore(root / "skill_documents"),
        )

    def save_skill_bundle(
        self,
        effective_json: str,
        editor_json: str,
        skill_id: str = "",
        display_name: str = "",
        save_root: str = "",
    ) -> str:
        package = SkillPackage.model_validate_json(effective_json)
        if editor_json:
            self.configuration_service.require_current(
                self._parse_editor_json(editor_json), package
            )
        document = self._editor_document(effective_json, editor_json)
        if document.effective_skill_package is None:
            raise ApplicationError("03 中存在未应用草稿，不能保存为正式版本")
        package_store, document_store = self._asset_stores(save_root)
        errors = validate_skill_package(package, self.registry)
        if errors:
            raise ApplicationError("保存前校验失败：" + "；".join(errors))
        try:
            package_path, document_path = save_complete_asset(
                package,
                document,
                package_store,
                document_store,
                self.configuration_service,
                skill_id=skill_id,
                display_name=display_name,
            )
        except (ValueError, OSError) as exc:
            raise ApplicationError(f"保存完整技能失败：{exc}") from exc
        return f"运行包：{package_path}\n可编辑文档：{document_path}"

    def delete_saved_skill(self, selection: str, save_root: str = "") -> str:
        if not selection or "/v" not in selection:
            raise ApplicationError("请选择要删除的自定义技能版本")
        skill_id, version = selection.rsplit("/v", 1)
        package_store, document_store = self._asset_stores(save_root)
        package_store.delete(skill_id, int(version))
        document_path = document_store.root / skill_id / f"{int(version)}.json"
        if document_path.exists():
            document_path.unlink()
        return f"已删除自定义技能版本：{selection}；预置技能不受影响。"

    def validate_json(self, effective_json: str) -> str:
        try:
            package = SkillPackage.model_validate_json(effective_json)
            errors = validate_skill_package(package, self.registry)
            return (
                "✅ V2 SkillPackage 校验通过，可执行"
                if not errors
                else ("❌\n" + "\n".join(errors))
            )
        except Exception as exc:  # noqa: BLE001 — preserved V2 behavior
            return "❌\n" + str(exc)

    def editor_document_projection(self, effective_json: str) -> tuple[str, str]:
        """Expose the V3 editor model without replacing the proven V2 runtime."""

        package = SkillPackage.model_validate_json(effective_json)
        document = build_editor_document(package, source_type="legacy")
        requirements = document.skill_template.resource_requirements
        result_specs = document.skill_template.result_specs
        lines = [
            "### 通用组合模型",
            "运行使用只读 Effective SkillPackage；业务编辑层是唯一的 SkillEditorDocument@3.2。",
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

    def restore_default_editor_document(
        self, effective_json: str, source_mode: str = "已保存技能"
    ) -> tuple[str, str]:
        """Restore the immutable generated/loaded business draft for step 03."""

        if not effective_json:
            raise ApplicationError("请先在 01 生成或加载技能。")
        package = SkillPackage.model_validate_json(effective_json)
        source_type = {
            "自然语言生成": "natural_language",
            "预置演示技能": "preset",
            "已保存技能": "legacy",
        }.get(source_mode, "legacy")
        baseline = self._generated_editor_documents.get(package.skill_id)
        if baseline is None:
            baseline = build_editor_document(package, source_type=source_type)
            self._generated_editor_documents[package.skill_id] = baseline.model_copy(
                deep=True
            )
        restored = self._sync_editor_scene_resources(
            baseline.model_copy(deep=True), package
        )
        restored.effective_skill_package = package
        return (
            self._dump(restored),
            "✅ 已还原本次 LLM 生成或加载时的默认事件规则；02 场景标注予以保留。",
        )

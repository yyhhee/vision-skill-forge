"""Pair the complete editable document with its immutable saved runtime version."""

from __future__ import annotations

import re
from pathlib import Path
from threading import RLock

from core.editor_generation import build_editor_document
from core.editor_schema import SkillEditorDocument
from core.persistence import PackageStore, SkillDocumentStore
from core.schema import SkillPackage

from .configuration import ConfigurationService
from .support import ApplicationError

_SAVE_LOCK = RLock()


def parse_saved_selection(selection: str) -> tuple[str, int]:
    """Accept only an explicit, positive saved version with a safe identity."""
    match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_-]*)/v([1-9][0-9]*)", selection or "")
    if match is None:
        raise ApplicationError("请选择有效的已保存技能版本。")
    return match[1], int(match[2])


def load_saved_document(
    package: SkillPackage,
    document_store: SkillDocumentStore,
    configuration: ConfigurationService,
) -> tuple[SkillEditorDocument, str]:
    """Never silently discard an existing but invalid editable document."""
    path = document_store.root / package.skill_id / f"{package.version}.json"
    if not path.exists():
        document = build_editor_document(package, source_type="legacy")
        return (
            document,
            "旧版本只有运行包，已兼容导入；原始业务编排结构无法从运行包完整恢复。",
        )
    try:
        document = document_store.load(package.skill_id, package.version)
        if (
            document.skill_template.skill_id != package.skill_id
            or document.version != package.version
        ):
            raise ValueError("编辑文档的技能标识或保存版本与运行包不匹配")
        embedded = document.effective_skill_package
        if embedded is None or document.validation_report.get("dirty"):
            raise ValueError("编辑文档存在未应用修改，不能作为正式保存版本加载")
        # Historical document saves renamed only the template, leaving the
        # embedded package's old identity/version/name. Only these top-level
        # metadata differences are safe to normalize; runtime content is not.
        content_fields = {"skill_id", "display_name", "version"}
        if embedded.model_dump(
            mode="json", exclude=content_fields
        ) != package.model_dump(mode="json", exclude=content_fields):
            raise ValueError("编辑文档内的执行内容与所选运行包不匹配")
        original = document.model_copy(deep=True)
        original.skill_template.skill_id = embedded.skill_id
        original.skill_template.display_name = embedded.display_name
        configuration.require_current(original, embedded)
        document.skill_template.display_name = package.display_name
        return configuration.rebase_saved_snapshot(
            document, package
        ), "已恢复完整编辑文档，保留条件、编排组、时间、业务输出及场景配置。"
    except (ValueError, OSError, ApplicationError) as exc:
        raise ApplicationError(
            f"已保存技能的编辑文档无效：{exc}；未从运行包重建或覆盖原文档。"
        ) from exc


def save_complete_asset(
    package: SkillPackage,
    document: SkillEditorDocument,
    package_store: PackageStore,
    document_store: SkillDocumentStore,
    configuration: ConfigurationService,
    *,
    skill_id: str = "",
    display_name: str = "",
) -> tuple[Path, Path]:
    """Save a matched version; publish the runnable entry only after its document.

    An interrupted process may leave a document-only version; numbering skips
    such files on the next save. Ordinary write errors roll back only the new
    document, never a previous asset. Exclusive store writes prevent overwrites.
    """
    configuration.require_current(document, package)
    identity = skill_id.strip() or package.skill_id
    name = display_name.strip() or package.display_name
    with _SAVE_LOCK:
        history = [*package_store.list_versions(), *document_store.list_versions()]
        versions = [
            version
            for item in history
            if item.startswith(f"{identity}/v")
            for key, version in [parse_saved_selection(item)]
        ]
        version = max(versions, default=0) + 1
        saved_package = SkillPackage.model_validate(
            {
                **package.model_dump(mode="json"),
                "skill_id": identity,
                "display_name": name,
                "version": version,
            }
        )
        saved_document = document.model_copy(deep=True)
        saved_document.skill_template.skill_id = identity
        saved_document.skill_template.display_name = name
        saved_document.version = version
        saved_document = configuration.rebase_saved_snapshot(
            saved_document, saved_package
        )
        document_path: Path | None = None
        try:
            document_path = document_store.save(saved_document, version=version)
            package_path = package_store.save(saved_package, version=version)
        except (ValueError, OSError) as exc:
            if document_path is not None:
                document_path.unlink(missing_ok=True)
            raise ApplicationError(
                f"保存完整技能失败：{exc}；未发布不完整版本。"
            ) from exc
    return package_path, document_path

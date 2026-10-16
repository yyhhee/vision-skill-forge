"""ExecutionService: extracted V2 responsibilities, preserving public method signatures."""

from __future__ import annotations

import json

from application.v2.support import ApplicationError
from core.runtime import SkillPackageRuntime, detect_media_type
from core.schema import SkillPackage
from core.validator import validate_skill_package


class ExecutionService:
    def run_skill(
        self,
        generated_json: str,
        effective_json: str,
        media_type: str,
        media_path: str,
        editor_json: str = "",
    ):
        if self.rex is None:
            raise ApplicationError("Rex 服务尚未配置")
        if not media_path:
            raise ApplicationError("请先上传媒体")
        generated = SkillPackage.model_validate_json(generated_json)
        effective = SkillPackage.model_validate_json(effective_json)
        if editor_json:
            self.configuration_service.require_current(
                self._parse_editor_json(editor_json), effective
            )
        key = detect_media_type(media_path)
        errors = validate_skill_package(effective, self.registry)
        if errors:
            raise ApplicationError("运行前校验失败：" + "；".join(errors))
        effective.select_variant(key)
        record = SkillPackageRuntime(
            self.registry, rex=self.rex, run_store=self.run_store
        ).run(
            generated,
            effective,
            media_path,
            editor_document=self._parse_editor_json(editor_json)
            if editor_json
            else None,
        )
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

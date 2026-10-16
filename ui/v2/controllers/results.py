"""ResultController: extracted V2 responsibilities, preserving public method signatures."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import gradio as gr

from application.v2.support import _variant_key
from core.business_result_schema import RunResult
from core.media_policy import inspect_execution_policy
from core.result_presentation_schema import PresentationSpec
from core.run_result_view import build_run_result_view
from core.runtime import detect_media_type
from core.schema import SkillPackage
from ui.run_results import render_run_result_html


class ResultController:
    @staticmethod
    def business_result_html(run_dir: str) -> str:
        directory = Path(run_dir)
        result = RunResult.model_validate_json(
            (directory / "run_result_v3.json").read_text("utf-8")
        )
        presentation_path = directory / "presentation_specs.json"
        presentation_data = (
            json.loads(presentation_path.read_text("utf-8"))
            if presentation_path.is_file()
            else []
        )
        view = build_run_result_view(
            result,
            [PresentationSpec.model_validate(item) for item in presentation_data],
        )
        return render_run_result_html(view)

    def inspect_media(self, effective_json: str, media_type: str, media_path: str):
        if not media_path:
            raise gr.Error("请先上传媒体")
        package = SkillPackage.model_validate_json(effective_json)
        key = detect_media_type(media_path)
        package.select_variant(key)
        policy = inspect_execution_policy(package, key, media_path, self.registry)
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

    def result_contract(
        self, effective_json: str, media_type: str
    ) -> dict[str, dict[str, Any]]:
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
            or any(
                constraint.temporal for constraint in package.semantic_ir.constraints
            )
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
                    diagnostics = [
                        {
                            "code": "semantic_event_output_missing",
                            "reason": info["reason"],
                        },
                        *diagnostics,
                    ]
                sections[key]["diagnostics"] = diagnostics
        return sections

"""AnnotationController: extracted V2 responsibilities, preserving public method signatures."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import gradio as gr

from application.v2.support import _variant_key
from core.annotation import (
    annotations_from_package,
    extract_annotation_frame,
    normalize_canvas_point,
    render_annotation_workspace,
)
from core.configuration import configuration_status
from core.schema import SkillPackage
from ui.v2.presentation import NO_ANNOTATION_SLOT


class AnnotationController:
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
        current.update(
            {
                "asset_path": str(Path(asset_path).resolve()),
                "media_type": frame.media_type,
                "timestamp": frame.timestamp,
                "frame_index": frame.frame_index,
            }
        )
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
            item for item in configuration_status(package) if item["media_type"] == key
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
        return [{**row, "selected": row["slot_id"] == selected_slot_id} for row in rows]

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
        remaining = list(
            {slot.slot_id: slot for slot in variant.configuration_slots}.values()
        )
        emitted: set[str] = set()
        while remaining:
            ready = [
                slot
                for slot in remaining
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
                    item["id"]
                    for item in params.get("regions", [])
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
                    item["key"]
                    for item in params.get("directions", [])
                    if isinstance(item, dict) and item.get("key")
                ]
                if slot.key_source_slot_id:
                    source = slot_by_id.get(slot.key_source_slot_id)
                    source_node = nodes.get(source.binding.node_id) if source else None
                    expected = [
                        item["id"]
                        for item in (
                            source_node.params.get("regions", [])
                            if source_node is not None
                            else []
                        )
                        if isinstance(item, dict) and item.get("id")
                    ]
                    pending_items = (
                        ["await_source"]
                        if not expected
                        else [item for item in expected if item not in configured_items]
                    )
                elif not configured_items:
                    pending_items = ["new_item"]
            rows.append(
                {
                    **status_by_id[slot.slot_id],
                    "depends_on": slot.key_source_slot_id,
                    "configured_items": configured_items,
                    "pending_items": pending_items,
                    "help_text": slot.help_text,
                }
            )

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
                    and row["required"]
                    and not row["configured"]
                    and row["pending_items"]
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

    def annotation_wizard_markdown(self, effective_json: str, media_type: str) -> str:
        wizard = self.annotation_wizard_state(effective_json, media_type)
        if not wizard["slots"]:
            automatic_regions = self._automatic_region_labels(
                effective_json, media_type
            )
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
            pending = (
                "、".join(
                    "等待上游区域"
                    if item == "await_source"
                    else ("可添加新区域" if item == "new_item" else item)
                    for item in slot["pending_items"]
                )
                or "无"
            )
            state = "已完成" if slot["configured"] else "待完成"
            dependency = (
                f"；依赖 `{slot['depends_on']}` 的命名项" if slot["depends_on"] else ""
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
            lines.append(f"\n➡️ 下一步：配置 `{wizard['current_slot']}`{hint}。")
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
            (
                item
                for item in package.variants[key].configuration_slots
                if item.slot_id == slot_id
            ),
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
        tool = (
            "direction"
            if slot.kind in {"direction", "direction_set"}
            else ("polygon" if "polygon" in slot.allowed_shapes else "rectangle")
        )
        item_label = (
            slot.label
            if slot.kind == "region_set" and not row["configured_items"]
            else item_id
        )
        return tool, item_id, item_label

    def annotation_tool_choices(
        self, effective_json: str, media_type: str, slot_id: str | None
    ) -> list[tuple[str, str]]:
        """Return stable Chinese labels and machine values for drawing tools."""

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
            return [("矩形", "rectangle"), ("多边形", "polygon")]
        if slot.kind in {"direction", "direction_set"}:
            return [("方向箭头", "direction")]
        values = list(slot.allowed_shapes or ["rectangle", "polygon"])
        has_linked_direction = any(
            item.kind in {"direction", "direction_set"}
            and item.key_source_slot_id == slot.slot_id
            for item in package.variants[key].configuration_slots
        )
        if has_linked_direction and "direction" not in values:
            values.append("direction")
        labels = {
            "rectangle": "矩形",
            "polygon": "多边形",
            "direction": "方向箭头",
        }
        return [(labels.get(value, value), value) for value in values]

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
        elif current_slot is not None and tool in {"rectangle", "polygon"}:  # noqa: SIM102 — preserved V2 behavior
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
            "；同时保留自动生成区域能力："
            + "、".join(automatic_regions)
            + "（兼容旧配置，不可手工编辑且默认不参与判定）"
            if automatic_regions
            else ""
        )
        return f"此技能需要场景标注：{labels}。使用当前任务媒体完成一次绘制后即可运行{suffix}。"

    def _automatic_region_labels(
        self, effective_json: str, media_type: str
    ) -> list[str]:
        """Return read-only region producers so automatic ROIs are visible in 02 标注."""

        if not effective_json:
            return []
        package = SkillPackage.model_validate_json(effective_json)
        variant = package.variants.get(_variant_key(media_type))
        if variant is None or variant.status == "unsupported":
            return []
        return [
            node.id for node in variant.nodes if node.op == "region.from_objects@1.0"
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
        points_json = json.dumps(state.get("points", []), ensure_ascii=False)
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

    def clear_saved_annotations(
        self,
        effective_json: str,
        media_type: str,
        asset_path: str,
        timestamp: float,
        state: dict | None,
    ):
        """Clear all persisted manual annotations for the active variant.

        ``clear_annotation_points`` intentionally remains the draft-only undo
        action used by the drawing controls.  This method is the explicit
        canvas reset action: it removes every saved region and direction in
        the current image/video variant, then returns a fresh empty preview so
        no stale geometry remains visible.
        """

        if not effective_json:
            raise gr.Error("请先生成或加载技能")
        if not asset_path:
            raise gr.Error("请先加载当前任务媒体")
        try:
            package = SkillPackage.model_validate_json(effective_json)
            key = _variant_key(media_type)
            before = annotations_from_package(package, key)
            removed = len(before.get("regions", [])) + len(before.get("directions", []))
            updated = self.configuration_binder.clear_annotations(
                package, media_type=key
            )
        except (ValueError, TypeError) as exc:
            raise gr.Error(f"清空标注失败：{exc}") from exc

        current = dict(state or {})
        current["tool"] = current.get("tool") or "rectangle"
        current["points"] = []
        preview, current, _, _ = self._render_annotation_state(
            self._dump(updated), media_type, asset_path, timestamp, current
        )
        status = (
            f"✅ 已清空当前 {key} 流程的全部已保存标注（{removed} 项）；"
            "配置槽已恢复为待绘制，请重新标注。"
        )
        return self._dump(updated), preview, current, "[]", status

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
                raise ValueError  # noqa: TRY004 — preserve the existing exception contract
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
            "direction",
            "direction_set",
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
                (
                    item
                    for item in package.variants[key].nodes
                    if item.id == slot.binding.node_id
                ),
                None,
            )
            existing = [
                it.get("id")
                for it in (node.params.get("regions", []) if node else [])
                if isinstance(it, dict) and it.get("id")
            ]
            if rerouted_for_tool or not item_id or not str(item_id).strip():
                item_id = f"{slot.slot_id}_{len(existing) + 1}"
                item_label = item_label or (slot.label if not existing else item_id)
        elif slot.kind == "direction_set":
            node = next(
                (
                    item
                    for item in package.variants[key].nodes
                    if item.id == slot.binding.node_id
                ),
                None,
            )
            existing = [
                it.get("key")
                for it in (node.params.get("directions", []) if node else [])
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
                    for it in (
                        source_node.params.get("regions", []) if source_node else []
                    )
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
            return [
                item.get("id")
                for item in node.params.get("regions", [])
                if item.get("id")
            ]
        if slot.kind == "direction_set":
            return [
                item.get("key")
                for item in node.params.get("directions", [])
                if item.get("key")
            ]
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

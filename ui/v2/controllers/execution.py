"""ExecutionConfigController: extracted V2 responsibilities, preserving public method signatures."""

from __future__ import annotations

import json
import re
from typing import Any

import gradio as gr

from application.v2.support import _variant_key
from core.preset_factory import apply_context_confirmation
from core.schema import SkillPackage
from core.validator import validate_skill_package
from core.video_sampling import normalize_end_seconds


class ExecutionConfigController:
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
                "labels": [],
                "selected_labels": [],
                "enabled": False,
                "confirmation_phrases": "",
                "padding_fraction": 1.0,
                "crop_long_side": 640,
                "status": f"当前技能没有可编辑的 {key} variant。",
            }
        label_phrases: dict[str, list[str]] = {}
        exclusion_labels = {
            label
            for node in variant.nodes
            if node.op == "objects.filter_by_label@1.0"
            and node.id.endswith("_exclusion")
            for label in node.params.get("labels", [])
        }
        crop_frame_refs = {
            f"${node.id}" for node in variant.nodes if node.op == "object.crop@1.0"
        }
        crop_frame_refs.update(
            f"${node.id}"
            for node in variant.nodes
            if node.op.startswith("image.resize@")
            and node.inputs.get("frames") in crop_frame_refs
        )
        for node in variant.nodes:
            if (
                node.op != "rex.ground@1.1"
                or node.id.startswith("context_confirmation_")
                or node.inputs.get("frames") in crop_frame_refs
            ):
                continue
            for target in node.params.get("targets", []):
                label = target.get("label")
                phrases = target.get("phrases", [])
                if label and label not in exclusion_labels and phrases:
                    label_phrases.setdefault(label, []).extend(phrases)
        candidate = next(
            (
                node
                for node in variant.nodes
                if node.id == "context_confirmation_candidates"
            ),
            None,
        )
        evidence = next(
            (
                node
                for node in variant.nodes
                if node.id == "context_confirmation_evidence_raw"
            ),
            None,
        )
        crops = next(
            (node for node in variant.nodes if node.id == "context_confirmation_crops"),
            None,
        )
        crop_resize = next(
            (
                node
                for node in variant.nodes
                if node.id == "context_confirmation_crop_resized"
            ),
            None,
        )
        candidate_phrases = (
            set(candidate.params.get("phrases", [])) if candidate else set()
        )
        selected_labels = [
            label
            for label, phrases in label_phrases.items()
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
            "padding_fraction": float(crops.params.get("padding_fraction", 1.0))
            if crops
            else 1.0,
            "crop_long_side": int(crop_resize.params.get("long_side", 640))
            if crop_resize
            else 640,
            "status": (
                "已读取当前 variant 的二次可见性确认分支。"
                if candidate
                else "当前未启用二次可见性确认；启用后仅复核选中的候选类别。"
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
        exclusion_labels = {
            label
            for node in variant["nodes"]
            if node["op"] == "objects.filter_by_label@1.0"
            and node["id"].endswith("_exclusion")
            for label in node["params"].get("labels", [])
        }
        crop_frame_refs = {
            f"${node['id']}"
            for node in variant["nodes"]
            if node["op"] == "object.crop@1.0"
        }
        crop_frame_refs.update(
            f"${node['id']}"
            for node in variant["nodes"]
            if node["op"].startswith("image.resize@")
            and node.get("inputs", {}).get("frames") in crop_frame_refs
        )
        for node in variant["nodes"]:
            if (
                node["op"] != "rex.ground@1.1"
                or node["id"].startswith("context_confirmation_")
                or node.get("inputs", {}).get("frames") in crop_frame_refs
            ):
                continue
            for target in node["params"].get("targets", []):
                label = target.get("label")
                phrases = target.get("phrases", [])
                if label and label not in exclusion_labels and phrases:
                    label_phrases.setdefault(label, []).extend(phrases)
        selected = list(dict.fromkeys(candidate_labels or []))
        unknown = [label for label in selected if label not in label_phrases]
        if unknown:
            raise gr.Error("待复核类别不存在于当前 variant：" + "、".join(unknown))
        candidate_phrases = [
            phrase for label in selected for phrase in label_phrases[label]
        ]
        confirmation_phrases = [
            item.strip()
            for item in re.split(r"[\n,;]+", confirmation_text or "")
            if item.strip()
        ]
        if enabled and not selected:
            raise gr.Error("启用二次可见性确认后，请至少选择一个待复核检测类别。")
        if enabled and not confirmation_phrases:
            raise gr.Error("启用二次可见性确认后，请填写至少一条确认可见证据提示词。")
        try:
            nodes, outputs = apply_context_confirmation(
                variant["nodes"],
                variant["outputs"],
                enabled=bool(enabled),
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
        current_resize = dict(resize.get("params") or {})

        def _number_or(value, fallback, cast, label):
            candidate = fallback if value in (None, "") else value
            try:
                return cast(candidate)
            except (TypeError, ValueError) as exc:
                raise gr.Error(f"{label}必须填写有效数值。") from exc

        resize["op"] = "image.resize@1.1"
        resize["params"] = {
            "mode": resize_mode,
            "long_side": _number_or(
                long_side, current_resize.get("long_side", 1280), int, "缩放长边"
            ),
            "width": _number_or(
                width, current_resize.get("width", 1280), int, "缩放宽度"
            ),
            "height": _number_or(
                height, current_resize.get("height", 720), int, "缩放高度"
            ),
            "interpolation": interpolation,
        }
        tile = next(
            (
                node
                for node in nodes
                if node["op"].startswith("image.tile@")
                and node.get("inputs", {}).get("frames") == f"${resize['id']}"
            ),
            None,
        )
        tile_id = tile["id"] if tile is not None else "preprocess_tiles"
        frame_sources = {f"${resize['id']}", f"${tile_id}"}
        primary_ground = next(
            (
                node
                for node in nodes
                if node["op"].startswith("rex.ground@")
                and node["id"] in {"candidates_raw", "candidates"}
            ),
            None,
        )
        if primary_ground is None:
            primary_ground = next(
                (
                    node
                    for node in nodes
                    if node["op"].startswith("rex.ground@")
                    and node.get("inputs", {}).get("frames") in frame_sources
                ),
                None,
            )
        ground_nodes = [primary_ground] if primary_ground is not None else []
        if tile_enabled:
            current_tile = dict(tile.get("params") or {}) if tile else {}
            tile_data = {
                "id": tile_id,
                "op": "image.tile@1.1",
                "inputs": {"frames": f"${resize['id']}"},
                "params": {
                    "tile_width": _number_or(
                        tile_width,
                        current_tile.get("tile_width", 640),
                        int,
                        "切片宽度",
                    ),
                    "tile_height": _number_or(
                        tile_height,
                        current_tile.get("tile_height", 640),
                        int,
                        "切片高度",
                    ),
                    "overlap_x": _number_or(
                        overlap_x,
                        current_tile.get("overlap_x", 0.2),
                        float,
                        "横向重叠比例",
                    ),
                    "overlap_y": _number_or(
                        overlap_y,
                        current_tile.get("overlap_y", 0.2),
                        float,
                        "纵向重叠比例",
                    ),
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
                current_dedup = dict(node.get("params") or {})
                node["params"] = {
                    "metric": dedup_metric or current_dedup.get("metric", "ios"),
                    "threshold": _number_or(
                        dedup_threshold,
                        current_dedup.get("threshold", 0.5),
                        float,
                        "去重阈值",
                    ),
                    "keep": (
                        "best_localization"
                        if tile_enabled
                        else current_dedup.get("keep", "first")
                    ),
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
            (
                node
                for node in variant["nodes"]
                if node["op"].startswith("video.sample@")
            ),
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
            (node for node in variant["nodes"] if node["op"] == "output.draw@1.0"),
            None,
        )
        if draw is None:
            raise gr.Error("当前 variant 没有 output.draw 节点")
        params = dict(draw.get("params", {}))
        params.update(
            {
                "output_size_mode": size_mode,
                "output_width": None if width in (None, "") else int(width),
                "output_height": None if height in (None, "") else int(height),
                "output_fps_mode": fps_mode,
                "output_fps": None if fps in (None, "") else float(fps),
            }
        )
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
        region.update(
            {
                "op": "region.manual@1.0",
                "inputs": {},
                "params": {
                    "shape": "rectangle",
                    "points": [
                        [min(x0, x1), min(y0, y1)],
                        [max(x0, x1), max(y0, y1)],
                    ],
                },
            }
        )
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
            raise gr.Error(
                "ROI 点必须是 JSON 坐标数组，例如 [[0.1,0.2],[0.9,0.8]]"
            ) from exc
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
            region.update(
                {
                    "op": "region.manual_set@1.0",
                    "inputs": {},
                    "params": {"regions": regions},
                }
            )
        else:
            region.update(
                {
                    "op": "region.manual@1.0",
                    "inputs": {},
                    "params": {"shape": shape, "points": points},
                }
            )

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
            direction.update(
                {
                    "op": "direction.manual@1.0",
                    "inputs": {},
                    "params": {"vector": vector},
                }
            )
        else:
            directions = []
            if direction.get("op") == "direction.manual_set@1.0":
                directions = list(direction.get("params", {}).get("directions", []))
            replacement = {"key": target_key, "vector": vector}
            index = next(
                (
                    i
                    for i, item in enumerate(directions)
                    if item.get("key") == target_key
                ),
                None,
            )
            if index is None:
                directions.append(replacement)
            else:
                directions[index] = replacement
            direction.update(
                {
                    "op": "direction.manual_set@1.0",
                    "inputs": {},
                    "params": {"directions": directions},
                }
            )

        updated = SkillPackage.model_validate(data)
        errors = validate_skill_package(updated, self.registry)
        if errors:
            raise gr.Error("方向配置无效：" + "；".join(errors))
        return self._dump(updated)

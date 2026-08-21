from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def n(node_id, op, inputs, params=None):
    return {"id": node_id, "op": op, "inputs": inputs, "params": params or {}}


def spec(name, display, instruction, media_type, nodes, outputs):
    return {"version": "0.1", "name": name, "display_name": display,
            "original_instruction": instruction, "compile_status": "compiled",
            "input": {"accept": [media_type]}, "nodes": nodes, "outputs": outputs}


def video_start():
    return [n("video", "media.video@1.0", {"media": "$input"}),
            n("frames", "video.sample@1.0", {"video": "$video"}, {"mode": "fps", "fps": 2.0})]


def image_start(tile=False):
    nodes = [n("image", "media.image@1.0", {"media": "$input"}),
             n("resized", "image.resize@1.0", {"frames": "$image"}, {"mode": "long_side", "long_side": 1280})]
    if tile:
        nodes.append(n("tiled", "image.tile@1.0", {"frames": "$resized"},
                       {"tile_width": 640, "tile_height": 640, "overlap": 0.2,
                        "deduplicate_iou": 0.7, "deduplicate_mode": "keep_larger"}))
    return nodes


def video_event(name, display, instruction, label, phrases):
    nodes = video_start() + [
        n("resized", "image.resize@1.0", {"frames": "$frames"}, {"mode": "long_side", "long_side": 1280}),
        n("objects", "rex.ground@1.0", {"frames": "$resized"}, {"targets": [{"label": label, "phrases": phrases}]}),
        n("count", "measure.count@1.0", {"objects": "$objects"}),
        n("present", "logic.compare@1.0", {"left": "$count"}, {"operator": ">", "value": 0}),
        n("events", "temporal.persist@1.0", {"condition": "$present"},
          {"seconds": 1.0, "scope": "global", "gap_tolerance_seconds": 0.6, "trigger_mode": "once"}),
        n("alerts", "output.alert@1.0", {"events": "$events"}, {"label": display}),
        n("draw", "output.draw@1.0", {"frames": "$frames", "objects": "$objects", "events": "$alerts"}),
    ]
    return spec(name, display, instruction, "video", nodes,
                {"media": "$draw", "events": "$alerts", "objects": "$objects"})


def direct_image(name, display, instruction, label, phrases, tile=False):
    frame_ref = "$tiled" if tile else "$resized"
    nodes = image_start(tile) + [
        n("objects", "rex.ground@1.0", {"frames": frame_ref}, {"targets": [{"label": label, "phrases": phrases}]}),
        n("draw", "output.draw@1.0", {"frames": "$image", "objects": "$objects"}),
    ]
    return spec(name, display, instruction, "image", nodes, {"media": "$draw", "objects": "$objects"})


def build_all():
    result = []
    result.append(("P01", video_event("fire_smoke", "烟火检测", "检测画面中的烟雾或明火，持续出现1秒后报警。", "烟火",
                                       ["smoke", "visible smoke", "fire", "flame", "open flame"])))
    result.append(("P02", video_event("traffic_accident", "交通事故检测", "检测车辆碰撞、侧翻或事故车辆，持续1秒后报警。", "交通事故",
                                       ["vehicle collision", "overturned vehicle", "crashed vehicle", "traffic accident"])))
    targets = [
        ("消防车", ["fire truck", "fire engine"]), ("救护车", ["ambulance", "emergency medical vehicle"]),
        ("警车", ["police car", "police vehicle"]), ("工程抢险车", ["engineering rescue vehicle", "emergency repair truck"]),
        ("道路清障车", ["tow truck", "road recovery vehicle", "wrecker truck"]),
        ("环卫车", ["sanitation vehicle", "street sweeper", "garbage truck"]),
        ("油罐车", ["tanker truck", "fuel tanker truck"]),
        ("混凝土搅拌车", ["concrete mixer truck", "cement mixer truck"]),
        ("混凝土泵车", ["concrete pump truck"]), ("汽车吊", ["truck crane", "mobile crane truck"]),
        ("高空作业车", ["aerial work platform truck", "bucket truck"]),
        ("危险品运输车", ["hazardous materials truck", "hazmat transport vehicle"]),
    ]
    nodes = image_start() + [
        n("objects", "rex.ground@1.0", {"frames": "$resized"},
          {"targets": [{"label": label, "phrases": phrases} for label, phrases in targets]}),
        n("draw", "output.draw@1.0", {"frames": "$image", "objects": "$objects"}),
    ]
    result.append(("P03", spec("special_vehicles", "特种车辆检测", "检测所有特种车辆并标注具体类型。", "image", nodes,
                                {"media": "$draw", "objects": "$objects"})))

    nodes = video_start() + [
        n("vehicles", "rex.ground@1.0", {"frames": "$frames"}, {"targets": [{"label": "车辆", "phrases": ["vehicle", "car", "truck"]}]}),
        n("tracks", "track.iou@1.0", {"objects": "$vehicles"}),
        n("count", "measure.count@1.0", {"objects": "$vehicles"}),
        n("many", "logic.compare@1.0", {"left": "$count"}, {"operator": ">=", "value": 4}),
        n("speed", "measure.speed@1.0", {"tracks": "$tracks"}, {"window_frames": 2, "aggregation": "global_mean"}),
        n("slow", "logic.compare@1.0", {"left": "$speed"}, {"operator": "<", "value": 10.0}),
        n("congested", "logic.all@1.0", {"conditions": ["$many", "$slow"]}),
        n("events", "temporal.persist@1.0", {"condition": "$congested"}, {"seconds": 1.0, "scope": "global", "gap_tolerance_seconds": 0.6}),
        n("alerts", "output.alert@1.0", {"events": "$events"}, {"label": "车辆拥堵"}),
        n("draw", "output.draw@1.0", {"frames": "$frames", "objects": "$vehicles", "events": "$alerts"}),
    ]
    result.append(("P04", spec("highway_congestion", "车辆拥堵", "车辆不少于4且平均像素速度低于5，持续1秒报警。", "video", nodes,
                                {"media": "$draw", "events": "$alerts", "objects": "$vehicles"})))

    nodes = video_start() + [
        n("vehicles", "rex.ground@1.0", {"frames": "$frames"}, {"targets": [{"label": "车辆", "phrases": ["vehicle"]}]}),
        n("tracks", "track.iou@1.0", {"objects": "$vehicles"}, {"iou_threshold": 0.2, "max_missing_frames": 1}),
        n("headings", "measure.heading@1.0", {"tracks": "$tracks"}, {"window_frames": 3, "min_displacement_pixels": 5.0}),
        n("majority", "measure.majority_heading@1.0", {"directions": "$headings"}, {"minimum_tracks": 3}),
        n("expected", "direction.manual@1.0", {}, {"vector": [1.0, 0.0]}),
        n("opposite", "logic.compare@1.0", {"left": "$headings", "right": "$expected"}, {"operator": "opposite_direction", "threshold": -0.5}),
        n("events", "temporal.persist@1.0", {"condition": "$opposite"}, {"seconds": 1.0, "scope": "track", "gap_tolerance_seconds": 0.6}),
        n("alerts", "output.alert@1.0", {"events": "$events"}, {"label": "逆行车辆"}),
        n("draw", "output.draw@1.0", {"frames": "$frames", "objects": "$vehicles", "events": "$alerts"}),
    ]
    result.append(("P05", spec("highway_wrong_way", "车辆逆行", "检测与多数车辆方向相反并持续1秒的车辆。", "video", nodes,
                                {"media": "$draw", "events": "$alerts", "objects": "$vehicles", "observed_majority": "$majority"})))

    nodes = video_start() + [
        n("people", "rex.ground@1.0", {"frames": "$frames"}, {"targets": [{"label": "人员", "phrases": ["person"]}]}),
        n("tracks", "track.iou@1.0", {"objects": "$people"}),
        n("road", "region.full_frame@1.0", {"frames": "$frames"}),
        n("inside", "spatial.inside@1.0", {"objects": "$tracks", "region": "$road"}, {"mode": "center"}),
        n("events", "temporal.persist@1.0", {"condition": "$inside"}, {"seconds": 1.0, "scope": "track", "gap_tolerance_seconds": 0.6}),
        n("alerts", "output.alert@1.0", {"events": "$events"}, {"label": "车道人员逗留"}),
        n("draw", "output.draw@1.0", {"frames": "$frames", "objects": "$people", "events": "$alerts", "regions": "$road"}),
    ]
    result.append(("P06", spec("highway_person_dwell", "车道人员逗留", "检测在车道范围持续逗留超过1秒的人员。", "video", nodes,
                                {"media": "$draw", "events": "$alerts", "objects": "$people"})))

    nodes = video_start() + [
        n("vehicles", "rex.ground@1.0", {"frames": "$frames"}, {"targets": [{"label": "车辆", "phrases": ["parked vehicle", "vehicle"]}]}),
        n("tracks", "track.iou@1.0", {"objects": "$vehicles"}),
        n("speed", "measure.speed@1.0", {"tracks": "$tracks"}, {"window_frames": 2}),
        n("stopped", "logic.compare@1.0", {"left": "$speed"}, {"operator": "<", "value": 2.0}),
        n("events", "temporal.persist@1.0", {"condition": "$stopped"}, {"seconds": 1.0, "scope": "track", "gap_tolerance_seconds": 0.6}),
        n("alerts", "output.alert@1.0", {"events": "$events"}, {"label": "车辆违停"}),
        n("draw", "output.draw@1.0", {"frames": "$frames", "objects": "$vehicles", "events": "$alerts"}),
    ]
    result.append(("P07", spec("illegal_parking", "车辆违停", "检测持续静止超过1秒的车辆。", "video", nodes,
                                {"media": "$draw", "events": "$alerts", "objects": "$vehicles"})))

    images = [
        ("P08", "road_debris", "道路抛洒物", "检测道路上的抛洒物、掉落货物或障碍物。", "道路抛洒物", ["road debris", "fallen cargo", "road obstacle"]),
        ("P10", "no_safety_rope", "未系安全绳", "检测高处作业中没有连接安全绳或安全带的人员。", "未系安全绳人员", ["worker at height without safety harness", "person not attached to safety rope"]),
        ("P11", "service_area_garbage", "服务区垃圾", "检测服务区垃圾堆或散落废弃物。", "垃圾", ["garbage", "pile of trash", "scattered waste"]),
    ]
    for item in images:
        result.append((item[0], direct_image(*item[1:])))

    nodes = image_start() + [
        n("workers", "rex.ground@1.0", {"frames": "$resized"},
          {"targets": [{"label": "施工人员", "phrases": ["construction worker"]}]}),
        n("helmets", "rex.ground@1.0", {"frames": "$resized"},
          {"targets": [{"label": "安全帽", "phrases": ["safety helmet"]}]}),
        n("has_helmet", "spatial.associate@1.0", {"subjects": "$workers", "objects": "$helmets"},
          {"relation": "center_in_subject_region", "threshold": 0.0,
           "subject_region": [0.0, 0.0, 1.0, 0.35]}),
        n("no_helmet", "logic.not@1.0", {"condition": "$has_helmet"}),
        n("filtered", "filter.apply@1.0", {"objects": "$workers", "condition": "$no_helmet"},
          {"output_label": "未戴安全帽人员"}),
        n("draw", "output.draw@1.0", {"frames": "$image", "objects": "$filtered"}),
    ]
    result.append(("P09", spec("no_helmet", "施工未戴安全帽", "检测施工人员中没有佩戴安全帽的人。", "image", nodes,
                                {"media": "$draw", "objects": "$filtered"})))

    result.append(("P12", video_event("person_fall", "人员摔倒", "检测摔倒或躺在地面上的人员，持续1秒后报警。", "摔倒人员",
                                       ["fallen person", "person lying on the ground", "person who has fallen"])))
    nodes = image_start(tile=True) + [
        n("objects", "rex.ground@1.0", {"frames": "$tiled"},
          {"targets": [{"label": "裂纹", "phrases": ["bridge crack", "concrete crack"]},
                       {"label": "锈蚀", "phrases": ["bridge corrosion", "rust"]},
                       {"label": "渗水", "phrases": ["water seepage", "water stain"]},
                       {"label": "剥落", "phrases": ["concrete spalling", "exposed rebar"]}]}),
        n("draw", "output.draw@1.0", {"frames": "$image", "objects": "$objects"}),
    ]
    result.append(("P13", spec("bridge_damage", "桥梁病害", "检测桥梁裂纹、锈蚀、渗水、剥落和露筋。", "image", nodes,
                                {"media": "$draw", "objects": "$objects"})))
    return result


def write_all():
    for preset_id, value in build_all():
        path = ROOT / f"{preset_id}_{value['name']}.json"
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    write_all()

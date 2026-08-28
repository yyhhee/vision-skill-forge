from __future__ import annotations


COLOR_NAMES = (
    "black", "white", "gray", "red", "orange", "yellow",
    "green", "cyan", "blue", "purple", "pink", "brown",
)

ATTRIBUTE_CATALOG = {
    "color": {"values": list(COLOR_NAMES), "executor": "visual.color_fraction@1.0"},
    "shape": {
        "values": ["round", "circle", "square", "rectangle", "triangle", "oval", "irregular"],
        "executor": "rex.ground@1.1",
    },
    "size": {"values": ["small", "medium", "large"], "executor": "visual.geometry@1.0"},
    "material": {
        "values": ["metal", "wood", "plastic", "glass", "concrete", "fabric", "paper",
                   "rubber", "stone", "ceramic"],
        "executor": "rex.ground@1.1",
    },
    "position": {
        "values": ["left", "center", "right", "top", "middle", "bottom"],
        "executor": "visual.geometry@1.0",
    },
    "state": {
        "values": ["open", "closed", "broken", "intact", "damaged", "fallen", "standing",
                   "moving", "stationary", "on", "off", "full", "empty", "wet", "dry",
                   "rusty", "cracked", "smoking", "burning"],
        "executor": "rex.ground@1.1",
    },
    "wearable": {"values": "affirmative visible phrase", "executor": "rex.ground@1.1"},
    "pose": {"values": "affirmative visible phrase", "executor": "rex.ground@1.1"},
    "appearance": {"values": "affirmative visible phrase", "executor": "rex.ground@1.1"},
}

SPATIAL_RELATIONS = (
    "inside_roi", "outside_roi", "near", "overlap", "contains", "inside",
    "left_of", "right_of", "above", "below",
)

SPATIAL_RELATION_MARKERS = {
    "left_of": ("左侧", "左边", "left of"),
    "right_of": ("右侧", "右边", "right of"),
    "above": ("上方", "上面", "above"),
    "below": ("下方", "下面", "below"),
    "near": ("附近", "靠近", "near"),
    "overlap": ("重叠", "overlap"),
    "inside": ("内部", "里面", "inside"),
    "contains": ("包含", "容纳", "contains"),
}

SPATIAL_RELATION_PATTERNS = (
    r"(?:位于|在).+?(?:左侧|左边|右侧|右边|上方|上面|下方|下面)",
    r"(?:识别|检测|查找|找出)?[^，。；,;]+?(?:附近|靠近|内部|里面|包含|容纳|重叠)[^，。；,;]+",
    r"\b(left|right)\s+of\b|\b(above|below|near|inside|contains|overlaps?)\b",
)

COUNT_OPERATORS = (">", ">=", "<", "<=", "==", "!=")

COLOR_MIN_FRACTIONS = {
    "black": 0.2, "white": 0.2, "gray": 0.2,
    "red": 0.1, "orange": 0.1, "yellow": 0.1, "green": 0.1,
    "cyan": 0.1, "blue": 0.1, "purple": 0.1, "pink": 0.1, "brown": 0.1,
}

CARRIER_CATALOG = {
    "clothing": {"phrase": "clothing", "color_mode": "dominant", "subject_region": [0, 0, 1, 1]},
    "upper_body_clothing": {"phrase": "upper body clothing", "color_mode": "fraction", "subject_region": [0, 0.1, 1, 0.7]},
    "lower_body_clothing": {"phrase": "lower body clothing", "color_mode": "fraction", "subject_region": [0, 0.45, 1, 1]},
    "headwear": {"phrase": "headwear", "color_mode": "dominant", "subject_region": [0, 0, 1, 0.35]},
    "footwear": {"phrase": "footwear", "color_mode": "dominant", "subject_region": [0, 0.75, 1, 1]},
    "vehicle_body": {"phrase": "vehicle body", "color_mode": "fraction", "subject_region": [0, 0, 1, 1]},
    "object": {"phrase": "object", "color_mode": "fraction", "subject_region": [0, 0, 1, 1]},
}

CARRIER_ALIASES = {
    "clothing": "clothing", "clothes": "clothing", "garment": "clothing",
    "shirt": "upper_body_clothing", "top": "upper_body_clothing",
    "top garment": "upper_body_clothing", "jacket": "upper_body_clothing",
    "coat": "upper_body_clothing", "upper body clothing": "upper_body_clothing",
    "pants": "lower_body_clothing", "trousers": "lower_body_clothing",
    "shorts": "lower_body_clothing", "skirt": "lower_body_clothing",
    "lower body clothing": "lower_body_clothing",
    "helmet": "headwear", "hat": "headwear", "headwear": "headwear",
    "shoe": "footwear", "shoes": "footwear", "boots": "footwear", "footwear": "footwear",
    "car body": "vehicle_body", "vehicle body": "vehicle_body",
}

COLOR_ALIASES = {
    "黑": "black", "黑色": "black", "black": "black",
    "白": "white", "白色": "white", "white": "white",
    "灰": "gray", "灰色": "gray", "灰色的": "gray", "gray": "gray", "grey": "gray",
    "红": "red", "红色": "red", "red": "red",
    "橙": "orange", "橙色": "orange", "orange": "orange",
    "黄": "yellow", "黄色": "yellow", "yellow": "yellow",
    "绿": "green", "绿色": "green", "green": "green",
    "青": "cyan", "青色": "cyan", "cyan": "cyan",
    "蓝": "blue", "蓝色": "blue", "blue": "blue",
    "紫": "purple", "紫色": "purple", "purple": "purple",
    "粉": "pink", "粉色": "pink", "pink": "pink",
    "棕": "brown", "棕色": "brown", "褐色": "brown", "brown": "brown",
}

CARRIER_TEXT_ALIASES = {
    **{name: name for name in CARRIER_CATALOG},
    **CARRIER_ALIASES,
    "衣服": "clothing", "衣物": "clothing", "服装": "clothing",
    "衣": "upper_body_clothing", "上衣": "upper_body_clothing", "上装": "upper_body_clothing",
    "短袖": "upper_body_clothing", "衬衣": "upper_body_clothing",
    "衬衫": "upper_body_clothing", "夹克": "upper_body_clothing",
    "外套": "upper_body_clothing", "红衣": "upper_body_clothing",
    "裤": "lower_body_clothing", "裤子": "lower_body_clothing", "长裤": "lower_body_clothing",
    "短裤": "lower_body_clothing", "灰裤": "lower_body_clothing",
    "头盔": "headwear", "安全帽": "headwear", "帽子": "headwear",
    "鞋": "footwear", "鞋子": "footwear", "靴子": "footwear",
    "车身": "vehicle_body", "车辆主体": "vehicle_body",
}


__all__ = [
    "ATTRIBUTE_CATALOG", "COLOR_MIN_FRACTIONS", "COLOR_NAMES",
    "COUNT_OPERATORS", "SPATIAL_RELATIONS", "SPATIAL_RELATION_MARKERS",
    "SPATIAL_RELATION_PATTERNS", "CARRIER_ALIASES", "CARRIER_CATALOG",
    "CARRIER_TEXT_ALIASES", "COLOR_ALIASES",
]

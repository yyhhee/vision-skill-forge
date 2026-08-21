from __future__ import annotations

import base64
import io
import re

from openai import OpenAI
from PIL import Image


def parse_detection_tokens(text: str | None) -> list[dict]:
    if not text:
        return []
    text = text.split("<|im_end|>")[0]
    if "<|box_start|>" in text and not text.rstrip().endswith("<|box_end|>"):
        text += "<|box_end|>"
    pattern = (
        r"<\|object_ref_start\|>\s*([^<]+?)\s*<\|object_ref_end\|>\s*"
        r"<\|box_start\|>(.*?)<\|box_end\|>"
    )
    detections = []
    for phrase, coordinates in re.findall(pattern, text, flags=re.DOTALL):
        for group in coordinates.split(","):
            tokens = re.findall(r"<(\d+)>", group)
            if len(tokens) != 4:
                continue
            values = [max(0, min(999, int(token))) / 999.0 for token in tokens]
            x0, y0, x1, y1 = values
            detections.append({
                "phrase": phrase.strip(),
                "bbox": [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)],
            })
    return detections


def _image_data_url(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=92)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


class RexGateway:
    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8000/v1",
        model: str = "rex-omni-awq",
        client=None,
        timeout: float = 300.0,
    ):
        self.model = model
        self.client = client or OpenAI(base_url=base_url, api_key="EMPTY", timeout=timeout)

    def detect(
        self,
        image: Image.Image,
        phrases: list[str],
        *,
        query_prompt: str | None = None,
    ) -> list[dict]:
        if not phrases:
            raise ValueError("Rex phrases cannot be empty")
        query = (query_prompt or f"Detect {', '.join(phrases)}").strip().rstrip(".")
        prompt = (
            f"{query}. "
            "Return every visible instance for every requested phrase, including "
            "small or partially occluded instances; do not omit a requested "
            "category just because another category is also present. "
            "Output only the bounding box coordinates in [x0, y0, x1, y1] format."
        )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant"},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": _image_data_url(image)}},
                        {"type": "text", "text": prompt},
                    ],
                },
            ],
            temperature=0.0,
            top_p=0.05,
            max_tokens=2048,
            extra_body={
                "top_k": 1,
                "repetition_penalty": 1.05,
                "skip_special_tokens": False,
                "spaces_between_special_tokens": False,
            },
        )
        raw = response.choices[0].message.content
        detections = parse_detection_tokens(raw)
        for detection in detections:
            detection["raw_output"] = raw
        return detections


__all__ = ["RexGateway", "parse_detection_tokens"]

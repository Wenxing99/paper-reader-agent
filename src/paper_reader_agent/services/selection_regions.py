from __future__ import annotations

import hashlib
import json
from math import ceil, floor
from typing import Any

from PIL import Image

from paper_reader_agent.config import AppConfig
from paper_reader_agent.models import PaperRecord
from paper_reader_agent.services.papers import render_page_image
from paper_reader_agent.services.storage import selection_debug_image_path, selection_debug_meta_path, write_json


def build_selection_debug_crop(
    config: AppConfig,
    record: PaperRecord,
    page_payload: dict[str, Any],
    selection_region: dict[str, Any],
) -> dict[str, Any]:
    normalized = _normalize_selection_region(selection_region, page_payload)
    crop_id = _selection_crop_id(normalized)
    output_path = selection_debug_image_path(config, record.id, crop_id)
    meta_path = selection_debug_meta_path(config, record.id, crop_id)

    page_image_path = render_page_image(config, record, normalized["page_number"])
    with Image.open(page_image_path) as image:
        page_width = float(page_payload.get("width") or 0.0)
        page_height = float(page_payload.get("height") or 0.0)
        if page_width <= 0 or page_height <= 0:
            raise ValueError("\u5f53\u524d\u9875\u7f3a\u5c11\u53ef\u7528\u7684\u5c3a\u5bf8\u4fe1\u606f\uff0c\u65e0\u6cd5\u751f\u6210\u9009\u533a\u88c1\u56fe\u3002")

        scale_x = image.width / page_width
        scale_y = image.height / page_height
        bounds = normalized["bounds"]
        left = max(0, min(image.width - 1, floor(bounds["x"] * scale_x)))
        top = max(0, min(image.height - 1, floor(bounds["y"] * scale_y)))
        right = max(left + 1, min(image.width, ceil((bounds["x"] + bounds["width"]) * scale_x)))
        bottom = max(top + 1, min(image.height, ceil((bounds["y"] + bounds["height"]) * scale_y)))

        if right <= left or bottom <= top:
            raise ValueError("\u9009\u533a\u77e9\u5f62\u65e0\u6548\uff0c\u65e0\u6cd5\u751f\u6210\u88c1\u56fe\u3002")

        if not output_path.exists():
            output_path.parent.mkdir(parents=True, exist_ok=True)
            crop = image.crop((left, top, right, bottom))
            try:
                crop.save(output_path, format="PNG")
            finally:
                crop.close()

    payload = {
        "crop_id": crop_id,
        "page_number": normalized["page_number"],
        "bounds": normalized["bounds"],
        "rects": normalized["rects"],
        "pixel_bounds": {
            "x": left,
            "y": top,
            "width": right - left,
            "height": bottom - top,
        },
    }
    write_json(meta_path, payload)
    return payload


def _normalize_selection_region(selection_region: dict[str, Any], page_payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(selection_region, dict):
        raise ValueError("\u6ca1\u6709\u6536\u5230\u53ef\u7528\u7684\u9009\u533a\u77e9\u5f62\u3002")

    page_number = int(selection_region.get("page_number") or page_payload.get("page_number") or 0)
    payload_page_number = int(page_payload.get("page_number") or 0)
    if page_number <= 0 or payload_page_number <= 0 or page_number != payload_page_number:
        raise ValueError("\u9009\u533a\u9875\u7801\u4e0e\u5f53\u524d\u9875\u4e0d\u4e00\u81f4\uff0c\u65e0\u6cd5\u751f\u6210\u88c1\u56fe\u3002")

    page_width = float(page_payload.get("width") or 0.0)
    page_height = float(page_payload.get("height") or 0.0)
    if page_width <= 0 or page_height <= 0:
        raise ValueError("\u5f53\u524d\u9875\u7f3a\u5c11\u53ef\u7528\u7684\u9875\u9762\u5c3a\u5bf8\u3002")

    rects = []
    for item in selection_region.get("rects") or []:
        rect = _normalize_rect(item, page_width, page_height)
        if rect:
            rects.append(rect)

    bounds = _normalize_rect(selection_region.get("bounds") or {}, page_width, page_height)
    if not bounds and rects:
        bounds = _union_rects(rects)
    if not bounds:
        raise ValueError("\u6ca1\u6709\u6536\u5230\u53ef\u7528\u7684\u9009\u533a\u77e9\u5f62\u3002")

    return {
        "page_number": page_number,
        "bounds": bounds,
        "rects": rects,
    }


def _normalize_rect(value: Any, page_width: float, page_height: float) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None

    try:
        x = float(value.get("x") or 0.0)
        y = float(value.get("y") or 0.0)
        width = float(value.get("width") or 0.0)
        height = float(value.get("height") or 0.0)
    except Exception as error:
        raise ValueError(f"\u9009\u533a\u77e9\u5f62\u683c\u5f0f\u65e0\u6548: {error}") from error

    x = max(0.0, min(page_width, x))
    y = max(0.0, min(page_height, y))
    width = max(0.0, min(page_width - x, width))
    height = max(0.0, min(page_height - y, height))
    if width <= 0 or height <= 0:
        return None

    return {
        "x": round(x, 3),
        "y": round(y, 3),
        "width": round(width, 3),
        "height": round(height, 3),
    }


def _union_rects(rects: list[dict[str, float]]) -> dict[str, float] | None:
    if not rects:
        return None

    left = min(rect["x"] for rect in rects)
    top = min(rect["y"] for rect in rects)
    right = max(rect["x"] + rect["width"] for rect in rects)
    bottom = max(rect["y"] + rect["height"] for rect in rects)
    return {
        "x": round(left, 3),
        "y": round(top, 3),
        "width": round(right - left, 3),
        "height": round(bottom - top, 3),
    }


def _selection_crop_id(selection_region: dict[str, Any]) -> str:
    digest = hashlib.sha1(json.dumps(selection_region, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return digest[:16]

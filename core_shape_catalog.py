"""Offline mechanical core references for interactive transformer previews.

The electrical library in :mod:`magnetics` remains the calculation authority.
This catalogue records manufacturer drawing dimensions in millimetres; no
mechanical dimension is reconstructed from effective Ae, Ve, Wa or MLT.
Returned records are independent copies, safe for scene-specific gap edits.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
import math
from typing import Any

from app_resources import resource_path


CATALOG_RESOURCE = "resources/core_shapes/catalog.json"
USABLE_STATUSES = frozenset({"datasheet_nominal", "reference_variant", "designation_nominal"})


@lru_cache(maxsize=1)
def _catalog() -> dict[str, Any]:
    with resource_path(CATALOG_RESOURCE).open(encoding="utf-8") as stream:
        catalog = json.load(stream)
    if catalog.get("schema_version") != 1:
        raise ValueError("不支持的磁芯机械目录版本")
    records = catalog.get("cores", [])
    names = [row["model"] for row in records]
    if len(names) != len(set(names)):
        raise ValueError("磁芯机械目录存在重复型号")
    for row in records:
        for key, value in row.get("dimensions_mm", {}).items():
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{row['model']} 的 {key} 不是有限尺寸")
            if value < 0 and not key.startswith("center_offset_"):
                raise ValueError(f"{row['model']} 的 {key} 为负尺寸")
        profile = row.get("shape_profile", {})
        for key in ("yoke_xy_mm", "center_xy_mm"):
            if key in profile:
                _validate_polygon(row["model"], key, profile[key])
        for index, polygon in enumerate(profile.get("returns_xy_mm", [])):
            _validate_polygon(row["model"], f"returns_xy_mm[{index}]", polygon)
    return catalog


def _validate_polygon(model: str, key: str, polygon: Any) -> None:
    """Reject corrupt offline contours before they reach a renderer."""
    if not isinstance(polygon, list) or len(polygon) < 3:
        raise ValueError(f"{model} 的 {key} 轮廓点不足")
    for point in polygon:
        if (not isinstance(point, list) or len(point) != 2
                or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in point)):
            raise ValueError(f"{model} 的 {key} 包含无效轮廓点")


def get_core_shape(model: str | None) -> dict[str, Any] | None:
    """Return the exact library model's mechanical reference, or ``None``.

    Case and surrounding spaces are ignored. We deliberately do not strip size
    suffixes or guess neighbouring models: those select different hardware.
    """
    key = str(model or "").strip().casefold()
    for record in _catalog()["cores"]:
        if record["model"].casefold() == key:
            return deepcopy(record)
    return None


def list_core_shapes() -> list[dict[str, Any]]:
    """Return all full records in the electrical library's display order."""
    return deepcopy(_catalog()["cores"])


def catalog_metadata() -> dict[str, Any]:
    """Expose coordinate, evidence and dimension semantics without GUI imports."""
    return deepcopy({key: value for key, value in _catalog().items() if key != "cores"})


def clear_catalog_cache() -> None:
    """Reload resource data after an explicit catalogue maintenance operation."""
    _catalog.cache_clear()

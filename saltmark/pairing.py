"""Pair a before and an after brick card with one uniform integer X shift."""
import numpy as np

from image_lab.validation import Invalid, integer, list_value, object_value

from . import sample

DEFAULT_LIMITS = {"shift": 32, "residual": 2, "visible": 24}
MAX_MARKS = 64
STATUS_LABELS = {"added": "浅色新增", "reduced": "浅色减少", "unchanged": "未变", "unproven": "无证"}


def limits(value, widths):
    value = object_value({} if value is None else value, "对位上限")
    ceiling = max(1, max(widths))
    return {
        "shift": integer(value.get("shift", DEFAULT_LIMITS["shift"]), "移量上限", 0, ceiling),
        "residual": integer(value.get("residual", DEFAULT_LIMITS["residual"]), "实标剩余偏差上限", 0, ceiling),
        "visible": integer(value.get("visible", DEFAULT_LIMITS["visible"]), "最低共见点数", 1, 4_000_000),
    }


def marks(value, widths):
    rows = []
    for item in list_value(value, "固定印记原 X 对", MAX_MARKS):
        item = object_value(item, "固定印记原 X 对")
        rows.append({"first": integer(item.get("first"), "第一张印记 X", 0, widths[0] - 1),
                     "second": integer(item.get("second"), "第二张印记 X", 0, widths[1] - 1)})
    return rows


def line(card, image):
    """Read one source cross-section; None-free metadata plus per-pixel evidence."""
    config = card["settings"]
    y = config["focus"]
    if not config["top"] <= y <= config["bottom"]:
        raise Invalid(f'“{card["name"]}”的原横截线不在测量框内，无法对照')
    row = image[y].astype(np.int16)
    floor = row.min(axis=1)
    spread = row.max(axis=1) - floor
    return {"y": y, "config": config, "floor": floor, "spread": spread,
            "pale": (floor >= config["minimum"]) & (spread <= config["spread"]),
            "clipped": np.any((row == 0) | (row == 255), axis=1)}


def window(first_line, second_line, shift):
    left = max(first_line["config"]["left"], second_line["config"]["left"] - shift)
    right = min(first_line["config"]["right"], second_line["config"]["right"] - shift)
    return left, right


def evaluate(first_line, second_line, pairs, config, shift):
    """Score one integer shift; None when it breaks a limit or the co-visible minimum."""
    if abs(shift) > config["shift"]:
        return None, "移量超过上限"
    residuals = np.abs(np.array([pair["second"] - pair["first"] for pair in pairs], dtype=np.int64) - shift)
    if int(residuals.max()) > config["residual"]:
        return None, "实标剩余偏差超过上限"
    left, right = window(first_line, second_line, shift)
    if right < left:
        return None, "两张截线没有共同范围"
    visible = right - left + 1
    if visible < config["visible"]:
        return None, "共见点数低于最低要求"
    clipped = first_line["clipped"][left:right + 1] | second_line["clipped"][left + shift:right + shift + 1]
    return {"shift": shift, "co_visible": int(visible),
            "true_overlap": int(visible - int(clipped.sum())),
            "mean_residual": float(residuals.mean()), "max_residual": int(residuals.max()),
            "residuals": [int(value) for value in residuals]}, None


def solve(first_line, second_line, pairs, config):
    if not pairs:
        raise Invalid("请至少保存一对固定印记原 X")
    rows = [result for shift in range(-config["shift"], config["shift"] + 1)
            for result in [evaluate(first_line, second_line, pairs, config, shift)[0]] if result]
    if not rows:
        raise Invalid("没有同时满足移量、实标剩余偏差和最低共见点数的整数位移")
    ceiling = max(row["true_overlap"] for row in rows) or 1
    for row in rows:
        overlap_term = row["true_overlap"] / ceiling
        residual_term = 1 - row["mean_residual"] / config["residual"] if config["residual"] else 1.
        row["score"] = round(.5 * (overlap_term + residual_term), 6)
    rows.sort(key=lambda row: (-row["score"], -row["true_overlap"], row["mean_residual"],
                               abs(row["shift"]), row["shift"]))
    return {"best": rows[0], "candidates": rows[:20], "candidate_count": len(rows),
            "marks": pairs, "limits": config,
            "first_line": first_line["y"], "second_line": second_line["y"],
            "note": "共见点须同时落在两张各自测量框的截线上；真原点重叠指两侧 RGB 都未被 0/255 截断的共见点。"}


def classify(first_point, second_point):
    if any(value in (0, 255) for value in first_point["rgb"] + second_point["rgb"]):
        return "unproven"
    first_pale, second_pale = bool(first_point["pale"]), bool(second_point["pale"])
    if second_pale and not first_pale:
        return "added"
    if first_pale and not second_pale:
        return "reduced"
    return "unchanged"


def evidence(first_image, second_image, first_line, second_line, shift, full=False):
    """Per-pixel pair evidence across both own threshold rules."""
    left, right = window(first_line, second_line, shift)
    if right < left:
        raise Invalid("两张截线没有共同范围")
    counts = {"co_visible": 0, "added": 0, "reduced": 0, "unchanged": 0, "unproven": 0}
    points = []
    for x in range(left, right + 1):
        first_point = sample.point(first_image, x, first_line["y"], first_line["config"])
        second_point = sample.point(second_image, x + shift, second_line["y"], second_line["config"])
        status = classify(first_point, second_point)
        counts["co_visible"] += 1
        counts[status] += 1
        row = {"first_x": x, "second_x": x + shift, "status": status,
               "first_pale": bool(first_point["pale"]), "second_pale": bool(second_point["pale"])}
        if full:
            row["first"] = first_point
            row["second"] = second_point
        points.append(row)
    counts["labels"] = dict(STATUS_LABELS)
    return {"shift": shift, "counts": counts, "points": points,
            "first_line": first_line["y"], "second_line": second_line["y"], "window": [left, right],
            "note": "各张用原有阈值判浅色；任一 RGB 通道为 0 或 255 的配对标为无证，不算未变。"}


def probe(first_image, second_image, first_line, second_line, shift, x):
    """Read the real paired source X/Y and RGB for one first-card column."""
    if not first_line["config"]["left"] <= x <= first_line["config"]["right"]:
        raise Invalid("请点在第一张卡片的截线范围内")
    first_point = sample.point(first_image, x, first_line["y"], first_line["config"])
    second_x = x + shift
    if not 0 <= second_x < second_image.shape[1]:
        return {"shift": shift, "first": first_point, "second": None, "status": "outside",
                "label": STATUS_LABELS["unproven"], "reason": "第二张范围外"}
    second_point = sample.point(second_image, second_x, second_line["y"], second_line["config"])
    if second_point["pale"] is None:
        return {"shift": shift, "first": first_point, "second": second_point, "status": "outside",
                "label": STATUS_LABELS["unproven"], "reason": "第二张范围外"}
    status = classify(first_point, second_point)
    return {"shift": shift, "first": first_point, "second": second_point, "status": status,
            "label": STATUS_LABELS[status], "reason": None}

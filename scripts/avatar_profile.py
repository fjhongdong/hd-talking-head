"""Shared head-and-shoulders calibration for a normalized 1080x1920 A-roll.

Landmarks are measured inputs, not a detector or proof of human approval.
The parent plan binds them to its edited A-roll and existing review gate.
"""
from __future__ import annotations

import copy
import math
import re


def _object(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError(f"avatar {label} fields are invalid")
    return value


def _number(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"avatar {label} must be finite")
    return value


def _integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"avatar {label} is outside its integer range")
    return value


def _point(value, anchor, size, radius, label):
    if type(value) is not list or len(value) != 2:
        raise ValueError(f"avatar {label} must be a measured point")
    x = (_number(value[0], label) - anchor["x"]) / size
    y = (_number(value[1], label) - anchor["y"]) / size
    if math.hypot(x - .5, y - .5) > radius:
        raise ValueError(f"avatar {label} is clipped by the circle")
    return x, y


def validate_avatar(avatar, *, frames=None):
    """Reject uncalibrated geometry; never replace it with default coordinates."""
    value = _object(avatar, ("profile", "position", "crop"), "contract")
    profile = _object(value["profile"], (
        "schema_version", "framing", "source_sha256", "diameter", "border_width", "border_color"
    ), "profile")
    if type(profile["schema_version"]) is not int or profile["schema_version"] != 1:
        raise ValueError("avatar profile version must be one")
    if profile["framing"] != "head-shoulders":
        raise ValueError("avatar framing must be head-shoulders")
    if type(profile["source_sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", profile["source_sha256"]):
        raise ValueError("avatar source SHA-256 is invalid")
    diameter = _integer(profile["diameter"], 128, 384, "diameter")
    border = _integer(profile["border_width"], 0, 24, "border width")
    if type(profile["border_color"]) is not str or not re.fullmatch(r"#[0-9A-Fa-f]{6}", profile["border_color"]):
        raise ValueError("avatar border color must be a hex RGB color")
    position = _object(value["position"], ("x", "y"), "position")
    extent = diameter + border * 2
    _integer(position["x"], 0, 1080 - extent, "position x")
    _integer(position["y"], 0, 1700 - extent, "position y")
    crop = _object(value["crop"], ("size", "anchors"), "crop")
    size = _integer(crop["size"], 32, 1080, "crop size")
    anchors = crop["anchors"]
    if type(anchors) is not list or not 3 <= len(anchors) <= 128:
        raise ValueError("avatar requires 3–128 measured crop anchors")
    prior = -1
    for anchor in anchors:
        _object(anchor, ("frame", "x", "y", "landmarks"), "anchor")
        frame = _integer(anchor["frame"], 0, 10_000_000, "anchor frame")
        if frame <= prior:
            raise ValueError("avatar anchor frames must strictly increase")
        prior = frame
        x, y = _number(anchor["x"], "crop x"), _number(anchor["y"], "crop y")
        if not (0 <= x <= 1080 - size and 0 <= y <= 1920 - size):
            raise ValueError("avatar crop exceeds the normalized source")
        landmarks = _object(anchor["landmarks"], (
            "head_top", "face_box", "chin", "neck", "shoulders"
        ), "landmarks")
        radius = .5 - 2 / diameter
        head = _point(landmarks["head_top"], anchor, size, radius, "head top")
        chin = _point(landmarks["chin"], anchor, size, radius, "chin")
        neck = _point(landmarks["neck"], anchor, size, radius, "neck")
        face = landmarks["face_box"]
        if type(face) is not list or len(face) != 4:
            raise ValueError("avatar face_box must be measured x/y/width/height")
        fx, fy, fw, fh = [_number(n, "face box") for n in face]
        if not .38 <= fw / size <= .52 or fh <= 0:
            raise ValueError("avatar face width must be 0.38–0.52 of crop")
        for px, py in ((fx, fy), (fx + fw, fy), (fx, fy + fh), (fx + fw, fy + fh)):
            _point([px, py], anchor, size, radius, "face box")
        shoulders = landmarks["shoulders"]
        if type(shoulders) is not list or len(shoulders) != 2:
            raise ValueError("avatar requires measured left and right shoulders")
        left, right = [_point(p, anchor, size, radius, "shoulder") for p in shoulders]
        if right[0] - left[0] < .68 - 1e-9:
            raise ValueError("avatar shoulder width must be at least 0.68 of crop")
        if not .06 - 1e-9 <= head[1] <= .11 + 1e-9:
            raise ValueError("avatar headroom must be 0.06–0.11 of crop")
        face_top, face_bottom = (fy - y) / size, (fy + fh - y) / size
        if not head[1] < face_top < face_bottom <= chin[1] < neck[1] <= max(left[1], right[1]):
            raise ValueError("avatar must preserve head, chin, neck and shoulder order")
    actual_frames = anchors[-1]["frame"] + 1
    frames = actual_frames if frames is None else _integer(frames, 3, 10_000_001, "frames")
    if actual_frames != frames or not {0, frames // 2, frames - 1}.issubset({a["frame"] for a in anchors}):
        raise ValueError("avatar anchors must cover this segment's first, middle and last frame")
    return copy.deepcopy(value)


def validate_plan_avatars(segments, *, source_sha256=None):
    """One source/style per plan, with independently calibrated segment crops."""
    shared = None
    for segment in segments:
        composition = segment["visual_strategy"]["composition"]
        if composition["presenter_mode"] != "bottom_window":
            if "avatar" in composition:
                raise ValueError("avatar is unused in hidden/full-frame presenter mode")
            continue
        duration = _number(segment["end"], "end") - _number(segment["start"], "start")
        frames = round(duration * 24)
        if abs(frames / 24 - duration) > 1e-6:
            raise ValueError("avatar segment must align to the 24fps clock")
        avatar = validate_avatar(composition.get("avatar"), frames=frames)
        profile = avatar["profile"]
        if source_sha256 is not None and profile["source_sha256"] != source_sha256:
            raise ValueError("avatar source differs from the edited A-roll")
        if shared is not None and profile != shared:
            raise ValueError("avatar profile must be shared across all B-roll segments")
        shared = profile


def crop_at(avatar, frame):
    """Return the square and linearly interpolated top-left for QA sampling."""
    checked = validate_avatar(avatar)
    anchors = checked["crop"]["anchors"]
    _number(frame, "sample frame")
    if not 0 <= frame <= anchors[-1]["frame"]:
        raise ValueError("avatar sample frame exceeds its segment")
    for a, b in zip(anchors, anchors[1:]):
        if frame <= b["frame"]:
            ratio = (frame - a["frame"]) / (b["frame"] - a["frame"])
            return checked["crop"]["size"], a["x"] + (b["x"] - a["x"]) * ratio, a["y"] + (b["y"] - a["y"]) * ratio
    raise ValueError("avatar sample frame is unavailable")


def _axis_expression(anchors, axis):
    # A balanced decision tree avoids FFmpeg's expression recursion limit when
    # a moving subject needs many anchors. The input is trimmed to these frames.
    def branch(first, last):
        if first == last:
            a, b = anchors[first:first + 2]
            span = b["frame"] - a["frame"]
            return f"{a[axis]:.9f}+({b[axis] - a[axis]:.9f})*(n-{a['frame']})/{span}"
        middle = (first + last) // 2
        return f"if(lte(n,{anchors[middle + 1]['frame']}),{branch(first, middle)},{branch(middle + 1, last)})"
    return branch(0, len(anchors) - 2)


def filter_chain(avatar, *, frames, fade_out=True):
    """Produce [presenter]; disable local fade when the compositor owns exit."""
    value = validate_avatar(avatar, frames=frames)
    profile, crop = value["profile"], value["crop"]
    diameter, border = profile["diameter"], profile["border_width"]
    outer = diameter + border * 2
    x = _axis_expression(crop["anchors"], "x")
    y = _axis_expression(crop["anchors"], "y")
    # Guard dimensions in the filter too: a different source must fail, not reframe.
    width = f"if(eq(iw,1080)*eq(ih,1920),{crop['size']},-1)"
    mask = "geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lte(hypot(X-W/2,Y-H/2),W/2-2),255,0)'"
    return [
        f"[0:v]fps=24,trim=start_frame=0:end_frame={frames},setpts=PTS-STARTPTS,format=rgba,"
        f"crop=w='{width}':h={crop['size']}:x='{x}':y='{y}':exact=1,"
        f"scale={diameter}:{diameter}:flags=lanczos,setsar=1,{mask}[presenter_face]",
        f"color=c={profile['border_color']}:s={outer}x{outer}:r=24:d={frames / 24:.9f},"
        f"format=rgba,{mask},trim=start_frame=0:end_frame={frames},setpts=PTS-STARTPTS[presenter_ring]",
        f"[presenter_ring][presenter_face]overlay={border}:{border}:eof_action=pass:shortest=0[presenter_raw]",
        (f"[presenter_raw]format=rgba,fade=t=out:st={max(0, frames - 12) / 24:.9f}:d=0.5:alpha=1[presenter]"
         if fade_out else "[presenter_raw]format=rgba[presenter]"),
    ]

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
    keys = ("profile", "position", "crop") + tuple(
        k for k in ("entrance", "exit", "continuation") if type(avatar) is dict and k in avatar
    )
    value = _object(avatar, keys, "contract")
    profile = _object(value["profile"], (
        "schema_version", "framing", "source_sha256", "diameter", "border_width", "border_color"
    ), "profile")
    if type(profile["schema_version"]) is not int or profile["schema_version"] != 1:
        raise ValueError("avatar profile version must be one")
    if profile["framing"] not in ("head-shoulders", "head-neck"):
        raise ValueError("avatar framing is invalid")
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
        framing = profile["framing"]
        landmark_keys = ("head_top", "face_box", "chin", "neck", "shoulders")
        if framing == "head-neck":
            landmark_keys = landmark_keys[:-1]
        landmarks = _object(anchor["landmarks"], landmark_keys, "landmarks")
        radius = .5 - 2 / diameter
        head = _point(landmarks["head_top"], anchor, size, radius, "head top")
        chin = _point(landmarks["chin"], anchor, size, radius, "chin")
        neck = _point(landmarks["neck"], anchor, size, radius, "neck")
        face = landmarks["face_box"]
        if type(face) is not list or len(face) != 4:
            raise ValueError("avatar face_box must be measured x/y/width/height")
        fx, fy, fw, fh = [_number(n, "face box") for n in face]
        face_width = fw / size
        if not (.38 <= face_width <= (.60 if framing == "head-neck" else .52)) or fh <= 0:
            maximum = .60 if framing == "head-neck" else .52
            raise ValueError(f"avatar face width must be 0.38–{maximum:.2f} of crop")
        for px, py in ((fx, fy), (fx + fw, fy), (fx, fy + fh), (fx + fw, fy + fh)):
            _point([px, py], anchor, size, radius, "face box")
        if not .06 - 1e-9 <= head[1] <= .11 + 1e-9:
            raise ValueError("avatar headroom must be 0.06–0.11 of crop")
        face_top, face_bottom = (fy - y) / size, (fy + fh - y) / size
        if framing == "head-shoulders":
            shoulders = landmarks["shoulders"]
            if type(shoulders) is not list or len(shoulders) != 2:
                raise ValueError("avatar requires measured left and right shoulders")
            left, right = [_point(p, anchor, size, radius, "shoulder") for p in shoulders]
            if right[0] - left[0] < .68 - 1e-9:
                raise ValueError("avatar shoulder width must be at least 0.68 of crop")
            valid_order = head[1] < face_top < face_bottom <= chin[1] < neck[1] <= max(left[1], right[1])
        else:
            valid_order = head[1] < face_top < face_bottom <= chin[1] < neck[1]
        if not valid_order:
            raise ValueError("avatar must preserve head, chin, neck and shoulder order")
    actual_frames = anchors[-1]["frame"] + 1
    frames = actual_frames if frames is None else _integer(frames, 3, 10_000_001, "frames")
    if actual_frames != frames or not {0, frames // 2, frames - 1}.issubset({a["frame"] for a in anchors}):
        raise ValueError("avatar anchors must cover this segment's first, middle and last frame")
    if "continuation" in value and (value["continuation"] is not True or "exit" in value):
        raise ValueError("avatar continuation must be true and cannot have an exit")
    exit_frames = 0 if "continuation" in value else 12
    if "exit" in value:
        leave = _object(value["exit"], ("kind", "frames"), "exit")
        if leave["kind"] != "avatar_to_aroll":
            raise ValueError("avatar exit kind is invalid")
        exit_frames = _integer(leave["frames"], 6, 18, "exit frames")
        if exit_frames >= frames:
            raise ValueError("avatar exit exceeds the segment")
    if "entrance" in value:
        entrance = _object(value["entrance"], ("kind", "frames"), "entrance")
        if entrance["kind"] != "aroll_to_avatar":
            raise ValueError("avatar entrance kind is invalid")
        entry_frames = _integer(entrance["frames"], 8, 18, "entrance frames")
        if entry_frames + exit_frames >= frames:
            raise ValueError("avatar entrance overlaps the exit")
    return copy.deepcopy(value)


def validate_plan_avatars(segments, *, source_sha256=None):
    """One source/style per plan, with independently calibrated segment crops."""
    animated = any(any(key in (s["visual_strategy"]["composition"].get("avatar") or {})
                       for key in ("entrance", "exit", "continuation")) for s in segments)
    shared = None
    previous = None
    for index, segment in enumerate(segments):
        composition = segment["visual_strategy"]["composition"]
        if composition["presenter_mode"] != "bottom_window":
            if "avatar" in composition:
                raise ValueError("avatar is unused in hidden/full-frame presenter mode")
            previous = segment
            continue
        duration = _number(segment["end"], "end") - _number(segment["start"], "start")
        frames = round(duration * 24)
        if abs(frames / 24 - duration) > 1e-6:
            raise ValueError("avatar segment must align to the 24fps clock")
        avatar = validate_avatar(composition.get("avatar"), frames=frames)
        following = segments[index + 1] if index + 1 < len(segments) else None
        if "entrance" in avatar:
            if (previous is None
                    or previous["visual_strategy"]["composition"]["presenter_mode"] != "full_frame"
                    or abs(float(previous["end"]) - float(segment["start"])) > 1e-6):
                raise ValueError("avatar entrance requires a contiguous full-frame A-roll")
        if "exit" in avatar:
            if (following is None
                    or following["visual_strategy"]["composition"]["presenter_mode"] != "full_frame"
                    or abs(float(segment["end"]) - float(following["start"])) > 1e-6):
                raise ValueError("avatar exit requires a contiguous full-frame A-roll")
        next_window = (following is not None and
                       following["visual_strategy"]["composition"]["presenter_mode"] == "bottom_window")
        if "continuation" in avatar:
            if not next_window or abs(float(segment["end"]) - float(following["start"])) > 1e-6:
                raise ValueError("avatar continuation requires an adjacent bottom window")
            other = validate_avatar(following["visual_strategy"]["composition"].get("avatar"),
                                    frames=round((following["end"] - following["start"]) * 24))
            if ("entrance" in other or avatar["profile"] != other["profile"]
                    or avatar["position"] != other["position"]
                    or avatar["crop"]["size"] != other["crop"]["size"]):
                raise ValueError("avatar continuation must keep the same framing without another entrance")
        elif animated and next_window:
            raise ValueError("adjacent avatar windows require continuation to avoid a fade")
        profile = avatar["profile"]
        if source_sha256 is not None and profile["source_sha256"] != source_sha256:
            raise ValueError("avatar source differs from the edited A-roll")
        if shared is not None and profile != shared:
            raise ValueError("avatar profile must be shared across all B-roll segments")
        shared = profile
        previous = segment
    if animated:
        _validate_short_aroll_gaps(segments)


def _avatar_composition(segment):
    return segment.get("visual_strategy", {}).get("composition", {})


def _bottom_window_position(avatar):
    profile = avatar.get("profile") if isinstance(avatar, dict) else None
    if not isinstance(profile, dict):
        raise ValueError("avatar profile is required for bottom_window policy")
    diameter = _integer(profile.get("diameter"), 128, 384, "diameter")
    border = _integer(profile.get("border_width"), 0, 24, "border width")
    outer = diameter + border * 2
    return {"x": 1080 - 80 - outer, "y": 1700 - outer}


def validate_avatar_plan_policy(segments):
    """Validate the new-job transition policy without relying on optional fields.

    This is intentionally separate from the historical contract validator.  It
    checks the arrangement of every independent avatar group, including groups
    whose avatar object has no animation keys yet.
    """
    errors = []
    for i, segment in enumerate(segments):
        composition = _avatar_composition(segment)
        if composition.get("presenter_mode") != "bottom_window":
            continue
        avatar = composition.get("avatar") or {}
        if avatar.get("position") != _bottom_window_position(avatar):
            errors.append(f"segment {i}: bottom_window avatar must use the right-bottom policy position")
        before = _avatar_composition(segments[i - 1]) if i else {}
        after = _avatar_composition(segments[i + 1]) if i + 1 < len(segments) else {}
        has_before = (before.get("presenter_mode") == "full_frame"
                      and float(segments[i - 1]["end"]) == float(segment["start"]))
        has_after = (after.get("presenter_mode") == "full_frame"
                     and float(segment["end"]) == float(segments[i + 1]["start"]))
        next_is_br = (after.get("presenter_mode") == "bottom_window"
                      and float(segment["end"]) == float(segments[i + 1]["start"]))
        expected = set()
        if has_before:
            expected.add("entrance")
        if next_is_br:
            expected.add("continuation")
        elif has_after:
            expected.add("exit")
        for key in ("entrance", "exit", "continuation"):
            if (key in avatar) != (key in expected):
                errors.append(f"segment {i}: avatar {key} does not match its adjacent modes")
    if errors:
        raise ValueError("; ".join(errors))
    validate_plan_avatars(segments)
    _validate_short_aroll_gaps(segments)
    return True


def plan_avatar_policy(segments):
    """Return a normalized copy and preparation actions for a new proposal.

    Measured crop/profile geometry is copied verbatim; bottom-window placement
    is normalized to the right-bottom policy. Short native A-roll gaps are actions, not
    silently shortened timestamps, because their host inputs must be rebuilt.
    """
    planned = copy.deepcopy(segments)
    actions = []
    for i, segment in enumerate(planned):
        composition = _avatar_composition(segment)
        if composition.get("presenter_mode") != "bottom_window" or "avatar" not in composition:
            continue
        avatar = composition["avatar"]
        avatar["position"] = _bottom_window_position(avatar)
        before = _avatar_composition(planned[i - 1]) if i else {}
        after = _avatar_composition(planned[i + 1]) if i + 1 < len(planned) else {}
        has_before = (before.get("presenter_mode") == "full_frame" and
                      float(planned[i - 1]["end"]) == float(segment["start"]))
        has_after = (after.get("presenter_mode") == "full_frame" and
                     float(segment["end"]) == float(planned[i + 1]["start"]))
        if has_before:
            avatar.setdefault("entrance", {"kind": "aroll_to_avatar", "frames": 12})
        next_is_br = (after.get("presenter_mode") == "bottom_window" and
                      float(segment["end"]) == float(planned[i + 1]["start"]))
        if next_is_br:
            avatar["continuation"] = True
            avatar.pop("exit", None)
        elif has_after:
            avatar.pop("continuation", None)
            avatar.setdefault("exit", {"kind": "avatar_to_aroll", "frames": 8})
        else:
            avatar.pop("continuation", None)
            avatar.pop("exit", None)
        if not has_before:
            avatar.pop("entrance", None)
    index = 0
    while index < len(planned):
        if _avatar_composition(planned[index]).get("presenter_mode") != "full_frame":
            index += 1
            continue
        first = index
        while index < len(planned) and _avatar_composition(planned[index]).get("presenter_mode") == "full_frame":
            index += 1
        run = planned[first:index]
        if first and index < len(planned):
            left, right = _avatar_composition(planned[first - 1]), _avatar_composition(planned[index])
            frames = round((float(run[-1]["end"]) - float(run[0]["start"])) * 24)
            if (left.get("presenter_mode") == right.get("presenter_mode") == "bottom_window"
                    and not any(s.get("visual_strategy", {}).get("components") for s in run)
                    and frames < 24):
                left_segment = planned[first - 1]
                actions.append({"kind": "prepare_visual_inputs",
                                "left_segment_id": left_segment["segment_id"],
                                "absorbed_segment_ids": [s["segment_id"] for s in run],
                                "right_segment_id": planned[index]["segment_id"],
                                "old_start": left_segment["start"], "old_end": left_segment["end"],
                                "target_start": left_segment["start"], "target_end": run[-1]["end"],
                                "right_start": planned[index]["start"],
                                "requires": ["brief_duration", "binding", "full_script_reference",
                                              "reading_window", "real_avatar_sampling"],
                                "reason": "hold the prior native end state; preserve voice clock and row ids"})
    if not actions:
        validate_avatar_plan_policy(planned)
    return {"segments": planned, "actions": actions}


def _validate_short_aroll_gaps(segments):
    """Measure complete full-frame runs, including their adjacent overlays."""
    def mode(segment):
        return segment["visual_strategy"]["composition"]["presenter_mode"]
    index = 0
    while index < len(segments):
        if mode(segments[index]) != "full_frame":
            index += 1
            continue
        first = index
        while index < len(segments) and mode(segments[index]) == "full_frame":
            index += 1
        run = segments[first:index]
        if (first > 0 and index < len(segments)
                and mode(segments[first - 1]) == mode(segments[index]) == "bottom_window"
                and not any(s["visual_strategy"].get("components") for s in run)
                and round((run[-1]["end"] - run[0]["start"]) * 24) < 24):
            raise ValueError("short empty A-roll gap must stay in the avatar group instead of zooming twice")


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


def _still_filter_chain(avatar, *, frames, fade_out=True):
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


def _morph_filter(value, *, start, end, progress, source_frame, label):
    """Sample the same local A-roll while changing its rounded viewport."""
    profile, crop, position = value["profile"], value["crop"], value["position"]
    diameter, border = profile["diameter"], profile["border_width"]
    outer = diameter + border * 2
    crop_x = re.sub(r"\bn\b", source_frame, _axis_expression(crop["anchors"], "x"))
    crop_y = re.sub(r"\bn\b", source_frame, _axis_expression(crop["anchors"], "y"))
    # Each geq channel owns its local registers. Centers use pixel boundaries;
    # the +/- .5 in inverse sampling preserves the identity at frame zero.
    setup = (
        f"st(0,{progress});st(0,ld(0)*ld(0)*(3-2*ld(0)));"
        f"st(1,1080+({outer}-1080)*ld(0));"
        f"st(2,1920+({outer}-1920)*ld(0));"
        f"st(3,540+({position['x'] + outer / 2}-540)*ld(0));"
        f"st(4,960+({position['y'] + outer / 2}-960)*ld(0));"
        "st(5,ld(0)*min(ld(1),ld(2))/2);"
        "st(6,abs(X-ld(3))-ld(1)/2+ld(5));"
        "st(7,abs(Y-ld(4))-ld(2)/2+ld(5));"
        "st(8,hypot(max(ld(6),0),max(ld(7),0))+min(max(ld(6),ld(7)),0)-ld(5));"
        f"st(9,1+({diameter / crop['size']:.12f}-1)*ld(0));"
    )
    sx = f"540+(({crop_x})+{crop['size']/2}-540)*ld(0)+(X+.5-ld(3))/ld(9)-.5"
    sy = f"960+(({crop_y})+{crop['size']/2}-960)*ld(0)+(Y+.5-ld(4))/ld(9)-.5"
    rgb = [int(profile["border_color"][i:i+2], 16) for i in (1, 3, 5)]
    channels = []
    for channel, color in zip(("r", "g", "b"), rgb):
        expr = setup + f"if(lte(ld(8),-2*ld(0)),if(lte(ld(8),-({border}+2)*ld(0)),{channel}({sx},{sy}),{color}),0)"
        channels.append(f"{channel}='{expr}'")
    alpha = setup + "if(eq(ld(0),0),255,if(lte(ld(8),-2*ld(0)),255,0))"
    return (
        f"[0:v]fps=24,trim=start_frame={start}:end_frame={end},setpts=PTS-STARTPTS,"
        "format=rgba,geq=" + ":".join([*channels, "a='" + alpha + "'"])
        + f",setsar=1[{label}]"
    )


def _entrance_filter_chain(value, *, frames, fade_out):
    """Morph one synchronous A-roll into its calibrated circle, then reuse it."""
    denominator = value["entrance"]["frames"] - 1
    position = value["position"]
    dynamic = _morph_filter(value, start=0, end=denominator,
                            progress=f"N/{denominator}", source_frame="N", label="avatar_entrance")
    # Crop anchors and original exit fade run on the unmodified local clock.
    # The final entrance frame is the existing static path, eliminating a
    # bilinear/lanczos handoff at the settled circle.
    filters = [line.replace("[presenter]", "[avatar_static]")
               for line in _still_filter_chain(value, frames=frames, fade_out=fade_out)]
    filters.extend([
        dynamic,
        f"[avatar_static]pad=1080:1920:{position['x']}:{position['y']}:color=black@0,"
        f"trim=start_frame={denominator}:end_frame={frames},setpts=PTS-STARTPTS[avatar_hold]",
        "[avatar_entrance][avatar_hold]concat=n=2:v=1:a=0,format=rgba[presenter]",
    ])
    return filters


def _exit_filter_chain(value, *, frames):
    """Keep the circle's handoff frame, then expand into synchronous A-roll."""
    start = frames - value["exit"]["frames"]
    denominator = value["exit"]["frames"] - 1
    if "entrance" in value:
        base = _entrance_filter_chain(value, frames=frames, fade_out=False)
        pad = ""
    else:
        base = _still_filter_chain(value, frames=frames, fade_out=False)
        position = value["position"]
        pad = f"pad=1080:1920:{position['x']}:{position['y']}:color=black@0,"
    filters = [line.replace("[presenter]", "[avatar_before_exit]") for line in base]
    filters.extend([
        f"[avatar_before_exit]{pad}trim=start_frame=0:end_frame={start + 1},"
        "setpts=PTS-STARTPTS[avatar_until_exit]",
        _morph_filter(value, start=start + 1, end=frames,
                      progress=f"1-(N+1)/{denominator}", source_frame=f"(N+{start + 1})",
                      label="avatar_exit"),
        "[avatar_until_exit][avatar_exit]concat=n=2:v=1:a=0,format=rgba[presenter]",
    ])
    return filters


def filter_chain(avatar, *, frames, fade_out=True):
    value = validate_avatar(avatar, frames=frames)
    if "continuation" in value:
        fade_out = False
    if "exit" in value:
        return _exit_filter_chain(value, frames=frames)
    if "entrance" in value:
        return _entrance_filter_chain(value, frames=frames, fade_out=fade_out)
    return _still_filter_chain(value, frames=frames, fade_out=fade_out)

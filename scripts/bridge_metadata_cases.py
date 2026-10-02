"""Undoable palette/tag and native GIF/lossless APNG GUI regressions. GPLv2."""
import base64
import struct
import zlib
from animation_checks import read_apng, read_gif


def test_palettes_tags_animation(client, assets, smoke):
    directory = assets / "metadata-assets"
    directory.mkdir()
    document = client.request("create", {"width": 8, "height": 8, "name": "Palette/tag/export tests"})
    document_id = document["documentId"]
    base = document["layers"][0]["layerId"]
    red = {"r": 220, "g": 50, "b": 60, "a": 255}
    green = {"r": 40, "g": 180, "b": 100, "a": 255}
    blue = {"r": 60, "g": 100, "b": 220, "a": 255}

    def current():
        return client.request("inspect", {"documentId": document_id})

    def mutate(method, params=None, error=None):
        before = current()
        result = client.request(method, {"documentId": document_id, "expectedRevision": before["revision"], **(params or {})}, expected_error=error)
        if error:
            assert current() == before, (method, error)
        return result

    def render(frame, scale=1):
        result = client.request("render", {"documentId": document_id, "frame": frame, "scale": scale})
        path = directory / "render.png"
        path.write_bytes(base64.b64decode(result["pngBase64"]))
        return smoke.read_png(path)

    def packed(color):
        return sum(color[channel] << (index * 8) for index, channel in enumerate(("r", "g", "b", "a")))

    for index in (1, 2):
        mutate("add_frame", {"index": index, "durationMs": [100, 157, 201][index]})
    for frame, color in enumerate((red, green, blue)):
        mutate("draw_stroke", {"layerId": base, "frame": frame, "points": [{"x": 1 + frame * 2, "y": 1}], "color": color})
    before_pixels = [render(frame) for frame in range(3)]
    selection = (current()["activeLayerId"], current()["activeFrame"])
    original = current()["palettes"]
    mutate("set_palette", {"frame": 0, "size": 4, "entries": [{"index": 1, "color": red}, {"index": 2, "color": green}]})
    baseline = current()["palettes"]
    assert len(baseline[0]["rgbaPacked"]) == 4 and baseline[0]["rgbaPacked"][1] == packed(red)
    mutate("set_palette", {"frame": 1, "entries": [{"index": 1, "color": blue}]})
    changed = current()["palettes"]
    assert len(changed) == 2 and changed[0] == baseline[0] and changed[1]["frame"] == 1
    assert changed[1]["rgbaPacked"][1] == packed(blue)
    for _ in range(3):
        mutate("undo")
        assert current()["palettes"] == baseline
        mutate("redo")
        assert current()["palettes"] == changed
    mutate("remove_palette", {"frame": 1})
    for _ in range(3):
        assert current()["palettes"] == baseline
        mutate("undo")
        assert current()["palettes"] == changed
        mutate("redo")
    mutate("undo")  # Restore keyframe and modify EXACT existing key.
    mutate("set_palette", {"frame": 1, "size": 5, "entries": [{"index": 4, "color": green}]})
    expanded = current()["palettes"]
    assert len(expanded) == 2 and expanded[0] == baseline[0] and expanded[1]["rgbaPacked"][4] == packed(green)
    mutate("undo")
    assert current()["palettes"] == changed
    mutate("redo")
    assert current()["palettes"] == expanded
    mutate("set_palette", {"frame": 2, "entries": [{"index": 4, "color": green}]})
    assert current()["palettes"] == expanded  # Identical inherited request creates no key.
    revision = current()["revision"]
    mutate("set_palette", {"frame": 1, "size": 5, "entries": [{"index": 4, "color": green}]})
    assert current()["revision"] == revision
    assert [render(frame) for frame in range(3)] == before_pixels  # RGBA swatches don't recolor pixels.
    assert (current()["activeLayerId"], current()["activeFrame"]) == selection
    mutate("remove_palette", {"frame": 0}, "BASE_PALETTE")
    mutate("remove_palette", {"frame": 2}, "PALETTE_NOT_FOUND")
    for params in ({"frame": 0}, {"frame": 0, "entries": []}, {"frame": 0, "size": 0}, {"frame": 0, "size": 257}, {"frame": 0, "entries": [{"index": 5, "color": red}]}, {"frame": 0, "entries": [{"index": 1, "color": red}, {"index": 1, "color": blue}]}):
        mutate("set_palette", params, "INVALID_PARAMS")
    mutate("add_frame", {"index": 3}, "UNSUPPORTED_PALETTES")
    mutate("remove_frame", {"frame": 2}, "UNSUPPORTED_PALETTES")
    print("PASS: exact/inherited palette edits, RGBA swatches, sparse resize, no-ops, repeated native undo/redo, key removal, structural palette guards.")

    created = mutate("create_tag", {"name": "Walk", "from": 0, "to": 2, "color": red})
    tag_id = created["createdTagId"]
    tag = current()["tags"][0]
    assert tag["tagId"] == tag_id and tag["direction"] == 0 and tag["color"] == packed(red)
    changed_tag = mutate("update_tag", {"tagId": tag_id, "name": "Bounce", "from": 1, "to": 2, "direction": "pingpong", "color": green})["tags"][0]
    assert changed_tag["name"] == "Bounce" and changed_tag["from"] == 1 and changed_tag["direction"] == 2
    mutate("undo")
    assert current()["tags"] == [tag]
    mutate("redo")
    assert current()["tags"] == [changed_tag]
    revision = current()["revision"]
    mutate("update_tag", {"tagId": tag_id, "name": "Bounce", "from": 1, "to": 2, "direction": "pingpong", "color": green})
    assert current()["revision"] == revision
    mutate("remove_tag", {"tagId": tag_id})
    assert not current()["tags"]
    for _ in range(3):
        mutate("undo")
        assert current()["tags"] == [changed_tag]
        mutate("redo")
        assert not current()["tags"]
    mutate("undo")
    for params, code in (({"tagId": tag_id}, "INVALID_PARAMS"), ({"tagId": tag_id, "from": 2, "to": 1}, "INVALID_PARAMS"), ({"tagId": tag_id, "name": "Changed", "to": 3}, "INVALID_PARAMS"), ({"tagId": tag_id, "direction": "bad"}, "INVALID_PARAMS"), ({"tagId": tag_id, "color": {**blue, "a": 0}}, "INVALID_PARAMS"), ({"tagId": 2147483647, "name": "No"}, "TAG_NOT_FOUND")):
        mutate("update_tag", params, code)
    mutate("create_tag", {"name": "Invalid", "from": 2, "to": 0}, "INVALID_PARAMS")
    mutate("remove_tag", {"tagId": 2147483647}, "TAG_NOT_FOUND")
    duplicate = mutate("create_tag", {"name": "Bounce", "from": 0, "to": 0})["createdTagId"]
    assert duplicate != tag_id and len(current()["tags"]) == 2
    mutate("remove_tag", {"tagId": duplicate})
    assert (current()["activeLayerId"], current()["activeFrame"]) == selection
    mutate("save", {"path": "metadata-assets/metadata.ase"})
    saved = current()
    print("PASS: native tag IDs, atomic name/range/direction/color, no-ops, duplicate-name IDs, delete/restore with stable IDs, no selection changes.")

    guarded = {
        "set_palette": {"frame": 0, "entries": [{"index": 1, "color": blue}]},
        "remove_palette": {"frame": 1},
        "create_tag": {"name": "Guarded", "from": 0, "to": 1},
        "update_tag": {"tagId": tag_id, "name": "Guarded"},
        "remove_tag": {"tagId": tag_id},
        "export_animation": {"path": "metadata-assets/guarded.apng", "format": "apng"},
    }
    for method, params in guarded.items():
        mutate(method, {**params, "expectedRevision": current()["revision"] + 1}, "STALE_REVISION")
        mutate(method, {**params, "sessionId": "other-process"}, "SESSION_MISMATCH")
    client.request("set_paused", {"paused": True})
    for method, params in guarded.items():
        mutate(method, params, "PAUSED")
    client.request("set_paused", {"paused": False})
    assert not (directory / "guarded.apng").exists()

    def exported(format, filename, **options):
        result = mutate("export_animation", {"format": format, "path": "metadata-assets/" + filename, **options})
        assert result["revision"] == current()["revision"] and "pngBase64" not in result
        assert result["bytes"] == (directory / filename).stat().st_size
        return result, read_apng(directory / filename, smoke) if format == "apng" else read_gif(directory / filename)

    result, apng = exported("apng", "all.apng", scale=2)
    assert apng["plays"] == 0 and apng["durations"] == [100, 157, 201]
    assert apng["frames"] == [render(frame, 2) for frame in range(3)]
    assert [item["encodedDurationMs"] for item in result["animationFrames"]] == apng["durations"]
    subset_result, subset = exported("apng", "subset.apng", frames=[2, 0, 2], loop=False)
    assert subset["plays"] == 1 and subset["frames"] == [before_pixels[i] for i in (2, 0, 2)]
    assert [item["frame"] for item in subset_result["animationFrames"]] == [2, 0, 2]
    gif_result, gif = exported("gif", "all.gif", scale=2)
    assert gif["plays"] == 0 and gif["durations"] == [100, 150, 200]
    assert [item["encodedDurationMs"] for item in gif_result["animationFrames"]] == gif["durations"]
    assert gif["frames"] == apng["frames"]  # Small opaque/transparent color set is lossless in GIF too.
    _, gif_once = exported("gif", "once.gif", frames=[2, 0, 2], loop=False)
    assert gif_once["plays"] == 1 and gif_once["frames"] == subset["frames"]
    assert current() == saved  # Export does not mark saved or change history/selection/palettes/options.
    for format in ("apng", "gif"):
        path = "metadata-assets/all." + format
        old_bytes = (assets / path).read_bytes()
        mutate("export_animation", {"format": format, "path": path}, "FILE_EXISTS")
        assert (assets / path).read_bytes() == old_bytes
        mutate("export_animation", {"format": format, "path": path, "overwrite": True})
        (directory / ("link." + format)).symlink_to(directory / ("all." + format))
        (directory / ("folder." + format)).mkdir()
        for target_path, error in (("../escape." + format, "PATH_OUTSIDE_ROOT"), ("metadata-assets/link." + format, "INVALID_PATH"), ("metadata-assets/folder." + format, "INVALID_PATH"), ("metadata-assets/mismatch.png", "INVALID_PATH")):
            mutate("export_animation", {"format": format, "path": target_path, "overwrite": True}, error)
    for params, error in (({"frames": [], "format": "apng"}, "INVALID_PARAMS"), ({"frames": [3], "format": "apng"}, "INVALID_PARAMS"), ({"tagId": tag_id, "frames": [0], "format": "apng"}, "INVALID_PARAMS"), ({"tagId": 2147483647, "format": "apng"}, "TAG_NOT_FOUND"), ({"format": "webm"}, "INVALID_PARAMS"), ({"format": "apng", "scale": 17}, "INVALID_PARAMS")):
        mutate("export_animation", {"path": "metadata-assets/invalid.apng", **params}, error)
    assert not (directory / "invalid.apng").exists()
    mutate("update_tag", {"tagId": tag_id, "from": 0, "to": 2})
    for direction, order in (("forward", [0, 1, 2]), ("reverse", [2, 1, 0]), ("pingpong", [0, 1, 2, 1])):
        mutate("update_tag", {"tagId": tag_id, "direction": direction})
        for format in ("apng", "gif"):
            metadata, decoded = exported(format, direction + "." + format, tagId=tag_id)
            assert [item["frame"] for item in metadata["animationFrames"]] == order
            assert decoded["frames"] == [before_pixels[i] for i in order]
    mutate("update_tag", {"tagId": tag_id, "from": 1, "to": 1})
    _, single = exported("apng", "single.apng", tagId=tag_id)
    assert single["frames"] == [before_pixels[1]]
    # Native rendering of semitransparency is preserved by APNG, binary in GIF.
    mutate("draw_stroke", {"layerId": base, "frame": 1, "points": [{"x": 3, "y": 1}], "color": {**green, "a": 128}})
    mutate("draw_stroke", {"layerId": base, "frame": 1, "points": [{"x": 5, "y": 1}], "color": {**blue, "a": 127}})
    _, alpha_apng = exported("apng", "alpha.apng", frames=[1])
    assert alpha_apng["frames"] == [render(1)]
    _, alpha_gif = exported("gif", "alpha.gif", frames=[1])
    assert alpha_gif["frames"][0][2][(1 * 8 + 3) * 4:(1 * 8 + 3) * 4 + 4] == bytes(green.values())
    assert alpha_gif["frames"][0][2][(1 * 8 + 5) * 4:(1 * 8 + 5) * 4 + 4] == bytes(4)
    mutate("set_frame_duration", {"frame": 1, "durationMs": 1})
    mutate("export_animation", {"format": "gif", "path": "metadata-assets/short.gif"}, "UNSUPPORTED_TIMING")
    _, short = exported("apng", "short.apng", frames=[1])
    assert short["durations"] == [1]
    mutate("set_frame_duration", {"frame": 1, "durationMs": 65535})
    _, longest = exported("apng", "long.apng", frames=[1])
    assert longest["durations"] == [65535]
    assert not list(assets.glob(".libresprite-gif-*")) and not list(directory.glob(".libresprite-export-*"))
    print("PASS: native GIF pixels/disposal/transparency/quantized timing, lossless RGBA APNG chunks/CRC/sequence/exact delays, tag playback order, once/forever, atomic file guards.")

    reopened = client.request("open", {"path": "metadata-assets/metadata.ase"})
    assert reopened["palettes"] == saved["palettes"]
    assert [{k: v for k, v in item.items() if k != "tagId"} for item in reopened["tags"]] == [{k: v for k, v in item.items() if k != "tagId"} for item in saved["tags"]]
    for method, params in guarded.items():
        mutate(method, params, "INACTIVE_DOCUMENT")
    large = client.request("create", {"width": 1024, "height": 1024, "name": "Animation bounds"})
    for format in ("apng", "gif"):
        for options in ({"scale": 2}, {"frames": [0] * 9}):
            client.request("export_animation", {"documentId": large["documentId"], "expectedRevision": large["revision"], "format": format, "path": "metadata-assets/large." + format, **options}, expected_error="LIMIT_EXCEEDED")
            assert not (directory / ("large." + format)).exists()

    # Indexed PNG: palette edits recolor without altering indices; shrink checks
    # hidden cels and an inherited interval, not just the visible current frame.
    png = directory / "indexed.png"
    png.write_bytes(smoke.SIGNATURE + smoke.chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, 3, 0, 0, 0)) + smoke.chunk(b"PLTE", bytes((0, 0, 0, 220, 50, 60))) + smoke.chunk(b"tRNS", bytes((0, 255))) + smoke.chunk(b"IDAT", zlib.compress(bytes((0, 0, 1)))) + smoke.chunk(b"IEND", b""))
    indexed = client.request("open", {"path": "metadata-assets/indexed.png"})
    document_id = indexed["documentId"]
    assert indexed["colorMode"] == "indexed"
    original_render = render(0)
    mutate("add_frame", {"index": 1, "copyFrom": 0})
    mutate("set_palette", {"frame": 1, "entries": [{"index": 1, "color": green}]})
    assert render(0) == original_render and render(1)[2] == bytes(4) + bytes(green.values())
    mutate("set_palette", {"frame": 0, "size": 1}, "PALETTE_INDEX_IN_USE")
    mutate("set_palette", {"frame": 1, "size": 1}, "PALETTE_INDEX_IN_USE")
    mutate("update_layer", {"layerId": indexed["layers"][0]["layerId"], "visible": False})
    mutate("set_palette", {"frame": 1, "size": 1}, "PALETTE_INDEX_IN_USE")
    mutate("undo")
    mutate("remove_palette", {"frame": 1})
    assert render(1) == original_render
    mutate("undo")
    assert render(1)[2] == bytes(4) + bytes(green.values())
    mutate("save", {"path": "metadata-assets/indexed.ase"})
    palette_saved = current()["palettes"]
    reindexed = client.request("open", {"path": "metadata-assets/indexed.ase"})
    assert reindexed["palettes"] == palette_saved
    # Hidden nested off-canvas cel uses index 2 only in a larger later palette.
    # Removing that keyframe must not strand the cel under the smaller base.
    def ase_chunk(kind, data):
        return struct.pack("<IH", len(data) + 6, kind) + data

    def ase_layer(name, kind, depth):
        return ase_chunk(0x2004, struct.pack("<6H", 2, kind, depth, 1, 1, 0) + b"\xff\0\0\0" + struct.pack("<H", len(name)) + name)

    frames = []
    for frame in range(2):
        chunks = [ase_layer(b"Hidden group", 1, 0), ase_layer(b"Hidden child", 0, 1)] if frame == 0 else []
        colors = [{"r": 0, "g": 0, "b": 0, "a": 0}, red] + ([green] if frame else [])
        palette_data = struct.pack("<III", len(colors), 0, len(colors) - 1) + bytes(8) + b"".join(struct.pack("<H", 0) + bytes(color.values()) for color in colors)
        chunks.append(ase_chunk(0x2019, palette_data))
        cel_data = struct.pack("<HhhBH", 1, 5, 5, 255, 2) + bytes(7) + struct.pack("<HH", 1, 1) + zlib.compress(bytes((2 if frame else 1,)))
        chunks.append(ase_chunk(0x2005, cel_data))
        payload = b"".join(chunks)
        frames.append(struct.pack("<IHHH", 16 + len(payload), 0xF1FA, len(chunks), 100) + bytes(6) + payload)
    header = bytearray(128)
    struct.pack_into("<IHHHHHIH", header, 0, 128 + sum(map(len, frames)), 0xA5E0, 2, 1, 1, 8, 1, 100)
    struct.pack_into("<H", header, 32, 2)
    header[34] = header[35] = 1
    (directory / "hidden.ase").write_bytes(header + b"".join(frames))
    hidden = client.request("open", {"path": "metadata-assets/hidden.ase"})
    document_id = hidden["documentId"]
    assert [len(palette["rgbaPacked"]) for palette in hidden["palettes"]] == [2, 3]
    assert hidden["layers"][1]["parentId"] == hidden["layers"][0]["layerId"]
    mutate("remove_palette", {"frame": 1}, "PALETTE_INDEX_IN_USE")
    mutate("set_palette", {"frame": 1, "size": 2}, "PALETTE_INDEX_IN_USE")
    assert render(1)[2] == bytes(4)
    # A grayscale palette is a fixed ramp, not editable swatches.
    (directory / "gray.png").write_bytes(smoke.SIGNATURE + smoke.chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)) + smoke.chunk(b"IDAT", zlib.compress(bytes((0, 100)))) + smoke.chunk(b"IEND", b""))
    gray = client.request("open", {"path": "metadata-assets/gray.png"})
    document_id = gray["documentId"]
    assert gray["colorMode"] == "grayscale"
    mutate("set_palette", {"frame": 0, "entries": [{"index": 1, "color": red}]}, "UNSUPPORTED_COLOR_MODE")
    for index in range(128):
        mutate("create_tag", {"name": "Limit tag", "from": 0, "to": 0})
    mutate("create_tag", {"name": "One too many", "from": 0, "to": 0}, "LIMIT_EXCEEDED")
    mutate("remove_tag", {"tagId": current()["tags"][0]["tagId"]})
    assert len(current()["tags"]) == 127
    mutate("undo")
    assert len(current()["tags"]) == 128
    # Maximum pingpong tag expands to 510 emitted steps, not 256, and blank
    # native GIF frames must still retain their timing and transparency.
    blank_frames = []
    for frame in range(256):
        chunks = [ase_layer(b"Blank", 0, 0)] if frame == 0 else []
        payload = b"".join(chunks)
        blank_frames.append(struct.pack("<IHHH", 16 + len(payload), 0xF1FA, len(chunks), 100) + bytes(6) + payload)
    blank_header = bytearray(128)
    struct.pack_into("<IHHHHHIH", blank_header, 0, 128 + sum(map(len, blank_frames)), 0xA5E0, 256, 1, 1, 32, 1, 100)
    blank_header[34] = blank_header[35] = 1
    (directory / "blank-256.ase").write_bytes(blank_header + b"".join(blank_frames))
    blank = client.request("open", {"path": "metadata-assets/blank-256.ase"})
    document_id = blank["documentId"]
    maximum_tag = mutate("create_tag", {"name": "Maximum pingpong", "from": 0, "to": 255, "direction": "pingpong"})["createdTagId"]
    for format in ("apng", "gif"):
        metadata, decoded = exported(format, "blank-510." + format, tagId=maximum_tag)
        assert [item["frame"] for item in metadata["animationFrames"]] == list(range(256)) + list(range(254, 0, -1))
        assert decoded["frames"] == [(1, 1, bytes(4))] * 510 and decoded["durations"] == [100] * 510
    print("PASS: indexed recoloring, invalid-index/hidden-cel shrink guards, native palette/tag save/reopen, inactive/pause/session/revision and animation pixel limits.")

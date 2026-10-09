"""Layer, frame, and drawing regression cases for the disposable native GUI test."""
import base64
from bridge_animation_cases import canonical_inspection
import struct
import zlib


def test_layers_frames_drawing(client, assets, smoke):
    document = client.request("create", {"width": 16, "height": 16, "name": "Layers and animation"})
    document_id = document["documentId"]
    base = document["layers"][0]["layerId"]

    def current():
        return canonical_inspection(client.request("inspect", {"documentId": document_id}))

    def mutate(method, params=None, error=None):
        snapshot = current()
        result = client.request(method, {"documentId": document_id, "expectedRevision": snapshot["revision"], **(params or {})}, expected_error=error)
        if error:
            after = current()
            assert after["revision"] == snapshot["revision"], (method, snapshot, after)
            assert after["activeLayerId"] == snapshot["activeLayerId"] and after["activeFrame"] == snapshot["activeFrame"]
        return result

    def layer(layer_id):
        return next(item for item in current()["layers"] if item["layerId"] == layer_id)

    def render(frame=0, scale=1, doc_id=None):
        result = client.request("render", {"documentId": doc_id or document_id, "frame": frame, "scale": scale})
        image = assets / "workflow.png"
        image.write_bytes(base64.b64decode(result["pngBase64"]))
        return smoke.read_png(image)

    def rgba_at(pixels, x, y):
        offset = (y * 16 + x) * 4
        return tuple(pixels[offset:offset + 4])

    red = {"r": 220, "g": 50, "b": 60, "a": 255}
    green = {"r": 40, "g": 180, "b": 100, "a": 255}
    blue = {"r": 60, "g": 100, "b": 220, "a": 255}
    clear = {"r": 0, "g": 0, "b": 0, "a": 0}

    # Every new mutation uses the same session/pause/revision gates. These are
    # valid arguments so the safety refusal must happen before any operation.
    guarded = {
        "create_layer": {"name": "Guarded"},
        "update_layer": {"layerId": base, "name": "Guarded"},
        "move_layer": {"layerId": base, "afterLayerId": None},
        "remove_layer": {"layerId": base},
        "add_frame": {"index": 1},
        "remove_frame": {"frame": 0},
        "set_frame_duration": {"frame": 0, "durationMs": 80},
        "draw_shape": {"layerId": base, "frame": 0, "shape": "line", "x1": 0, "y1": 0, "x2": 1, "y2": 1, "color": red},
        "draw_stroke": {"layerId": base, "frame": 0, "points": [{"x": 0, "y": 0}], "color": red},
        "flood_fill": {"layerId": base, "frame": 0, "x": 0, "y": 0, "color": red},
    }
    for method, params in guarded.items():
        snapshot = current()
        client.request(method, {"documentId": document_id, "expectedRevision": snapshot["revision"] + 1, **params}, expected_error="STALE_REVISION")
        mutate(method, {**params, "sessionId": "other-process"}, "SESSION_MISMATCH")
    client.request("set_paused", {"paused": True})
    for method, params in guarded.items():
        mutate(method, params, "PAUSED")
    client.request("set_paused", {"paused": False})
    print("PASS: all ten new mutations respect session, pause, and stale-revision gates.")

    def shape(kind, x1, y1, x2, y2, color=red, filled=False, layer_id=None, frame=0):
        return mutate("draw_shape", {"layerId": layer_id or base, "frame": frame, "shape": kind, "x1": x1, "y1": y1, "x2": x2, "y2": y2, "color": color, "filled": filled})

    mutate("remove_layer", {"layerId": base}, "LAST_LAYER")
    mutate("remove_frame", {"frame": 0}, "LAST_FRAME")
    mutate("create_layer", {"name": "Invalid", "parentId": base}, "INVALID_PARAMS")
    blank = render()[2]
    shape("line", 1, 1, 5, 5)
    diagonal = render()[2]
    assert all(rgba_at(diagonal, x, y) == tuple(red.values()) if x == y and 1 <= x <= 5 else rgba_at(diagonal, x, y) == (0, 0, 0, 0) for y in range(16) for x in range(16))
    revision = current()["revision"]
    shape("line", 5, 5, 1, 1)  # An identical reversed line is not an undo step.
    assert current()["revision"] == revision
    mutate("undo")
    assert render()[2] == blank
    shape("rectangle", 8, 8, 3, 3, filled=False)
    outline = render()[2]
    assert rgba_at(outline, 3, 3) == tuple(red.values()) and rgba_at(outline, 5, 5) == (0, 0, 0, 0)
    mutate("flood_fill", {"layerId": base, "frame": 0, "x": 5, "y": 5, "color": green})
    filled = render()[2]
    assert rgba_at(filled, 5, 5) == tuple(green.values()) and rgba_at(filled, 0, 0) == (0, 0, 0, 0)
    assert rgba_at(filled, 3, 3) == tuple(red.values())
    mutate("undo")
    assert render()[2] == outline
    mutate("undo")
    assert render()[2] == blank
    shape("rectangle", 2, 2, 5, 5, green, filled=True)
    rectangle = render()[2]
    assert sum(rgba_at(rectangle, x, y) == tuple(green.values()) for y in range(16) for x in range(16)) == 16
    shape("rectangle", 3, 3, 4, 4, clear, filled=True)
    assert rgba_at(render()[2], 3, 3) == (0, 0, 0, 0)
    mutate("undo")
    assert render()[2] == rectangle
    mutate("undo")
    shape("ellipse", 2, 2, 12, 12, blue, filled=True)
    ellipse = render()[2]
    assert rgba_at(ellipse, 7, 7) == tuple(blue.values()) and rgba_at(ellipse, 2, 2) == (0, 0, 0, 0)
    mutate("undo")
    assert render()[2] == blank
    shape("ellipse", 12, 12, 2, 2, blue, filled=False)
    assert rgba_at(render()[2], 7, 7) == (0, 0, 0, 0) and render()[2] != blank
    mutate("undo")
    shape("ellipse", 5, 5, 5, 5, blue, filled=True)
    assert rgba_at(render()[2], 5, 5) == tuple(blue.values())
    mutate("undo")
    mutate("draw_stroke", {"layerId": base, "frame": 0, "points": [{"x": 1, "y": 1}, {"x": 5, "y": 1}, {"x": 5, "y": 5}], "color": red})
    stroke = render()[2]
    assert sum(rgba_at(stroke, x, y) == tuple(red.values()) for y in range(16) for x in range(16)) == 9
    mutate("draw_stroke", {"layerId": base, "frame": 0, "points": [{"x": 1, "y": 1}, {"x": 16, "y": 0}], "color": red}, "INVALID_PARAMS")
    mutate("draw_shape", {"layerId": base, "frame": 0, "shape": "line", "x1": 0, "y1": 0, "x2": 5, "y2": 5, "color": red, "filled": True}, "INVALID_PARAMS")
    assert render()[2] == stroke
    mutate("undo")
    assert render()[2] == blank
    mutate("flood_fill", {"layerId": base, "frame": 0, "x": 0, "y": 0, "color": green})
    assert render()[2] == bytes(tuple(green.values())) * 256
    mutate("undo")
    mutate("draw_stroke", {"layerId": base, "frame": 0, "points": [{"x": 1, "y": 1}], "color": red})
    mutate("draw_stroke", {"layerId": base, "frame": 0, "points": [{"x": 8, "y": 8}], "color": red})
    mutate("flood_fill", {"layerId": base, "frame": 0, "x": 1, "y": 1, "color": blue, "contiguous": False})
    assert rgba_at(render()[2], 1, 1) == tuple(blue.values()) and rgba_at(render()[2], 8, 8) == tuple(blue.values())
    mutate("undo")
    mutate("flood_fill", {"layerId": base, "frame": 0, "x": 1, "y": 1, "color": {**blue, "a": 128}, "tolerance": 1})
    assert rgba_at(render()[2], 1, 1)[3] == 128
    mutate("undo")
    print("PASS: native lines/rectangles/ellipses/strokes/fills, alpha erasing, no-op history, atomic validation.")

    overlay = mutate("create_layer", {"name": "Overlay"})["createdLayerId"]
    assert current()["activeLayerId"] == overlay
    shape("rectangle", 0, 0, 15, 15, blue, filled=True, layer_id=overlay)
    assert render()[2] == bytes(tuple(blue.values())) * 256
    mutate("update_layer", {"layerId": overlay, "name": "Clouds", "opacity": 128, "visible": False})
    assert layer(overlay)["name"] == "Clouds" and layer(overlay)["opacity"] == 128 and not layer(overlay)["visible"]
    assert rgba_at(render()[2], 1, 1) == tuple(red.values())
    mutate("undo")
    assert layer(overlay)["name"] == "Overlay" and layer(overlay)["opacity"] == 255 and layer(overlay)["visible"]
    mutate("update_layer", {"layerId": overlay, "opacity": 128})
    assert rgba_at(render()[2], 0, 0)[3] == 128
    mutate("undo")
    mutate("move_layer", {"layerId": overlay, "afterLayerId": None})
    assert rgba_at(render()[2], 1, 1) == tuple(red.values())
    mutate("undo")
    assert rgba_at(render()[2], 1, 1) == tuple(blue.values())
    mutate("move_layer", {"layerId": overlay, "afterLayerId": overlay}, "INVALID_PARAMS")
    mutate("update_layer", {"layerId": overlay, "editable": False})
    mutate("draw_stroke", {"layerId": overlay, "frame": 0, "points": [{"x": 0, "y": 0}], "color": red}, "LAYER_LOCKED")
    mutate("update_layer", {"layerId": overlay, "editable": True, "name": "Sneaky"}, "LAYER_LOCKED")
    mutate("add_frame", {"index": 1}, "LAYER_LOCKED")
    mutate("update_layer", {"layerId": overlay, "editable": True})
    group = mutate("create_layer", {"name": "Group", "type": "group"})["createdLayerId"]
    subgroup = mutate("create_layer", {"name": "Nested", "type": "group", "parentId": group})["createdLayerId"]
    child = mutate("create_layer", {"name": "Child", "parentId": subgroup})["createdLayerId"]
    assert layer(child)["parentId"] == subgroup
    shape("line", 0, 0, 15, 15, green, layer_id=child)
    mutate("move_layer", {"layerId": child, "afterLayerId": overlay}, "INVALID_PARAMS")
    mutate("update_layer", {"layerId": group, "editable": False})
    mutate("draw_stroke", {"layerId": child, "frame": 0, "points": [{"x": 0, "y": 0}], "color": red}, "LAYER_LOCKED")
    mutate("create_layer", {"name": "Blocked", "parentId": group}, "LAYER_LOCKED")
    mutate("update_layer", {"layerId": child, "editable": True}, "LAYER_LOCKED")
    mutate("update_layer", {"layerId": group, "editable": True})
    grouped_pixels = render()[2]
    mutate("add_frame", {"index": 1, "copyFrom": 0})
    assert render(1)[2] == grouped_pixels
    assert all(cel["links"] == 0 for item in current()["layers"] for cel in item.get("cels", []))
    shape("line", 0, 0, 15, 15, red, layer_id=child, frame=1)
    grouped_frame_one = render(1)[2]
    assert grouped_frame_one != grouped_pixels and render(0)[2] == grouped_pixels
    mutate("remove_frame", {"frame": 1})
    assert all(cel["frame"] == 0 for item in current()["layers"] for cel in item.get("cels", []))
    mutate("undo")
    assert render(1)[2] == grouped_frame_one
    mutate("redo")
    mutate("save", {"path": "groups.ase"})
    reopened_groups = client.request("open", {"path": "groups.ase"})
    document_id = reopened_groups["documentId"]
    base = next(item["layerId"] for item in reopened_groups["layers"] if item["name"] == "Layer 1")
    overlay = next(item["layerId"] for item in reopened_groups["layers"] if item["name"] == "Overlay")
    group = next(item["layerId"] for item in reopened_groups["layers"] if item["name"] == "Group")
    subgroup = next(item["layerId"] for item in reopened_groups["layers"] if item["name"] == "Nested")
    child = next(item["layerId"] for item in reopened_groups["layers"] if item["name"] == "Child")
    assert layer(subgroup)["parentId"] == group and layer(child)["parentId"] == subgroup and render()[2] == grouped_pixels
    # Select the descendant before recursive deletion, then verify its restored
    # native undo selection never references a deleted layer.
    shape("line", 0, 0, 15, 15, red, layer_id=child)
    shape("line", 0, 0, 15, 15, green, layer_id=child)
    mutate("remove_layer", {"layerId": group}, "GROUP_NOT_EMPTY")
    mutate("remove_layer", {"layerId": group, "recursive": True})
    assert all(item["layerId"] not in (group, subgroup, child) for item in current()["layers"])
    mutate("undo")
    assert layer(child)["parentId"] == subgroup
    assert current()["activeLayerId"] == child
    mutate("redo")
    mutate("remove_layer", {"layerId": overlay})
    assert len(current()["layers"]) == 1
    mutate("undo")
    assert layer(overlay)["name"] == "Overlay"
    mutate("redo")
    mutate("remove_layer", {"layerId": base}, "LAST_LAYER")
    print("PASS: layer/group creation, properties, compositing, restacking, locks, subtree deletion and native undo/redo.")

    frame_zero = render()[2]
    mutate("set_frame_duration", {"frame": 0, "durationMs": 140})
    copied = mutate("add_frame", {"index": 0, "copyFrom": 0, "durationMs": 210})
    assert copied["insertedFrame"] == 0 and copied["activeFrame"] == 0
    assert [item["durationMs"] for item in current()["frames"]] == [210, 140]
    assert render(0)[2] == frame_zero and render(1)[2] == frame_zero
    assert all(cel["links"] == 0 for cel in layer(base)["cels"])
    shape("line", 0, 15, 15, 0, green, frame=0)
    frame_one = render(0)[2]
    assert frame_one != frame_zero and render(1)[2] == frame_zero
    mutate("undo")
    assert render(0)[2] == frame_zero
    mutate("undo")  # Undo the index-zero duplicate as one transaction.
    assert current()["frameCount"] == 1 and current()["frames"][0]["durationMs"] == 140
    mutate("redo")
    assert render(0)[2] == frame_zero and render(1)[2] == frame_zero
    mutate("add_frame", {"index": 1, "durationMs": 300})
    assert [item["durationMs"] for item in current()["frames"]] == [210, 300, 140]
    assert render(1)[2] == blank and render(2)[2] == frame_zero
    mutate("set_frame_duration", {"frame": 1, "durationMs": 75})
    revision = current()["revision"]
    mutate("set_frame_duration", {"frame": 1, "durationMs": 75})
    assert current()["revision"] == revision
    mutate("undo")
    assert current()["frames"][1]["durationMs"] == 300
    mutate("redo")
    mutate("remove_frame", {"frame": 0})
    assert [item["durationMs"] for item in current()["frames"]] == [75, 140]
    assert render(0)[2] == blank and render(1)[2] == frame_zero
    mutate("undo")
    assert [item["durationMs"] for item in current()["frames"]] == [210, 75, 140]
    mutate("redo")
    mutate("add_frame", {"index": 2, "copyFrom": 1})
    assert render(2)[2] == frame_zero and current()["frames"][2]["durationMs"] == 140
    mutate("set_frame_duration", {"frame": 0, "durationMs": 65536}, "INVALID_PARAMS")
    mutate("add_frame", {"index": 4}, "INVALID_PARAMS")
    mutate("save", {"path": "animation.ase"})
    expected_frames = [render(i)[2] for i in range(3)]
    reopened = client.request("open", {"path": "animation.ase"})
    assert [item["durationMs"] for item in reopened["frames"]] == [75, 140, 140]
    assert [render(i, doc_id=reopened["documentId"])[2] for i in range(3)] == expected_frames
    print("PASS: index-zero frame insertion, independent duplicates, blank/middle frames, durations, deletion, animation save/reopen.")

    # A small native ASE fixture makes tag-range regressions and palette guards
    # observable without adding an unrestricted script execution tool.
    def chunk(kind, payload):
        return struct.pack("<IH", len(payload) + 6, kind) + payload

    def native_fixture(path, per_frame_palette=False, linked=False, background=False):
        frames = []
        layer_chunk = struct.pack("<6H", 15 if background else 3, 0, 0, 16, 16, 0) + b"\xff\0\0\0" + struct.pack("<H", 4) + b"Base"
        name = b"Walk"
        tag_chunk = struct.pack("<H", 1) + bytes(8) + struct.pack("<HHB", 0, 1, 0) + bytes(8) + bytes((255, 0, 0, 0)) + struct.pack("<H", len(name)) + name
        for index in range(2):
            chunks = []
            if index == 0:
                chunks += [chunk(0x2004, layer_chunk), chunk(0x2018, tag_chunk)]
            cel_chunk = struct.pack("<HhhBH", 0, 0, 0, 255, 2) + bytes(7) + struct.pack("<HH", 16, 16) + zlib.compress(bytes(tuple(red.values())) * 256)
            if linked and index == 1:
                cel_chunk = struct.pack("<HhhBH", 0, 0, 0, 255, 1) + bytes(7) + struct.pack("<H", 0)
            chunks.append(chunk(0x2005, cel_chunk))
            if per_frame_palette:
                palette_chunk = struct.pack("<III", 256, 0, 0) + bytes(8) + struct.pack("<H", 0) + bytes((10 + index, 20, 30, 255))
                chunks.append(chunk(0x2019, palette_chunk))
            payload = b"".join(chunks)
            frames.append(struct.pack("<IHHH", 16 + len(payload), 0xF1FA, len(chunks), 100) + bytes(6) + payload)
        header = bytearray(128)
        struct.pack_into("<IHHHHHIH", header, 0, 128 + sum(map(len, frames)), 0xA5E0, 2, 16, 16, 32, 1, 100)
        header[34] = header[35] = 1
        path.write_bytes(bytes(header) + b"".join(frames))

    native_fixture(assets / "tagged.ase")
    tagged = client.request("open", {"path": "tagged.ase"})
    document_id = tagged["documentId"]
    assert tagged["tags"][0]["name"] == "Walk" and tagged["tags"][0]["to"] == 1
    mutate("add_frame", {"index": 1})
    assert current()["tags"][0]["to"] == 2
    mutate("undo")
    assert current()["tags"][0]["to"] == 1
    mutate("add_frame", {"index": 0, "copyFrom": 0})
    assert current()["tags"][0]["from"] == 1 and current()["tags"][0]["to"] == 2
    mutate("remove_frame", {"frame": 1})
    assert current()["tags"][0]["from"] == 1 and current()["tags"][0]["to"] == 1
    mutate("remove_frame", {"frame": 1})
    assert current()["tags"] == []
    mutate("undo")
    assert current()["tags"][0]["name"] == "Walk"
    native_fixture(assets / "palettes.ase", True)
    palette_document = client.request("open", {"path": "palettes.ase"})
    document_id = palette_document["documentId"]
    assert len(palette_document["palettes"]) == 2
    mutate("add_frame", {"index": 1}, "UNSUPPORTED_PALETTES")
    mutate("remove_frame", {"frame": 0}, "UNSUPPORTED_PALETTES")
    print("PASS: existing tag-range maintenance/undo and refusal of unsupported per-frame palettes.")

    native_fixture(assets / "linked.ase", linked=True)
    linked_document = client.request("open", {"path": "linked.ase"})
    document_id = linked_document["documentId"]
    base = linked_document["layers"][0]["layerId"]
    assert all(cel["links"] > 0 for cel in layer(base)["cels"])
    paint_cases = {
        "draw_shape": {"shape": "rectangle", "x1": 0, "y1": 0, "x2": 3, "y2": 3},
        "draw_stroke": {"points": [{"x": 0, "y": 0}]},
        "flood_fill": {"x": 0, "y": 0},
    }
    for method, params in paint_cases.items():
        mutate(method, {"layerId": base, "frame": 1, "color": blue, **params}, "LINKED_CEL")
    original = render(0)[2]
    mutate("add_frame", {"index": 2, "copyFrom": 1})
    assert layer(base)["cels"][2]["links"] == 0 and render(2)[2] == original
    shape("line", 0, 0, 15, 15, blue, frame=2)
    assert render(2)[2] != original and render(0)[2] == original and render(1)[2] == original
    mutate("remove_frame", {"frame": 0})
    mutate("undo")
    assert render(0)[2] == original and render(1)[2] == original
    assert layer(base)["cels"][0]["links"] > 0 and layer(base)["cels"][2]["links"] == 0

    native_fixture(assets / "background.ase", background=True)
    background_document = client.request("open", {"path": "background.ase"})
    document_id = background_document["documentId"]
    base = background_document["layers"][0]["layerId"]
    assert layer(base)["background"]
    for method, params in paint_cases.items():
        mutate(method, {"layerId": base, "frame": 0, "color": blue, **params}, "UNSUPPORTED_LAYER")
    mutate("create_layer", {"name": "Below background", "afterLayerId": None}, "UNSUPPORTED_LAYER")
    foreground = mutate("create_layer", {"name": "Foreground"})["createdLayerId"]
    mutate("move_layer", {"layerId": foreground, "afterLayerId": None}, "UNSUPPORTED_LAYER")
    mutate("move_layer", {"layerId": base, "afterLayerId": foreground}, "UNSUPPORTED_LAYER")
    mutate("remove_layer", {"layerId": base}, "UNSUPPORTED_LAYER")
    mutate("add_frame", {"index": 1})
    assert layer(base)["cels"][1]["frame"] == 1  # Native blank background is opaque.
    mutate("undo")
    assert current()["frameCount"] == 2
    print("PASS: linked-cel drawing guards, independent copies of links, linked frame removal/undo, background invariants.")

    # Eight full RGBA canvases reach the working limit. A ninth independent
    # frame must roll back both its cels and its structural/native-history state.
    large = client.request("create", {"width": 1024, "height": 1024, "name": "Working limit rollback"})
    document_id = large["documentId"]
    base = large["layers"][0]["layerId"]
    mutate("flood_fill", {"layerId": base, "frame": 0, "x": 0, "y": 0, "color": green})
    for index in range(1, 8):
        mutate("add_frame", {"index": index, "copyFrom": 0})
    mutate("save", {"path": "working-limit.ase"})
    before = current()
    for index in (0, 4, 8):
        client.request("add_frame", {"documentId": document_id, "expectedRevision": current()["revision"], "index": index, "copyFrom": 0}, expected_error="LIMIT_EXCEEDED")
        after = current()
        # Native rollback can increment internal version counters. Inspect for a
        # fresh revision; assert actual state/history, not equal revision numbers.
        for key in ("frameCount", "frames", "activeLayerId", "activeFrame", "modified", "canUndo", "canRedo"):
            assert after[key] == before[key], (key, before[key], after[key])
        for key in ("cels", "name", "parentId"):
            assert after["layers"][0][key] == before["layers"][0][key], key
    mutate("undo")  # The failed requests did not create undo states.
    assert current()["frameCount"] == 7
    mutate("redo")
    assert current()["frameCount"] == 8 and not current()["modified"]
    assert render(7)[2] == bytes(tuple(green.values())) * (1024 * 1024)
    print("PASS: working-limit rollback preserves frames, cels, selection, saved state, and undo/redo history.")

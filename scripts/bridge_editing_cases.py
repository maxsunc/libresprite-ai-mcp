"""Step 3: real GUI canvas/layer/mask/brush/index regressions. GPL-2.0-only."""
import base64
import copy
import struct
from bridge_animation_cases import fixture, large_fixture, raw_frames


def test_editing_workflows(client, assets, smoke):
    original_ids = {doc["documentId"] for doc in client.request("list_documents")["documents"]}
    directory = assets / "editing-workflows"
    directory.mkdir()
    doc = client.request("create", {"width": 16, "height": 16, "name": "Editing tests"})
    document_id = doc["documentId"]
    base = doc["layers"][0]["layerId"]
    red = {"r": 220, "g": 50, "b": 60, "a": 255}
    blue = {"r": 30, "g": 150, "b": 210, "a": 128}

    def current():
        return client.request("inspect", {"documentId": document_id})

    def target():
        return {"documentId": document_id, "expectedRevision": current()["revision"]}

    def image(frame=0, mask=False):
        result = client.request("render_selection" if mask else "render", {"documentId": document_id, "frame": frame, "scale": 1, "mode": "mask"})
        path = directory / "preview.png"
        path.write_bytes(base64.b64decode(result["pngBase64"]))
        return smoke.read_png(path)

    def images():
        n = current()["frameCount"]
        return [image(i) for i in (range(n) if n <= 16 else (0, n // 2, n - 1))]

    def stable(state=None, undo=False):
        state = copy.deepcopy(state or current())
        for layer in state["layers"]:
            if undo:
                layer.pop("version")
            else:
                layer["version"] = max(1, layer["version"])
            for cel in layer.get("cels", []):
                if undo:
                    cel.pop("imageVersion")
                else:
                    cel["imageVersion"] = max(1, cel["imageVersion"])
        if undo:
            for key in ("revision", "canUndo", "canRedo", "activeFrame", "activeLayerId"):
                state.pop(key)
        return state

    def mutate(method, params=None, error=None):
        before = stable() if error else None
        pixels = images() if error else None
        result = client.request(method, {**target(), **(params or {})}, expected_error=error)
        if error:
            assert stable() == before, (method, error, before, current())
            assert images() == pixels, (method, error)
        return result

    def roundtrip(before, after, old_state=None):
        for _ in range(2):
            mutate("undo")
            assert images() == before
            if old_state is not None:
                assert stable(undo=True) == old_state
            mutate("redo")
            assert images() == after

    def layer(layer_id):
        return next(item for item in current()["layers"] if item["layerId"] == layer_id)

    def no_op(method, params):
        before = stable()
        mutate(method, params)
        assert stable() == before, method

    def native_save(name):
        mutate("save", {"path": "editing-workflows/" + name})
        return raw_frames(directory / name)

    def open_fixture(name, **options):
        nonlocal document_id, base
        fixture(directory / name, **options)
        doc = client.request("open", {"path": "editing-workflows/" + name})
        document_id = doc["documentId"]
        base = doc["layers"][0]["layerId"]
        return doc

    new_edits = [
        ("resize_canvas", {"width": 16, "height": 16}),
        ("crop_canvas", {"x": 0, "y": 0, "width": 16, "height": 16}),
        ("duplicate_layer", {"layerId": base}),
        ("reparent_layer", {"layerId": base, "parentId": None}),
        ("set_polygon_selection", {"vertices": [{"x": 1, "y": 1}, {"x": 3, "y": 1}, {"x": 2, "y": 3}]}),
        ("set_bitmap_selection", {"x": 1, "y": 1, "width": 1, "height": 1, "bits": "1"}),
        ("draw_brush_stroke", {"layerId": base, "frame": 0, "points": [{"x": 1, "y": 1}], "brush": {"width": 1, "height": 1, "bits": "1"}, "color": red}),
        ("set_indexed_pixels", {"layerId": base, "frame": 0, "pixels": [{"x": 1, "y": 1, "index": 1}]}),
    ]
    state = stable()
    for method, args in new_edits:
        mutate(method, {**args, "sessionId": "not-this-editor"}, "SESSION_MISMATCH")
        mutate(method, {**args, "expectedRevision": current()["revision"] + 1}, "STALE_REVISION")
    client.request("set_paused", {"paused": True})
    for method, args in new_edits:
        mutate(method, args, "PAUSED")
    client.request("set_paused", {"paused": False})
    assert stable() == state
    second = client.request("create", {"width": 16, "height": 16, "name": "Inactive guard"})
    for method, args in new_edits:
        mutate(method, args, "INACTIVE_DOCUMENT")
    client.request("activate_document", {**target(), "expectedActiveDocumentId": second["documentId"]})
    print("PASS: all eight new editing methods enforce session/current-revision/pause/active-document gates without data/history/focus changes.")

    # All frames, cropped/off-canvas image bytes, linked data moved exactly once,
    # mask shift/clipping, complete cel removal and native undo restoration.
    for mode in (32, 16, 8):
        open_fixture(f"canvas-{mode}.ase", mode=mode, linked=True)
        mutate("set_selection", {"x1": 0, "y1": 2, "x2": 3, "y2": 4})
        raw = native_save(f"canvas-{mode}-before.ase")
        before, state = images(), stable(undo=True)
        mutate("resize_canvas", {"width": 18, "height": 20, "offsetX": 2, "offsetY": 3})
        assert (current()["width"], current()["height"]) == (18, 20)
        assert [(c["x"], c["y"], c["links"]) for c in layer(base)["cels"]] == [(1, 5, 1), (1, 5, 1), (1, 5, 0)]
        assert (current()["selection"]["x"], current()["selection"]["y"]) == (2, 5)
        roundtrip(before, images(), state)
        mutate("undo")
        assert native_save(f"canvas-{mode}-restored.ase") == raw
        before, state = images(), stable(undo=True)
        mutate("resize_canvas", {"width": 1, "height": 1})
        assert all(c["width"] == 3 and c["height"] == 2 for c in layer(base)["cels"])
        mutate("resize_canvas", {"width": 16, "height": 16})
        assert images() == before  # shrink/grow never loses off-canvas data
        mutate("undo")
        mutate("undo")
        assert stable(undo=True) == state
        no_op("resize_canvas", {"width": 16, "height": 16})
        mutate("crop_canvas", {"x": 0, "y": 2, "width": 2, "height": 2}, "WOULD_DISCARD_PIXELS")
        mutate("crop_canvas", {"x": 15, "y": 15, "width": 2, "height": 2, "discardOutside": True}, "OUTSIDE_CANVAS")
        before, state = images(), stable(undo=True)
        mutate("crop_canvas", {"x": 0, "y": 2, "width": 2, "height": 2, "discardOutside": True})
        assert all((c["x"], c["y"], c["width"], c["height"]) == (0, 0, 2, 2) for c in layer(base)["cels"])
        assert [c["links"] for c in layer(base)["cels"]] == [1, 1, 0]
        after = images()
        for original, cropped in zip(before, after):
            expected = b"".join(original[2][(y * 16) * 4:(y * 16 + 2) * 4] for y in (2, 3))
            assert cropped == (2, 2, expected)
        roundtrip(before, after, state)
        mutate("undo")
        assert native_save(f"canvas-{mode}-crop-undo.ase") == raw
        before, state = images(), stable(undo=True)
        mutate("crop_canvas", {"x": 8, "y": 8, "width": 4, "height": 4, "discardOutside": True})
        assert not layer(base)["cels"] and not current()["selection"]["visible"]
        roundtrip(before, images(), state)
        mutate("undo")
        assert native_save(f"canvas-{mode}-remove-undo.ase") == raw
        # A single-frame raw clone can be compared byte-for-byte on disk without
        # IDs or compositing/quantization obscuring cel opacity/user data.
        open_fixture(f"copy-raw-{mode}.ase", mode=mode, count=1)
        original_raw = native_save(f"copy-raw-{mode}-before.ase")
        source_image = layer(base)["cels"][0]["imageId"]
        copied = mutate("duplicate_layer", {"layerId": base})["createdLayerId"]
        assert layer(copied)["cels"][0]["imageId"] != source_image
        assert layer(copied)["cels"][0]["celDataId"] != layer(base)["cels"][0]["celDataId"]
        assert layer(copied)["cels"][0]["userData"] == layer(base)["cels"][0]["userData"] == {"text": "preserve me", "color": 0}
        copy_raw = native_save(f"copy-raw-{mode}-after.ase")
        cels = [payload[2:] for kind, payload in copy_raw[0][1] if kind == 0x2005]
        data = [payload for kind, payload in copy_raw[0][1] if kind == 0x2020]
        assert cels == [payload[2:] for kind, payload in original_raw[0][1] if kind == 0x2005] * 2
        assert data == [payload for kind, payload in original_raw[0][1] if kind == 0x2020] * 2
    print("PASS: canvas preserve/shifts and guarded raw RGBA/indexed/grayscale crop, linked data once, mask clipping/removal, repeated one-step undo/redo and exact save restoration.")

    open_fixture("canvas-background.ase", background=True)
    mutate("resize_canvas", {"width": 8, "height": 8}, "UNSUPPORTED_LAYER")
    mutate("crop_canvas", {"x": 0, "y": 0, "width": 8, "height": 8, "discardOutside": True}, "UNSUPPORTED_LAYER")
    mutate("duplicate_layer", {"layerId": base}, "UNSUPPORTED_LAYER")
    extra = mutate("create_layer", {"name": "Transparent above background"})["createdLayerId"]
    mutate("duplicate_layer", {"layerId": extra, "afterLayerId": None}, "UNSUPPORTED_LAYER")
    mutate("reparent_layer", {"layerId": extra, "parentId": None, "afterLayerId": None}, "UNSUPPORTED_LAYER")
    open_fixture("canvas-lock.ase", count=1)
    mutate("update_layer", {"layerId": base, "editable": False})
    mutate("resize_canvas", {"width": 20, "height": 20}, "LAYER_LOCKED")
    mutate("crop_canvas", {"x": 0, "y": 0, "width": 8, "height": 8, "discardOutside": True}, "LAYER_LOCKED")
    mutate("update_layer", {"layerId": base, "editable": True})
    mutate("update_cel", {"layerId": base, "frame": 0, "x": -32768})
    mutate("resize_canvas", {"width": 16, "height": 16, "offsetX": -1}, "OUTSIDE_NATIVE_RANGE")
    before, state = images(), stable(undo=True)
    # Cropping removes a wholly-outside cel: it must not try to shift that
    # discarded cel past the signed coordinate boundary before deleting it.
    mutate("crop_canvas", {"x": 1, "y": 1, "width": 15, "height": 15, "discardOutside": True})
    assert not layer(base)["cels"]
    roundtrip(before, images(), state)
    mutate("undo")
    print("PASS: canvas/background/locked/out-of-native-range refusals preserve all metadata/pixels/history.")

    doc = client.request("create", {"width": 16, "height": 16, "name": "Empty canvas and mask-only shifts"})
    document_id, base = doc["documentId"], doc["layers"][0]["layerId"]
    for color in (red, {"r": 0, "g": 0, "b": 0, "a": 0}):
        mutate("set_pixels", {"layerId": base, "frame": 0, "pixels": [{"x": 1, "y": 1, **color}]})
    assert not layer(base)["cels"]
    mutate("save", {"path": "editing-workflows/mask-only-shift.ase"})
    no_op("resize_canvas", {"width": 16, "height": 16, "offsetX": 2, "offsetY": 3})
    mutate("set_bitmap_selection", {"x": 2, "y": 2, "width": 3, "height": 1, "bits": "101"})
    before, state = images(), stable(undo=True)
    mutate("resize_canvas", {"width": 16, "height": 16, "offsetX": 2, "offsetY": 3})
    assert not current()["modified"] and (current()["selection"]["x"], current()["selection"]["y"]) == (4, 5)
    roundtrip(before, images(), state)
    print("PASS: empty-canvas offset no-op and mask-only canvas shifts preserve saved state/history with native selection undo.")

    # Subtree clones retain flags/properties and bytes but copy every image
    # independently, including links. Moving never changes any IDs or pixels.
    open_fixture("layer-links.ase", linked=True)
    raw = native_save("layer-source.ase")
    group = mutate("create_layer", {"name": "Parent", "type": "group"})["createdLayerId"]
    nested = mutate("create_layer", {"name": "Child", "type": "group", "parentId": group})["createdLayerId"]
    mutate("reparent_layer", {"layerId": base, "parentId": nested})
    no_op("reparent_layer", {"layerId": base, "parentId": nested})
    mutate("reparent_layer", {"layerId": group, "parentId": nested}, "LAYER_CYCLE")
    mutate("reparent_layer", {"layerId": group, "parentId": group}, "LAYER_CYCLE")
    mutate("reparent_layer", {"layerId": base, "parentId": group, "afterLayerId": base}, "INVALID_PARAMS")
    mutate("reparent_layer", {"layerId": base, "parentId": base}, "INVALID_PARAMS")
    mutate("update_layer", {"layerId": base, "opacity": 180, "blendMode": "multiply", "visible": False})
    mutate("update_layer", {"layerId": nested, "editable": False})
    mutate("duplicate_layer", {"layerId": base}, "LAYER_LOCKED")
    before, state = images(), stable(undo=True)
    copy_id = mutate("duplicate_layer", {"layerId": group, "name": "Independent subtree"})["createdLayerId"]
    assert len(current()["layers"]) == len(state["layers"]) + 3
    copied_nested = next(l for l in current()["layers"] if l["parentId"] == copy_id)
    copied_base = next(l for l in current()["layers"] if l["parentId"] == copied_nested["layerId"])
    assert not copied_nested["editable"] and not copied_base["visible"]
    assert copied_base["opacity"] == 180 and copied_base["blendMode"] == 1
    assert all(c["links"] == 0 for c in copied_base["cels"])
    assert not {c["imageId"] for c in layer(base)["cels"]} & {c["imageId"] for c in copied_base["cels"]}
    roundtrip(before, images(), state)
    mutate("undo")
    mutate("update_layer", {"layerId": nested, "editable": True})
    mutate("update_layer", {"layerId": base, "visible": True, "blendMode": "normal", "opacity": 255})
    before, state = images(), stable(undo=True)
    result = mutate("reparent_layer", {"layerId": base, "parentId": None, "afterLayerId": None})
    assert result["reparented"] and layer(base)["parentId"] is None
    assert layer(base)["cels"] == current()["layers"][0]["cels"]
    roundtrip(before, images(), state)
    # Undo after destination folder destruction/reconstruction re-resolves IDs.
    mutate("remove_layer", {"layerId": group, "recursive": True})
    mutate("undo")
    mutate("undo")
    assert stable(undo=True) == state
    mutate("redo")
    assert native_save("layer-reparented.ase") == raw
    copy_id = mutate("duplicate_layer", {"layerId": base, "name": "Independent linked copies", "parentId": group})["createdLayerId"]
    mutate("draw_brush_stroke", {"layerId": copy_id, "frame": 1, "points": [{"x": 7, "y": 7}], "brush": {"width": 1, "height": 1, "bits": "1"}, "color": red})
    assert layer(base)["cels"][0]["links"] == 1
    assert layer(copy_id)["cels"][0]["imageId"] != layer(copy_id)["cels"][1]["imageId"]
    mutate("update_layer", {"layerId": group, "editable": False})
    mutate("reparent_layer", {"layerId": base, "parentId": group}, "LAYER_LOCKED")
    mutate("duplicate_layer", {"layerId": base, "parentId": group}, "LAYER_LOCKED")
    mutate("update_layer", {"layerId": group, "editable": True})
    mutate("update_layer", {"layerId": group, "blendMode": "multiply"}, "UNSUPPORTED_LAYER")
    print("PASS: independent nested linked-layer copies with flags/blends/raw bytes; ID-preserving reparent/cycles/locks and undo after native folder reconstruction.")

    # Layer compositing follows native blend modes and is one atomic property edit.
    doc = client.request("create", {"width": 16, "height": 16, "name": "Mask and brush tests"})
    document_id, base = doc["documentId"], doc["layers"][0]["layerId"]
    mutate("set_pixels", {"layerId": base, "frame": 0, "pixels": [{"x": 5, "y": 5, **red}]})
    overlay = mutate("create_layer", {"name": "Blend overlay"})["createdLayerId"]
    mutate("set_pixels", {"layerId": overlay, "frame": 0, "pixels": [{"x": 5, "y": 5, **blue}]})
    before, state = images(), stable(undo=True)
    mutate("update_layer", {"layerId": overlay, "blendMode": "multiply", "opacity": 170})
    assert images() != before and layer(overlay)["blendMode"] == 1
    roundtrip(before, images(), state)
    mutate("undo")
    no_op("update_layer", {"layerId": overlay, "blendMode": "normal"})
    mutate("update_layer", {"layerId": overlay, "blendMode": "bogus"}, "INVALID_PARAMS")
    names = ("normal", "multiply", "screen", "overlay", "darken", "lighten", "color_dodge", "color_burn", "hard_light", "soft_light", "difference", "exclusion", "hue", "saturation", "color", "luminosity")
    for value, name in enumerate(names):
        mutate("update_layer", {"layerId": overlay, "blendMode": name})
        assert layer(overlay)["blendMode"] == value
    mutate("remove_layer", {"layerId": overlay})
    mutate("save", {"path": "editing-workflows/masks.ase"})

    bitmap = {"x": 2, "y": 2, "width": 3, "height": 3, "bits": "101010101"}
    mutate("set_bitmap_selection", bitmap)
    selected = {(2, 2), (4, 2), (3, 3), (2, 4), (4, 4)}
    def mask_points():
        w, h, pixels = image(mask=True)
        return {(x, y) for y in range(h) for x in range(w) if pixels[(y * w + x) * 4 + 3]}
    assert mask_points() == selected and not current()["modified"]
    no_op("set_bitmap_selection", bitmap)
    mutate("set_bitmap_selection", {**bitmap, "bits": "10"}, "INVALID_PARAMS")
    mutate("set_bitmap_selection", {**bitmap, "x": 15}, "OUTSIDE_CANVAS")
    for mode, expected in (("add", selected | {(3, 2)}), ("subtract", selected), ("intersect", set())):
        mutate("set_bitmap_selection", {"x": 3, "y": 2, "width": 1, "height": 1, "bits": "1", "mode": mode})
        assert mask_points() == expected
    mutate("undo")
    assert mask_points() == selected
    mutate("set_polygon_selection", {"vertices": [{"x": 2, "y": 2}, {"x": 4, "y": 2}, {"x": 4, "y": 4}, {"x": 2, "y": 4}]})
    assert mask_points() == {(x, y) for y in range(2, 5) for x in range(2, 5)}
    assert not current()["modified"]
    mutate("undo")
    assert mask_points() == selected
    mutate("redo")
    mutate("set_polygon_selection", {"vertices": [{"x": 2, "y": 2}] * 3}, "INVALID_PARAMS")
    mutate("set_polygon_selection", {"vertices": [{"x": 2, "y": 2}, {"x": 4, "y": 2}, {"x": 16, "y": 4}]}, "INVALID_PARAMS")
    # Clockwise/reversed winding and self-crossing fill give deterministic masks.
    polygon = [{"x": 1, "y": 1}, {"x": 8, "y": 8}, {"x": 1, "y": 8}, {"x": 8, "y": 1}]
    mutate("set_polygon_selection", {"vertices": polygon})
    crossed = mask_points()
    mutate("set_polygon_selection", {"vertices": polygon[::-1]})
    assert mask_points() == crossed
    for mode in ("add", "subtract", "intersect"):
        mutate("set_polygon_selection", {"vertices": [{"x": 2, "y": 2}, {"x": 4, "y": 2}, {"x": 4, "y": 4}, {"x": 2, "y": 4}], "mode": mode})
    print("PASS: native blend/property undo; exact sparse/empty bitmap masks and polygon winding/self-crossing/combinations, no saved-state changes or invalid partial edits.")

    mutate("modify_selection", {"action": "none"})
    brush = {"width": 3, "height": 3, "bits": "010111010"}
    stroke = {"layerId": base, "frame": 0, "points": [{"x": 2, "y": 7}, {"x": 7, "y": 7}], "brush": brush, "color": red}
    before, state = images(), stable(undo=True)
    mutate("draw_brush_stroke", stroke)
    painted = image()[2]
    stamped = {(x + dx, 7 + dy) for x in range(2, 8) for dx, dy in ((0, -1), (-1, 0), (0, 0), (1, 0), (0, 1))}
    for x, y in stamped:
        assert painted[(y * 16 + x) * 4:(y * 16 + x) * 4 + 4] == bytes(red.values())
    roundtrip(before, images(), state)
    no_op("draw_brush_stroke", stroke)
    mutate("draw_brush_stroke", {**stroke, "points": [{"x": 0, "y": 0}]}, "OUTSIDE_CANVAS")
    mutate("draw_brush_stroke", {**stroke, "brush": {**brush, "bits": "000000000"}}, "INVALID_PARAMS")
    mutate("draw_brush_stroke", {**stroke, "brush": {**brush, "bits": "11"}}, "INVALID_PARAMS")
    mutate("draw_brush_stroke", {**stroke, "brush": {**brush, "anchorX": 3}}, "INVALID_PARAMS")
    mutate("draw_brush_stroke", {**stroke, "index": 2}, "INVALID_PARAMS")
    mutate("draw_brush_stroke", {k: v for k, v in stroke.items() if k != "color"}, "INVALID_PARAMS")
    mutate("draw_brush_stroke", {**stroke, "respectSelection": True}, "NO_SELECTION")
    mutate("set_bitmap_selection", {"x": 2, "y": 7, "width": 3, "height": 1, "bits": "101"})
    before = image()[2]
    mutate("draw_brush_stroke", {**stroke, "color": {"r": 0, "g": 0, "b": 0, "a": 0}, "respectSelection": True})
    expected = bytearray(before)
    for x in (2, 4):
        expected[(7 * 16 + x) * 4:(7 * 16 + x) * 4 + 4] = bytes(4)
    assert image()[2] == expected
    mutate("modify_selection", {"action": "none"})
    mutate("draw_brush_stroke", {**stroke, "points": [{"x": 0, "y": 0}], "clipToCanvas": True})
    mutate("draw_brush_stroke", {**stroke, "points": [{"x": 0, "y": 12}], "brush": {"width": 2, "height": 1, "bits": "11", "anchorX": 0, "anchorY": 0}})
    assert image()[2][(12 * 16) * 4:(12 * 16 + 2) * 4] == bytes(red.values()) * 2
    mutate("update_layer", {"layerId": base, "editable": False})
    mutate("draw_brush_stroke", stroke, "LAYER_LOCKED")
    mutate("update_layer", {"layerId": base, "editable": True})
    print("PASS: connected/custom-anchor bitmap brushes, exact replacement/erasure/selection/explicit clipping, no-op history and one-step undo/redo.")

    doc = client.request("create", {"width": 16, "height": 16, "name": "Exact indexed tests", "colorMode": "indexed"})
    document_id, base = doc["documentId"], doc["layers"][0]["layerId"]
    assert doc["colorMode"] == "indexed" and doc["transparentIndex"] == 0
    mutate("set_palette", {"frame": 0, "size": 3, "entries": [{"index": 0, "color": {**red, "a": 0}}, {"index": 1, "color": red}, {"index": 2, "color": {**blue, "a": 255}}]})
    paint = {"layerId": base, "frame": 0}
    pixels = [{"x": 2, "y": 3, "index": 2}, {"x": 2, "y": 3, "index": 1}, {"x": 5, "y": 6, "index": 2}]
    before, state = images(), stable(undo=True)
    mutate("set_indexed_pixels", {**paint, "pixels": pixels})
    assert image()[2][(3 * 16 + 2) * 4:(3 * 16 + 2) * 4 + 4] == bytes(red.values())
    roundtrip(before, images(), state)
    no_op("set_indexed_pixels", {**paint, "pixels": pixels})
    mutate("set_indexed_pixels", {**paint, "pixels": pixels + [{"x": 1, "y": 1, "index": 3}]}, "PALETTE_INDEX_OUT_OF_RANGE")
    mutate("set_indexed_pixels", {**paint, "pixels": pixels + [{"x": 16, "y": 1, "index": 1}]}, "INVALID_PARAMS")
    stroke = {**paint, "points": [{"x": 7, "y": 7}, {"x": 10, "y": 9}], "brush": brush, "index": 2}
    before, state = images(), stable(undo=True)
    mutate("draw_brush_stroke", stroke)
    roundtrip(before, images(), state)
    no_op("draw_brush_stroke", stroke)
    mutate("draw_brush_stroke", {**stroke, "index": 3}, "PALETTE_INDEX_OUT_OF_RANGE")
    mutate("draw_brush_stroke", {**{k: v for k, v in stroke.items() if k != "index"}, "color": red}, "UNSUPPORTED_COLOR_MODE")
    mutate("set_bitmap_selection", {"x": 2, "y": 3, "width": 1, "height": 1, "bits": "1"})
    mutate("set_indexed_pixels", {**paint, "pixels": [{"x": 2, "y": 3, "index": 0}, {"x": 5, "y": 6, "index": 0}], "respectSelection": True})
    assert image()[2][(3 * 16 + 2) * 4 + 3] == 0 and image()[2][(6 * 16 + 5) * 4 + 3] == 255
    mutate("set_indexed_pixels", {**paint, "pixels": [{"x": 5, "y": 6, "index": 3}], "respectSelection": True}, "PALETTE_INDEX_OUT_OF_RANGE")
    mutate("modify_selection", {"action": "none"})
    mutate("add_frame", {"index": 1})
    mutate("set_palette", {"frame": 1, "entries": [{"index": 1, "color": {**blue, "a": 255}}]})
    mutate("set_indexed_pixels", {**paint, "frame": 1, "pixels": [{"x": 2, "y": 3, "index": 1}]})
    assert image(1)[2][(3 * 16 + 2) * 4:(3 * 16 + 2) * 4 + 4] == bytes((30, 150, 210, 255))
    raw = native_save("indexed-painted.ase")
    assert struct.unpack_from("<H", (directory / "indexed-painted.ase").read_bytes(), 12)[0] == 8
    first_cel = next(payload for kind, payload in raw[1][1] if kind == 0x2005)
    assert set(first_cel[20:]) <= {0, 1, 2} and 1 in first_cel[20:]
    saved = images()
    doc = client.request("open", {"path": "editing-workflows/indexed-painted.ase"})
    document_id, base = doc["documentId"], doc["layers"][0]["layerId"]
    assert images() == saved
    print("PASS: indexed creation/exact palette pixels/duplicate last-wins/erasure and custom brushes, frame palettes/masks, raw index save/reopen, no conversion or invalid partial edits.")

    for mode in (32, 16, 8):
        open_fixture(f"brush-guards-{mode}.ase", mode=mode, linked=True)
        color_key = {"index": 1} if mode == 8 else {"color": red}
        params = {"layerId": base, "frame": 0, "points": [{"x": 5, "y": 5}], "brush": brush, **color_key}
        mutate("draw_brush_stroke", params, "UNSUPPORTED_COLOR_MODE" if mode == 16 else "LINKED_CEL")
        mutate("set_indexed_pixels", {"layerId": base, "frame": 0, "pixels": [{"x": 5, "y": 5, "index": 1}]}, "LINKED_CEL" if mode == 8 else "UNSUPPORTED_COLOR_MODE")

    # Existing files can use a nonzero transparent index; palette0 isn't
    # implicitly special and byte-level erasure must follow the sprite header.
    fixture(directory / "index2-transparent.ase", mode=8, count=1)
    data = bytearray((directory / "index2-transparent.ase").read_bytes())
    data[28] = 2
    (directory / "index2-transparent.ase").write_bytes(data)
    doc = client.request("open", {"path": "editing-workflows/index2-transparent.ase"})
    document_id, base = doc["documentId"], doc["layers"][0]["layerId"]
    assert doc["transparentIndex"] == 2
    paint = {"layerId": base, "frame": 0}
    mutate("set_indexed_pixels", {**paint, "pixels": [{"x": 5, "y": 5, "index": 0}]})
    assert image()[2][(5 * 16 + 5) * 4 + 3] == 192  # fixture cel opacity is retained
    mutate("draw_brush_stroke", {**paint, "points": [{"x": 5, "y": 5}], "brush": {"width": 1, "height": 1, "bits": "1"}, "index": 2})
    assert image()[2][(5 * 16 + 5) * 4 + 3] == 0
    no_op("set_indexed_pixels", {**paint, "pixels": [{"x": 5, "y": 5, "index": 2}]})

    # Allocation/CPU/structural limits are rejected before changes.
    large_fixture(directory / "layer-memory-limit.ase")
    doc = client.request("open", {"path": "editing-workflows/layer-memory-limit.ase"})
    document_id, base = doc["documentId"], doc["layers"][0]["layerId"]
    mutate("duplicate_layer", {"layerId": base}, "LIMIT_EXCEEDED")
    doc = client.request("create", {"width": 1024, "height": 1024, "name": "CPU limits"})
    document_id, base = doc["documentId"], doc["layers"][0]["layerId"]
    mutate("set_polygon_selection", {"vertices": [{"x": 0, "y": 0}, {"x": 1023, "y": 0}, {"x": 1023, "y": 1023}] * 3}, "LIMIT_EXCEEDED")
    mutate("draw_brush_stroke", {"layerId": base, "frame": 0, "points": [{"x": 16, "y": y} for y in range(16, 1008)], "brush": {"width": 32, "height": 32, "bits": "1" * 1024}, "color": red}, None)
    # Many long parallel runs exceed the stamp budget (path centers deduped).
    points = []
    for y in range(16, 1008, 32):
        points.extend([{"x": 16, "y": y}, {"x": 1007, "y": y}])
    mutate("draw_brush_stroke", {"layerId": base, "frame": 0, "points": points, "brush": {"width": 32, "height": 32, "bits": "1" * 1024}, "color": red}, "LIMIT_EXCEEDED")
    # Native fixture at the layer bound; no 128 individual UI edits needed.
    fixture(directory / "layer-count-limit.ase", count=1)
    data = (directory / "layer-count-limit.ase").read_bytes()
    layer_size = struct.unpack_from("<I", data, 144)[0]
    layer_chunk = data[144:144 + layer_size]
    frame = bytearray(data[128:144])
    chunks = layer_chunk * 128 + data[144 + layer_size:]
    struct.pack_into("<I", frame, 0, 16 + len(chunks))
    struct.pack_into("<H", frame, 6, 130)  # 128 layers + cel + user data
    header = bytearray(data[:128])
    struct.pack_into("<I", header, 0, 144 + len(chunks))
    (directory / "layer-count-limit.ase").write_bytes(header + frame + chunks)
    doc = client.request("open", {"path": "editing-workflows/layer-count-limit.ase"})
    document_id, base = doc["documentId"], doc["layers"][0]["layerId"]
    assert len(doc["layers"]) == 128
    mutate("duplicate_layer", {"layerId": base}, "LIMIT_EXCEEDED")
    print("PASS: linked/color-mode refusals and bounded memory/polygon/brush work before mutation.")

    # Save/close only the documents created here, leaving callers' documents alone.
    for document in list(client.request("list_documents")["documents"]):
        if document["documentId"] in original_ids:
            continue
        document_id = document["documentId"]
        active = client.request("list_documents")["activeDocumentId"]
        client.request("activate_document", {**target(), "expectedActiveDocumentId": active})
        mutate("save", {"path": f"editing-workflows/cleanup-{document_id}.ase"})
        mutate("close_document", {"confirm": True})

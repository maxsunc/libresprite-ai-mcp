"""Cel transforms and explicit native selection regressions in a disposable GUI. GPLv2."""
import base64
import struct
import zlib


def test_cels_and_selection(client, assets, smoke):
    directory = assets / "selection-assets"
    directory.mkdir()
    document = client.request("create", {"width": 16, "height": 16, "name": "Cel and selection tests"})
    document_id = document["documentId"]
    base = document["layers"][0]["layerId"]
    red = {"r": 220, "g": 50, "b": 60, "a": 255}
    green = {"r": 40, "g": 180, "b": 100, "a": 255}
    blue = {"r": 60, "g": 100, "b": 220, "a": 255}
    clear = {"r": 0, "g": 0, "b": 0, "a": 0}

    def current():
        return client.request("inspect", {"documentId": document_id})

    def mutate(method, params=None, error=None):
        before = current()
        result = client.request(method, {"documentId": document_id, "expectedRevision": before["revision"], **(params or {})}, expected_error=error)
        if error:
            assert current() == before, (method, error)
        return result

    def image(method="render", **params):
        result = client.request(method, {"documentId": document_id, "frame": 0, "scale": 1, **params})
        path = directory / "check.png"
        path.write_bytes(base64.b64decode(result["pngBase64"]))
        return smoke.read_png(path)

    def cel(layer=None, frame=0):
        if layer is None:
            layer = base
        return next(item for item in next(item for item in current()["layers"] if item["layerId"] == layer)["cels"] if item["frame"] == frame)

    def paint(layer=None, frame=0):
        return {"layerId": base if layer is None else layer, "frame": frame}

    def selection_points():
        width, height, pixels = image("render_selection", mode="mask")
        return {(x, y) for y in range(height) for x in range(width) if pixels[(y * width + x) * 4 + 3]}

    def select(x1, y1, x2=None, y2=None, **options):
        return mutate("set_selection", {"x1": x1, "y1": y1, "x2": x1 if x2 is None else x2, "y2": y1 if y2 is None else y2, **options})

    def at(picture, x, y):
        width, _, pixels = picture
        start = (y * width + x) * 4
        return tuple(pixels[start:start + 4])

    def expected_grid(grid, x=3, y=4):
        return (16, 16, bytes(channel for dy in range(16) for dx in range(16) for channel in (grid[dy - y][dx - x] if y <= dy < y + len(grid) and x <= dx < x + len(grid[0]) else (0, 0, 0, 0))))

    colors = [tuple(red.values()), tuple(green.values()), tuple(blue.values()), (255, 200, 100, 255), (80, 40, 120, 255), (20, 210, 240, 255)]
    grid = [colors[0:2], colors[2:4], colors[4:6]]
    mutate("set_pixels", {**paint(), "pixels": [{"x": 3 + x, "y": 4 + y, "r": c[0], "g": c[1], "b": c[2], "a": c[3]} for y, row in enumerate(grid) for x, c in enumerate(row)]})
    assert image() == expected_grid(grid) and (cel()["width"], cel()["height"]) == (2, 3)
    select(3, 4)  # Whole-image transforms must ignore this one-pixel selection.
    for operation, transformed in (
        ("flip_horizontal", [row[::-1] for row in grid]),
        ("flip_vertical", grid[::-1]),
        ("rotate_cw", [list(row) for row in zip(*grid[::-1])]),
        ("rotate_ccw", [list(row) for row in zip(*grid)][::-1]),
        ("rotate_180", [row[::-1] for row in grid[::-1]]),
    ):
        mutate("transform_cel", {**paint(), "operation": operation})
        assert image() == expected_grid(transformed), operation
        assert (cel()["x"], cel()["y"], cel()["opacity"]) == (3, 4, 255)
        assert (cel()["width"], cel()["height"]) == (len(transformed[0]), len(transformed))
        for _ in range(2):
            mutate("undo")
            assert image() == expected_grid(grid)
            mutate("redo")
            assert image() == expected_grid(transformed)
        mutate("undo")
        assert selection_points() == {(3, 4)}
    mutate("modify_selection", {"action": "none"})
    revision = current()["revision"]
    mutate("update_cel", {**paint(), "x": 3, "y": 4, "opacity": 255})
    mutate("unlink_cel", paint())
    assert current()["revision"] == revision
    mutate("update_cel", {**paint(), "x": -1, "y": -1, "opacity": 128})
    assert (cel()["x"], cel()["y"], cel()["opacity"]) == (-1, -1, 128)
    assert at(image(), 0, 0) == grid[1][1][:3] + (128,)
    mutate("transform_cel", {**paint(), "operation": "rotate_cw"})
    assert (cel()["width"], cel()["height"]) == (3, 2)
    mutate("update_cel", {**paint(), "x": 3, "y": 4, "opacity": 255})
    assert image() == expected_grid([list(row) for row in zip(*grid[::-1])])
    mutate("undo")
    mutate("undo")
    mutate("undo")
    assert image() == expected_grid(grid)
    for params in ({**paint()}, {**paint(), "x": -32769}, {**paint(), "opacity": 256}, {**paint(), "x": 4, "y": 32768}):
        mutate("update_cel", params, "INVALID_PARAMS")
    mutate("transform_cel", {**paint(), "operation": "rotate_45"}, "INVALID_PARAMS")
    missing = mutate("create_layer", {"name": "Empty"})["createdLayerId"]
    for method, params in (("update_cel", {"x": 1}), ("transform_cel", {"operation": "flip_horizontal"}), ("unlink_cel", {})):
        mutate(method, {**paint(missing), **params}, "CEL_NOT_FOUND")
    mutate("draw_stroke", {**paint(missing), "points": [{"x": 10, "y": 10}], "color": green})
    # A first missing-cel stroke starts with the full patch extent. Repainting
    # the existing cel runs native PatchCel/TrimCel and leaves a true 1x1 image.
    mutate("draw_stroke", {**paint(missing), "points": [{"x": 10, "y": 10}], "color": blue})
    assert (cel(missing)["width"], cel(missing)["height"]) == (1, 1)
    for operation in ("flip_horizontal", "flip_vertical", "rotate_cw", "rotate_ccw", "rotate_180"):
        before = current()
        mutate("transform_cel", {**paint(missing), "operation": operation})
        assert current() == before
    mutate("remove_layer", {"layerId": missing})
    mutate("update_cel", {**paint(), "x": 32767, "y": -32768, "opacity": 64})
    mutate("save", {"path": "selection-assets/off-canvas.ase"})
    reopened = client.request("open", {"path": "selection-assets/off-canvas.ase"})
    document_id = reopened["documentId"]
    base = reopened["layers"][0]["layerId"]
    assert (cel(base)["x"], cel(base)["y"], cel(base)["opacity"]) == (32767, -32768, 64)
    mutate("update_cel", {**paint(base), "x": 3, "y": 4, "opacity": 255})
    assert image() == expected_grid(grid)
    print("PASS: all five whole-cel transforms, nonsquare exact rotations, off-canvas/opacity metadata, native undo/redo, no-ops, validation and signed-coordinate save/reopen.")

    mutate("save", {"path": "selection-assets/selected.ase"})
    initial = current()
    select(4, 6, 3, 4)  # Reversed inclusive endpoints.
    rectangle = {(x, y) for y in range(4, 7) for x in range(3, 5)}
    assert selection_points() == rectangle and current()["selection"]["selectedPixels"] == 6
    assert not current()["modified"]
    assert (current()["activeLayerId"], current()["activeFrame"]) == (initial["activeLayerId"], initial["activeFrame"])
    before = current()
    select(3, 4, 4, 6)
    assert current() == before
    select(8, 8, 9, 9, mode="add")
    assert selection_points() == rectangle | {(8, 8), (8, 9), (9, 8), (9, 9)}
    select(4, 4, 9, 9, mode="intersect")
    assert selection_points() == {(4, 4), (4, 5), (4, 6), (8, 8), (8, 9), (9, 8), (9, 9)}
    select(4, 4, 4, 6, mode="subtract")
    assert selection_points() == {(8, 8), (8, 9), (9, 8), (9, 9)}
    mutate("modify_selection", {"action": "invert"})
    assert len(selection_points()) == 252
    mutate("modify_selection", {"action": "all"})
    assert len(selection_points()) == 256
    mutate("modify_selection", {"action": "none"})
    assert not selection_points() and not current()["selection"]["visible"]
    before = current()
    mutate("modify_selection", {"action": "none"})
    assert current() == before
    mutate("modify_selection", {"action": "invert"})
    assert len(selection_points()) == 256
    select(5, 5, 9, 9, shape="ellipse")
    ellipse = selection_points()
    assert (7, 7) in ellipse and not {(5, 5), (9, 5), (5, 9), (9, 9)} & ellipse
    assert {(14 - x, y) for x, y in ellipse} == ellipse and {(x, 14 - y) for x, y in ellipse} == ellipse
    assert current()["selection"]["selectedPixels"] == len(ellipse) and not current()["modified"]
    mutate("undo")
    assert len(selection_points()) == 256
    mutate("redo")
    assert selection_points() == ellipse
    overlay_before = current()
    client.request("set_paused", {"paused": True})
    assert image("render_selection", mode="overlay", opacity=0) == image()
    assert image("render_selection", mode="mask", scale=2)[:2] == (32, 32)
    assert current() == overlay_before
    client.request("set_paused", {"paused": False})
    for params in ({"x1": 16, "y1": 0, "x2": 16, "y2": 1}, {"x1": 0, "y1": 0, "x2": 1, "y2": 1, "shape": "polygon"}, {"x1": 0, "y1": 0, "x2": 1, "y2": 1, "mode": "bad"}):
        mutate("set_selection", params, "INVALID_PARAMS")
    mutate("modify_selection", {"action": "grow"}, "INVALID_PARAMS")
    select(3, 4, 4, 6)
    stale = current()["revision"]
    select(8, 8, 9, 9)
    mutate("fill_selection", {**paint(base), "color": red, "expectedRevision": stale}, "STALE_REVISION")
    print("PASS: document-wide rectangle/ellipse masks and combinations, all/none/invert, unchanged saved state, no-ops, native selection undo/redo, paused PNG feedback and selection revision gates.")

    selection_art = mutate("create_layer", {"name": "Selected art"})["createdLayerId"]
    target = paint(selection_art)
    mutate("set_pixels", {**target, "respectSelection": True, "pixels": [{"x": 8, "y": 8, **red}, {"x": 0, "y": 0, **blue}]})
    assert at(image(), 8, 8) == tuple(red.values()) and at(image(), 0, 0) == (0, 0, 0, 0)
    before = current()
    mutate("set_pixels", {**target, "respectSelection": True, "pixels": [{"x": 0, "y": 0, **blue}]})
    assert current() == before
    mutate("set_pixels", {**target, "respectSelection": True, "pixels": [{"x": 8, "y": 8, **blue}, {"x": 16, "y": 0, **red}]}, "INVALID_PARAMS")
    mutate("draw_shape", {**target, "shape": "rectangle", "x1": 0, "y1": 0, "x2": 15, "y2": 15, "filled": True, "color": green, "respectSelection": True})
    assert all(at(image(), x, y) == tuple(green.values()) for x, y in selection_points())
    mutate("draw_stroke", {**target, "points": [{"x": 0, "y": 0}, {"x": 15, "y": 15}], "color": blue, "respectSelection": True})
    assert at(image(), 8, 8) == tuple(blue.values()) and at(image(), 8, 9) == tuple(green.values())
    for contiguous in (True, False):
        before = current()
        mutate("flood_fill", {**target, "x": 0, "y": 0, "color": red, "respectSelection": True, "contiguous": contiguous})
        assert current() == before
    mutate("fill_selection", {**target, "color": clear})
    assert at(image(), 8, 8) == (0, 0, 0, 0)
    select(8, 8)
    select(10, 8, mode="add")
    mutate("flood_fill", {**target, "x": 8, "y": 8, "color": red, "respectSelection": True})
    assert at(image(), 8, 8) == tuple(red.values()) and at(image(), 10, 8) == (0, 0, 0, 0)
    mutate("flood_fill", {**target, "x": 10, "y": 8, "color": green, "respectSelection": True, "contiguous": False})
    assert at(image(), 10, 8) == tuple(green.values())
    mutate("fill_selection", {**target, "color": blue})
    unchanged = current()
    mutate("fill_selection", {**target, "color": blue})
    assert current() == unchanged
    mutate("modify_selection", {"action": "none"})
    no_selection_cases = {
        "fill_selection": {**target, "color": red},
        "translate_selection": {**target, "dx": 1, "dy": 0},
        "set_pixels": {**target, "pixels": [{"x": 0, "y": 0, **red}], "respectSelection": True},
        "draw_shape": {**target, "shape": "line", "x1": 0, "y1": 0, "x2": 1, "y2": 1, "color": red, "respectSelection": True},
        "draw_stroke": {**target, "points": [{"x": 0, "y": 0}], "color": red, "respectSelection": True},
        "flood_fill": {**target, "x": 0, "y": 0, "color": red, "respectSelection": True},
    }
    for method, params in no_selection_cases.items():
        mutate(method, params, "NO_SELECTION")
    mutate("draw_stroke", {**target, "points": [{"x": 0, "y": 0}], "color": red})
    assert at(image(), 0, 0) == tuple(red.values())  # Backward-compatible default.
    mutate("remove_layer", {"layerId": selection_art})
    print("PASS: explicit selection fill/erase, selection-aware pixels/shapes/strokes/flood barriers, disconnected mask islands, outside-seed no-ops, missing-cel creation, no-selection fallback refusal.")

    select(3, 4, 4, 6)
    before_move = image()
    before_mask = selection_points()
    mutate("translate_selection", {**paint(base), "dx": 1, "dy": 0})
    assert image() == expected_grid(grid, x=4, y=4)
    assert selection_points() == {(x + 1, y) for x, y in before_mask}
    for _ in range(2):
        mutate("undo")
        assert image() == before_move and selection_points() == before_mask
        mutate("redo")
        assert image() == expected_grid(grid, x=4, y=4)
    mutate("undo")
    mutate("translate_selection", {**paint(base), "dx": 4, "dy": 0, "copy": True})
    picture = image()
    assert all(at(picture, x, y) == at(before_move, x, y) for x, y in before_mask)
    assert all(at(picture, x + 4, y) == at(before_move, x, y) for x, y in before_mask)
    mutate("undo")
    # Move a sparse mask containing transparent pixels over colored destinations.
    select(3, 4)
    select(2, 4, mode="add")
    mutate("translate_selection", {**paint(base), "dx": 1, "dy": 0, "copy": True})
    assert at(image(), 3, 4) == (0, 0, 0, 0) and at(image(), 4, 4) == grid[0][0]
    mutate("undo")
    mutate("translate_selection", {**paint(base), "dx": 20, "dy": 0}, "OUTSIDE_CANVAS")
    before = current()
    mutate("translate_selection", {**paint(base), "dx": 0, "dy": 0})
    assert current() == before
    select(12, 12)
    mutate("save", {"path": "selection-assets/mask-only.ase"})
    mutate("translate_selection", {**paint(base), "dx": 1, "dy": 0})
    assert selection_points() == {(13, 12)} and not current()["modified"] and image() == before_move
    mutate("undo")
    assert selection_points() == {(12, 12)} and not current()["modified"]
    mutate("redo")
    assert selection_points() == {(13, 12)} and not current()["modified"]
    print("PASS: overlap-safe move/copy with one pixel+mask undo step, transparent replacement, clipping refusal, and saved-state-preserving blank mask translation.")

    group = mutate("create_layer", {"name": "Group guard", "type": "group"})["createdLayerId"]
    nested = mutate("create_layer", {"name": "Nested", "parentId": group})["createdLayerId"]
    mutate("draw_stroke", {**paint(nested), "points": [{"x": 1, "y": 1}], "color": red})
    mutate("update_layer", {"layerId": group, "editable": False})
    for method, params in (("update_cel", {"x": 1}), ("transform_cel", {"operation": "rotate_cw"}), ("unlink_cel", {}), ("fill_selection", {"color": red}), ("translate_selection", {"dx": 1, "dy": 0})):
        mutate(method, {**paint(nested), **params}, "LAYER_LOCKED")
    mutate("update_layer", {"layerId": group, "editable": True})
    mutate("transform_cel", {**paint(group), "operation": "rotate_cw"}, "UNSUPPORTED_LAYER")
    guarded = {
        "update_cel": {**paint(base), "x": 4}, "transform_cel": {**paint(base), "operation": "rotate_cw"},
        "unlink_cel": paint(base), "set_selection": {"x1": 1, "y1": 1, "x2": 3, "y2": 3},
        "modify_selection": {"action": "none"}, "fill_selection": {**paint(base), "color": red},
        "translate_selection": {**paint(base), "dx": 1, "dy": 0},
    }
    for method, params in guarded.items():
        mutate(method, {**params, "expectedRevision": current()["revision"] + 1}, "STALE_REVISION")
        mutate(method, {**params, "sessionId": "other-process"}, "SESSION_MISMATCH")
    client.request("set_paused", {"paused": True})
    for method, params in guarded.items():
        mutate(method, params, "PAUSED")
    assert image("render_selection", mode="mask")[:2] == (16, 16)
    client.request("set_paused", {"paused": False})

    linked = client.request("open", {"path": "linked.ase"})
    for method, params in guarded.items():
        mutate(method, params, "INACTIVE_DOCUMENT")
    assert image("render_selection", mode="mask")[:2] == (16, 16)  # Inactive read doesn't switch tabs.
    document_id = linked["documentId"]
    base = linked["layers"][0]["layerId"]
    for method, params in (("update_cel", {"x": 1}), ("transform_cel", {"operation": "flip_horizontal"}), ("fill_selection", {"color": blue}), ("translate_selection", {"dx": 1, "dy": 0})):
        mutate(method, {**paint(base, 1), **params}, "LINKED_CEL")
    original_linked = image(frame=0)
    mutate("unlink_cel", paint(base, 1))
    assert cel(base, 1)["links"] == 0 and image(frame=0) == original_linked
    for _ in range(2):
        mutate("undo")
        assert cel(base, 1)["links"] > 0
        mutate("redo")
        assert cel(base, 1)["links"] == 0
    mutate("update_cel", {**paint(base, 1), "x": 1, "y": 2, "opacity": 128})
    assert (cel(base, 0)["x"], cel(base, 0)["y"], cel(base, 0)["opacity"]) == (0, 0, 255)
    select(1, 2)
    mutate("fill_selection", {**paint(base, 1), "color": blue})
    assert image(frame=0) == original_linked and at(image(frame=1), 1, 2) == tuple(blue.values())[:3] + (128,)

    # Color-mode transforms preserve index/gray bytes, and may retain a swapped
    # image extending beyond the unchanged sprite canvas.
    for filename, color_type, width, height, rows, extra in (
        ("indexed.png", 3, 2, 1, bytes((0, 0, 1)), smoke.chunk(b"PLTE", bytes((0, 0, 0, 220, 50, 60))) + smoke.chunk(b"tRNS", bytes((0, 255)))),
        ("gray.png", 4, 1, 2, bytes((0, 80, 128, 0, 180, 255)), b""),
    ):
        (directory / filename).write_bytes(smoke.SIGNATURE + smoke.chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)) + extra + smoke.chunk(b"IDAT", zlib.compress(rows)) + smoke.chunk(b"IEND", b""))
        loaded = client.request("open", {"path": "selection-assets/" + filename})
        document_id = loaded["documentId"]
        base = loaded["layers"][0]["layerId"]
        original = image()
        mutate("transform_cel", {**paint(base), "operation": "flip_horizontal" if color_type == 3 else "flip_vertical"})
        assert image()[2] == original[2][4:] + original[2][:4]
        mutate("undo")
        mutate("transform_cel", {**paint(base), "operation": "rotate_cw"})
        assert (cel(base)["width"], cel(base)["height"]) == (height, width)
        mutate("transform_cel", {**paint(base), "operation": "rotate_ccw"})
        assert image() == original
        select(0, 0)
        mutate("fill_selection", {**paint(base), "color": red}, "UNSUPPORTED_COLOR_MODE")
    background = client.request("open", {"path": "background.ase"})
    document_id = background["documentId"]
    base = background["layers"][0]["layerId"]
    for method, params in (("update_cel", {"x": 1}), ("transform_cel", {"operation": "rotate_cw"}), ("unlink_cel", {}), ("fill_selection", {"color": red}), ("translate_selection", {"dx": 1, "dy": 0})):
        mutate(method, {**paint(base), **params}, "UNSUPPORTED_LAYER")
    print("PASS: locked groups/background/linked guards, explicit unlink/undo and isolated editing, indexed/grayscale transforms, paused/inactive reads, session/pause/revision safety.")

    # The previous workflow suite owns this 32-MiB sprite. An extreme cel offset
    # must be rejected BEFORE PatchCel tries to allocate a multi-gigabyte union.
    large = client.request("open", {"path": "working-limit.ase"})
    document_id = large["documentId"]
    base = large["layers"][0]["layerId"]
    mutate("update_cel", {**paint(base), "x": 32767, "y": -32768})
    select(0, 0)
    mutate("fill_selection", {**paint(base), "color": red}, "LIMIT_EXCEEDED")
    mutate("set_pixels", {**paint(base), "pixels": [{"x": 0, "y": 0, **red}]}, "LIMIT_EXCEEDED")
    client.request("render_selection", {"documentId": document_id, "frame": 0, "scale": 2}, expected_error="LIMIT_EXCEEDED")
    # Add a ninth linked frame to the test-owned 32-MiB native fixture. Explicit
    # unlinking would allocate another image and must roll back links/selection.
    data = bytearray((assets / "working-limit.ase").read_bytes())
    linked_payload = struct.pack("<HhhBH", 0, 0, 0, 255, 1) + bytes(7) + struct.pack("<H", 0)
    linked_chunk = struct.pack("<IH", len(linked_payload) + 6, 0x2005) + linked_payload
    linked_frame = struct.pack("<IHHH", 16 + len(linked_chunk), 0xF1FA, 1, 100) + bytes(6) + linked_chunk
    struct.pack_into("<I", data, 0, len(data) + len(linked_frame))
    struct.pack_into("<H", data, 6, 9)
    (directory / "large-linked.ase").write_bytes(data + linked_frame)
    large_linked = client.request("open", {"path": "selection-assets/large-linked.ase"})
    document_id = large_linked["documentId"]
    base = large_linked["layers"][0]["layerId"]
    select(0, 0)
    snapshot = current()
    client.request("unlink_cel", {"documentId": document_id, "expectedRevision": snapshot["revision"], **paint(base, 8)}, expected_error="LIMIT_EXCEEDED")
    after = current()
    for key in ("layers", "frames", "selection", "activeLayerId", "activeFrame", "modified", "canUndo", "canRedo"):
        assert after[key] == snapshot[key], key
    mutate("undo")
    assert not current()["selection"]["visible"] and cel(base, 8)["links"] > 0
    # Live selection isn't silently promised to survive native-file reopen.
    saved_mask = client.request("open", {"path": "selection-assets/mask-only.ase"})
    assert not saved_mask["selection"]["visible"]
    print("PASS: pre-allocation off-canvas patch bounds and selection-preview pixel ceilings; original data, mask, saved state and history survive refusals.")

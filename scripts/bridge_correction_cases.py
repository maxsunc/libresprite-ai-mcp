"""Atomic animation correction in generated, test-owned native sprites. GPLv2."""
import base64
import copy
import struct
import zlib
from bridge_animation_cases import canonical_inspection, fixture, raw_frames


def test_animation_correction(client, assets, smoke):
    original_ids = {doc["documentId"] for doc in client.request("list_documents")["documents"]}
    directory = assets / "correction-workflows"
    directory.mkdir()
    document = client.request("create", {"width": 16, "height": 16, "name": "Atomic correction tests"})
    document_id, base = document["documentId"], document["layers"][0]["layerId"]
    red = {"r": 210, "g": 40, "b": 70, "a": 255}
    blue = {"r": 40, "g": 150, "b": 210, "a": 128}
    green = {"r": 60, "g": 200, "b": 120, "a": 255}

    def current():
        return canonical_inspection(client.request("inspect", {"documentId": document_id}))

    def edit(method, params=None, error=None):
        state = current()
        result = client.request(method, {"documentId": document_id, "expectedRevision": state["revision"], **(params or {})}, expected_error=error)
        if error:
            assert current() == state, (method, error)
        return result

    def image(layer, frame):
        result = client.request("render_layer", {"documentId": document_id, "layerId": layer, "frame": frame, "includeHidden": True})
        path = directory / "check.png"
        path.write_bytes(base64.b64decode(result["pngBase64"]))
        return smoke.read_png(path)[2]

    def semantic():
        state = current()
        for key in ("revision", "name", "activeFrame", "activeLayerId", "canUndo", "canRedo", "modified", "hasFile"):
            state.pop(key, None)
        for layer in state["layers"]:
            layer.pop("version")
            for cel in layer.get("cels", []):
                cel.pop("imageVersion")
        return state

    def invariant(state):
        after = current()
        for key in ("frames", "tags", "palettes", "selection", "activeFrame", "activeLayerId"):
            assert after[key] == state[key], key

    def expected_changes(original, corrected, entries):
        changes = []
        for entry in entries:
            key = (entry["layerId"], entry["frame"])
            points = [(i // 4 % 16, i // 4 // 16) for i in range(0, 16 * 16 * 4, 4) if original[key][i:i + 4] != corrected[key][i:i + 4]]
            if points:
                x1, x2 = min(x for x, _ in points), max(x for x, _ in points)
                y1, y2 = min(y for _, y in points), max(y for _, y in points)
                changes.append({"layerId": key[0], "frame": key[1], "changedPixels": len(points), "bounds": {"x": x1, "y": y1, "width": x2 - x1 + 1, "height": y2 - y1 + 1}})
        return changes

    for index in (1, 2):
        edit("add_frame", {"index": index, "durationMs": 80 + 30 * index})
    group = edit("create_layer", {"name": "Motion", "type": "group"})["createdLayerId"]
    moving = edit("create_layer", {"name": "Moving pixels", "parentId": group})["createdLayerId"]
    hidden = edit("create_layer", {"name": "Hidden editable pixels"})["createdLayerId"]
    for frame in range(3):
        edit("set_pixels", {"layerId": base, "frame": frame, "pixels": [{"x": 12, "y": 12, **green}]})
        edit("set_pixels", {"layerId": moving, "frame": frame, "pixels": [{"x": x + frame, "y": 3, **color} for x, color in ((2, red), (3, blue), (5, green))]})
    edit("update_layer", {"layerId": hidden, "visible": False})
    edit("create_tag", {"name": "Motion", "from": 0, "to": 2, "direction": "pingpong"})
    edit("set_bitmap_selection", {"x": 1, "y": 1, "width": 2, "height": 2, "bits": "1001"})
    edit("set_active_site", {"layerId": base, "frame": 2})
    edit("draw_stroke", {"layerId": base, "frame": 2, "points": [{"x": 0, "y": 0}], "color": red})
    edit("undo")
    edit("save", {"path": "correction-workflows/baseline.ase"})
    before, before_semantic = current(), semantic()
    assert before["canRedo"]
    sources = {(layer, frame): image(layer, frame) for layer in (base, moving, hidden) for frame in range(3)}
    batch = {"edits": [
        {"layerId": base, "frame": 0, "pixels": [{"x": 1, "y": 1, **blue}]},
        {"layerId": moving, "frame": 0, "pixels": [{"x": 2, "y": 3, **blue}, {"x": 2, "y": 3, **red}, {"x": 3, "y": 3, **{**red, "a": 0}}, {"x": 2, "y": 4, **green}]},
        {"layerId": moving, "frame": 1, "pixels": [{"x": 3, "y": 3, **{**red, "a": 0}}]},
        {"layerId": hidden, "frame": 2, "pixels": [{"x": 6, "y": 6, **blue}]},
    ]}
    no_op = {"edits": [{"layerId": moving, "frame": 0, "pixels": [{"x": 2, "y": 3, **blue}, {"x": 2, "y": 3, **red}]}, {"layerId": hidden, "frame": 0, "pixels": [{"x": 0, "y": 0, **{**red, "a": 0}}]}]}
    assert edit("edit_pixels", no_op)["changedPixels"] == 0 and current() == before
    preview = edit("edit_pixels", {**batch, "dryRun": True})
    assert preview["editedCels"] == 0 and preview["wouldEditCels"] == 4 and preview["changedPixels"] == 5
    assert current() == before
    expected = {key: bytearray(value) for key, value in sources.items()}
    for entry in batch["edits"]:
        target = expected[(entry["layerId"], entry["frame"])]
        for pixel in entry["pixels"]:
            offset = (pixel["y"] * 16 + pixel["x"]) * 4
            target[offset:offset + 4] = bytes((pixel["r"], pixel["g"], pixel["b"], pixel["a"])) if pixel["a"] else bytes(4)
    applied = edit("edit_pixels", batch)
    assert applied["editedCels"] == applied["wouldEditCels"] == 4 and applied["changedPixels"] == 5
    assert applied["changes"] == preview["changes"]
    assert applied["changes"] == expected_changes(sources, expected, batch["edits"])
    invariant(before)
    for key, pixels in expected.items():
        assert image(*key) == bytes(pixels), key
    for _ in range(2):
        edit("undo")
        assert semantic() == before_semantic and not current()["modified"]
        for key, pixels in sources.items():
            assert image(*key) == pixels
        edit("redo")
        for key, pixels in expected.items():
            assert image(*key) == bytes(pixels)
    state = current()
    assert edit("edit_pixels", batch)["changedPixels"] == 0 and current() == state
    edit("undo")
    before = current()
    region_batch = {"edits": [
        {"layerId": moving, "frame": 2, "mask": {"x": 4, "y": 3, "width": 4, "height": 1, "bits": "1011"}, "dx": 1, "dy": 0},
        {"layerId": moving, "frame": 0, "mask": {"x": 2, "y": 3, "width": 4, "height": 1, "bits": "1011"}, "dx": 1, "dy": 0},
        {"layerId": moving, "frame": 1, "mask": {"x": 3, "y": 3, "width": 3, "height": 1, "bits": "111"}, "dx": -1, "dy": 1, "copy": True},
        {"layerId": hidden, "frame": 0, "mask": {"x": 0, "y": 0, "width": 1, "height": 1, "bits": "1"}, "dx": 1, "dy": 0},
    ]}
    region_expected = {key: bytearray(value) for key, value in sources.items()}
    for entry in region_batch["edits"]:
        key = (entry["layerId"], entry["frame"])
        mask = entry["mask"]
        selected = [(mask["x"] + i % mask["width"], mask["y"] + i // mask["width"]) for i, bit in enumerate(mask["bits"]) if bit == "1"]
        if not entry.get("copy", False):
            for x, y in selected:
                offset = (y * 16 + x) * 4
                region_expected[key][offset:offset + 4] = bytes(4)
        for x, y in selected:
            source = (y * 16 + x) * 4
            target = ((y + entry["dy"]) * 16 + x + entry["dx"]) * 4
            region_expected[key][target:target + 4] = sources[key][source:source + 4]
    preview = edit("translate_regions", {**region_batch, "dryRun": True})
    changed = sum(sum(a[i:i + 4] != b[i:i + 4] for i in range(0, len(a), 4)) for key in sources for a, b in [(sources[key], region_expected[key])])
    assert preview["wouldEditCels"] == 3 and preview["changedPixels"] == changed and current() == before
    applied = edit("translate_regions", region_batch)
    assert applied["editedCels"] == 3 and applied["changes"] == preview["changes"]
    assert applied["changes"] == expected_changes(sources, region_expected, region_batch["edits"])
    invariant(before)
    for key, pixels in region_expected.items():
        assert image(*key) == bytes(pixels), key
    for _ in range(2):
        edit("undo")
        assert semantic() == before_semantic
        for key, pixels in sources.items():
            assert image(*key) == pixels
        edit("redo")
        for key, pixels in region_expected.items():
            assert image(*key) == bytes(pixels)
    edit("undo")
    before = current()
    zero = copy.deepcopy(region_batch["edits"][0]); zero["dx"] = zero["dy"] = 0
    assert edit("translate_regions", {"edits": [zero]})["changedPixels"] == 0 and current() == before
    assert edit("translate_regions", {"edits": [region_batch["edits"][-1]]})["editedCels"] == 0 and current() == before
    valid_pixel, valid_region = batch["edits"][0], region_batch["edits"][0]
    for bad, code in (({**valid_pixel, "frame": 3}, "INVALID_PARAMS"), ({**valid_pixel, "layerId": 2147483647}, "LAYER_NOT_FOUND"), ({**valid_pixel, "layerId": group}, "UNSUPPORTED_LAYER"), ({**valid_pixel, "pixels": [{"x": 16, "y": 0, **red}]}, "INVALID_PARAMS"), ({**valid_pixel, "pixels": [{"x": 0, "y": 0, "index": 1}]}, "UNSUPPORTED_COLOR_MODE"), (valid_pixel, "INVALID_PARAMS")):
        first = valid_pixel if bad == valid_pixel else {**valid_pixel, "frame": 2}
        edit("edit_pixels", {"edits": [first, bad]}, code)
    # An invalid overwritten coordinate must still reject the entire request.
    edit("edit_pixels", {"edits": [{**valid_pixel, "pixels": [{"x": 1, "y": 1, **red, "a": 256}, {"x": 1, "y": 1, **red}]}]}, "INVALID_PARAMS")
    for bad in ({**valid_region, "dx": 16}, {**valid_region, "mask": {"x": 15, "y": 0, "width": 2, "height": 1, "bits": "10"}}, {**valid_region, "mask": {"x": 0, "y": 0, "width": 2, "height": 1, "bits": "00"}}, {**valid_region, "mask": {"x": 0, "y": 0, "width": 2, "height": 1, "bits": "1"}}, valid_region):
        # Use a distinct valid first target so the invalid final entry is tested.
        first = region_batch["edits"][1]
        code = "OUTSIDE_CANVAS" if bad.get("dx") == 16 or bad.get("mask", {}).get("x") == 15 else "INVALID_PARAMS"
        entries = [valid_region, bad] if bad == valid_region else [first, bad]
        edit("translate_regions", {"edits": entries}, code)
    for method, params in (("edit_pixels", batch), ("translate_regions", region_batch)):
        edit(method, {**params, "expectedRevision": current()["revision"] + 1}, "STALE_REVISION")
        edit(method, {**params, "sessionId": "wrong"}, "SESSION_MISMATCH")
        edit(method, {**params, "dryRun": "yes"}, "INVALID_PARAMS")
    edit("update_layer", {"layerId": group, "editable": False})
    edit("edit_pixels", {"edits": [batch["edits"][1]]}, "LAYER_LOCKED")
    edit("translate_regions", {"edits": [valid_region]}, "LAYER_LOCKED")
    edit("undo")
    for method, params in (("edit_pixels", batch), ("translate_regions", region_batch)):
        client.request("set_paused", {"paused": True})
        edit(method, params, "PAUSED")
        edit(method, {**params, "dryRun": True}, "PAUSED")
        client.request("set_paused", {"paused": False})
    print("PASS: multi-layer/frame pixel batches and heterogeneous sparse-region moves/copies, exact independent pixels, dry runs/no-ops/redo, one-step repeated Undo/Redo and full validation/guard/focus/mask preservation.")

    # Fixtures include cropped off-canvas pixels, opacity and cel user data.
    for mode in (32, 8, 16):
        name = f"correction-workflows/raw-{mode}.ase"
        fixture(assets / name, mode=mode, palettes=mode == 8)
        loaded = client.request("open", {"path": name})
        for method, params in (("edit_pixels", batch), ("translate_regions", region_batch)):
            edit(method, params, "INACTIVE_DOCUMENT")
        document_id, layer = loaded["documentId"], loaded["layers"][0]["layerId"]
        edit("save", {"path": f"correction-workflows/raw-{mode}-before.ase"})
        before = current()
        baseline = raw_frames(directory / f"raw-{mode}-before.ase")
        entries = [{"layerId": layer, "frame": frame, "mask": {"x": 0, "y": 2, "width": 2, "height": 2, "bits": "1111"}, "dx": 2, "dy": 1, "copy": frame == 1} for frame in (0, 1)]
        preview = edit("translate_regions", {"edits": entries, "dryRun": True})
        assert preview["wouldEditCels"] == 2 and current() == before
        edit("translate_regions", {"edits": entries})
        after = current()
        for frame in (0, 1):
            old_cel = next(c for c in before["layers"][0]["cels"] if c["frame"] == frame)
            new_cel = next(c for c in after["layers"][0]["cels"] if c["frame"] == frame)
            assert old_cel["opacity"] == new_cel["opacity"] == 192
            assert old_cel["userData"] == new_cel["userData"]
        assert after["frames"] == before["frames"] and after["palettes"] == before["palettes"]
        edit("save", {"path": f"correction-workflows/raw-{mode}-after.ase"})
        actual = raw_frames(directory / f"raw-{mode}-after.ase")
        stride = mode // 8

        def native_pixels(frame):
            payload = next(value for kind, value in frame[1] if kind == 0x2005)
            x, y = struct.unpack_from("<hh", payload, 2)
            w, h = struct.unpack_from("<HH", payload, 16)
            return {(x + xx, y + yy): payload[20 + (yy * w + xx) * stride:20 + (yy * w + xx + 1) * stride] for yy in range(h) for xx in range(w)}

        for index in (0, 1):
            old, new = native_pixels(baseline[index]), native_pixels(actual[index])
            expected_raw = dict(old)
            for x in (0, 1):
                for y in (2, 3):
                    if index == 0:
                        expected_raw[(x, y)] = bytes(stride)
                    expected_raw[(x + 2, y + 1)] = old[(x, y)]
            for p in set(old) | set(new) | set(expected_raw):
                assert new.get(p, bytes(stride)) == expected_raw.get(p, bytes(stride)), (mode, index, p)
            assert new[(-1, 2)] == old[(-1, 2)] and new[(-1, 3)] == old[(-1, 3)]
        edit("undo")
        edit("save", {"path": f"correction-workflows/raw-{mode}-undo.ase"})
        assert raw_frames(directory / f"raw-{mode}-undo.ase") == baseline
        if mode == 8:
            before = current()
            indexed = [{"layerId": layer, "frame": i, "pixels": [{"x": 1, "y": 2, "index": 2}]} for i in (0, 1)]
            assert edit("edit_pixels", {"edits": indexed, "dryRun": True})["wouldEditCels"] == 2 and current() == before
            edit("edit_pixels", {"edits": indexed})
            assert current()["palettes"] == before["palettes"]
            edit("save", {"path": "correction-workflows/indexed-pixels-after.ase"})
            painted = raw_frames(directory / "indexed-pixels-after.ase")
            for frame in (0, 1):
                expected_raw = native_pixels(baseline[frame]); expected_raw[(1, 2)] = bytes((2,))
                assert native_pixels(painted[frame]) == expected_raw
            edit("undo")
            edit("edit_pixels", {"edits": [indexed[0], {**indexed[1], "pixels": [{"x": 0, "y": 0, "index": 3}]}]}, "PALETTE_INDEX_OUT_OF_RANGE")
            oversized = [{"layerId": layer, "frame": i, "pixels": [{"x": 0, "y": 2, "index": 1}] * 8193} for i in (0, 1)]
            edit("edit_pixels", {"edits": oversized}, "LIMIT_EXCEEDED")
            edit("edit_pixels", {"edits": [indexed[0]] * 257}, "INVALID_PARAMS")
        if mode == 16:
            edit("edit_pixels", {"edits": [{"layerId": layer, "frame": 0, "pixels": [{"x": 0, "y": 0, **red}]}]}, "UNSUPPORTED_COLOR_MODE")
    print("PASS: native RGBA/indexed/grayscale raw-region corrections retain off-canvas pixels/opacity/user data/palettes; Undo restores exact native bytes, and indexed batches enforce each frame's palette.")

    # Nonzero transparent index, including one outside the small visible palette.
    name = "correction-workflows/transparent-seven.ase"
    fixture(assets / name, mode=8, count=2, palettes=True)
    data = bytearray((assets / name).read_bytes()); data[28] = 7
    (assets / name).write_bytes(data)
    loaded = client.request("open", {"path": name})
    document_id, layer = loaded["documentId"], loaded["layers"][0]["layerId"]
    assert current()["transparentIndex"] == 7
    absent = edit("create_layer", {"name": "Absent indexed cels"})["createdLayerId"]
    before = current()
    assert edit("edit_pixels", {"edits": [{"layerId": absent, "frame": 0, "pixels": [{"x": 0, "y": 0, "index": 7}]}]})["changedPixels"] == 0
    assert current() == before
    indexed = [{"layerId": layer, "frame": i, "pixels": [{"x": 0, "y": 2, "index": 7}]} for i in (0, 1)]
    assert edit("edit_pixels", {"edits": indexed})["changedPixels"] == 2
    edit("save", {"path": "correction-workflows/transparent-seven-pixels.ase"})
    for frame in raw_frames(directory / "transparent-seven-pixels.ase"):
        payload = next(value for kind, value in frame[1] if kind == 0x2005)
        assert payload[20:] == bytes((1, 7, 0, 2, 1, 2))
    edit("undo")
    region = {"layerId": layer, "frame": 0, "mask": {"x": 0, "y": 2, "width": 1, "height": 1, "bits": "1"}, "dx": 1, "dy": 0}
    edit("translate_regions", {"edits": [region] * 257}, "INVALID_PARAMS")
    assert edit("translate_regions", {"edits": [region]})["changedPixels"] == 2
    edit("save", {"path": "correction-workflows/transparent-seven-region.ase"})
    frame = raw_frames(directory / "transparent-seven-region.ase")[0]
    payload = next(value for kind, value in frame[1] if kind == 0x2005)
    assert payload[20:] == bytes((1, 7, 2, 2, 1, 2))
    print("PASS: exact indexed pixel bytes, total-input/target limits, overwritten invalid values, nonzero transparent-index erasure/moves and absent-cel no-ops.")

    for linked, background in ((True, False), (False, True)):
        name = "correction-workflows/linked.ase" if linked else "correction-workflows/background.ase"
        fixture(assets / name, linked=linked, background=background)
        loaded = client.request("open", {"path": name})
        document_id, layer = loaded["documentId"], loaded["layers"][0]["layerId"]
        code = "LINKED_CEL" if linked else "UNSUPPORTED_LAYER"
        edit("edit_pixels", {"edits": [{"layerId": layer, "frame": 1, "pixels": [{"x": 1, "y": 2, **green}]}]}, code)
        edit("translate_regions", {"edits": [{"layerId": layer, "frame": 1, "mask": {"x": 0, "y": 2, "width": 1, "height": 1, "bits": "1"}, "dx": 1, "dy": 0}]}, code)
        if linked:
            edit("unlink_cel", {"layerId": layer, "frame": 1})
            untouched = image(layer, 0)
            edit("edit_pixels", {"edits": [{"layerId": layer, "frame": 1, "pixels": [{"x": 1, "y": 2, **green}]}]})
            assert image(layer, 0) == untouched

    # Two 4-MiB images each fit a single growth plan, but not aggregate growth.
    name = "correction-workflows/growth.ase"
    fixture(assets / name, count=2)
    data = (assets / name).read_bytes()
    layer_size = struct.unpack_from("<I", data, 144)[0]
    layer_chunk = data[144:144 + layer_size]
    payload = struct.pack("<HhhBH", 0, 0, 0, 255, 2) + bytes(7) + struct.pack("<HH", 1024, 1024) + zlib.compress(bytes((40, 150, 90, 255)) * (1024 * 1024))
    cel = struct.pack("<IH", 6 + len(payload), 0x2005) + payload
    frames = []
    for index in (0, 1):
        chunks = (layer_chunk if index == 0 else b"") + cel
        frames.append(struct.pack("<IHHH", 16 + len(chunks), 0xF1FA, 2 if index == 0 else 1, 100) + bytes(6) + chunks)
    header = bytearray(data[:128]); struct.pack_into("<I", header, 0, 128 + sum(map(len, frames)))
    (assets / name).write_bytes(header + b"".join(frames))
    loaded = client.request("open", {"path": name})
    document_id, layer = loaded["documentId"], loaded["layers"][0]["layerId"]
    edit("edit_cels", {"edits": [{"layerId": layer, "frame": i, "x": 4000} for i in (0, 1)]})
    edits = [{"layerId": layer, "frame": i, "pixels": [{"x": 0, "y": 0, **red}]} for i in (0, 1)]
    assert edit("edit_pixels", {"edits": edits[:1], "dryRun": True})["wouldEditCels"] == 1
    edit("edit_pixels", {"edits": edits}, "LIMIT_EXCEEDED")
    edit("translate_regions", {"edits": [{"layerId": layer, "frame": i, "mask": {"x": 0, "y": 0, "width": 1, "height": 1, "bits": "1"}, "dx": 1, "dy": 0} for i in (0, 1)]}, "LIMIT_EXCEEDED")
    edit("update_cel", {"layerId": layer, "frame": 0, "x": 32767, "y": 32767})
    edit("edit_pixels", {"edits": edits[:1]}, "LIMIT_EXCEEDED")
    huge = client.request("create", {"width": 1024, "height": 1024, "name": "Correction scratch guards"})
    document_id, layer = huge["documentId"], huge["layers"][0]["layerId"]
    for index in range(1, 9):
        edit("add_frame", {"index": index})
    edits = [{"layerId": layer, "frame": i, "pixels": [{"x": 0, "y": 0, **red}, {"x": 1023, "y": 1023, **red}]} for i in range(9)]
    edit("edit_pixels", {"edits": edits}, "LIMIT_EXCEEDED")
    regions = [{"layerId": layer, "frame": i, "mask": {"x": 0, "y": 0, "width": 1, "height": 1, "bits": "1"}, "dx": 1023, "dy": 1023} for i in range(9)]
    edit("translate_regions", {"edits": regions}, "LIMIT_EXCEEDED")
    print("PASS: linked/background guards and explicit unlink, aggregate off-canvas growth/far-offset and patch scratch refusals before mutation/allocation.")

    # Save/close only our documents; never touch originals or another editor.
    ours = [doc["documentId"] for doc in client.request("list_documents")["documents"] if doc["documentId"] not in original_ids]
    for identity in reversed(ours):
        docs = client.request("list_documents")
        state = client.request("inspect", {"documentId": identity})
        if docs["activeDocumentId"] != identity:
            client.request("activate_document", {"documentId": identity, "expectedRevision": state["revision"], "expectedActiveDocumentId": docs["activeDocumentId"]})
        saved = client.request("save", {"documentId": identity, "expectedRevision": state["revision"], "path": f"correction-workflows/closed-{identity}.ase"})
        client.request("close_document", {"documentId": identity, "expectedRevision": saved["revision"], "confirm": True})

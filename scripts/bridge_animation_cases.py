"""Step 2: real GUI atomic cel/frame/selection workflows. GPL-2.0-only."""
import base64
import copy
import struct
import uuid
import zlib


def canonical_inspection(state):
    """Only recovery's initial 0->1 counters are equivalent, like native revisions.

    Keep all higher counters, identities, properties, history, and revision;
    never mutate the raw inspection returned by the editor.
    """
    state = copy.deepcopy(state)
    for layer in state.get("layers", []):
        if layer.get("version") == 0:
            layer["version"] = 1
        for cel in layer.get("cels", []):
            if cel.get("imageVersion") == 0:
                cel["imageVersion"] = 1
    return state


def fixture(path, linked=False, background=False, mode=32, palettes=False, count=3):
    """Small native fixture with cropped/off-canvas pixels, links and cel user data."""
    def chunk(kind, payload):
        return struct.pack("<IH", len(payload) + 6, kind) + payload

    name = b"Native test"
    layer = struct.pack("<HHHHHHB", 3 | (8 if background else 0), 0, 0, 0, 0, 0, 255) + bytes(3) + struct.pack("<H", len(name)) + name
    frames = []
    for i in range(count):
        chunks = [chunk(0x2004, layer)] if i == 0 else []
        pixels = bytes(((10 + i) % 256, 20, 30, 255, 70, 80, 90, 128, 0, 0, 0, 0, 180, 190, 200, 255, 40, 50, 60, 255, 210, 220, 230, 255))
        if mode == 8:
            pixels = bytes((1, 2, 0, 2, 1, 2))
        elif mode == 16:
            pixels = bytes((20, 255, 60, 128, 0, 0, 100, 255, 160, 255, 240, 255))
        cel = struct.pack("<HhhBH", 0, -1, 2, 192, 1 if linked and i == 1 else 2) + bytes(7)
        cel += struct.pack("<H", 0) if linked and i == 1 else struct.pack("<HH", 3, 2) + zlib.compress(pixels)
        chunks.append(chunk(0x2005, cel))
        if not (linked and i == 1):
            text = b"preserve me"
            chunks.append(chunk(0x2020, struct.pack("<IH", 1, len(text)) + text))
        if (mode == 8 and i == 0) or palettes:
            entries = b"".join(struct.pack("<H", 0) + bytes((j * 70 + (i if palettes else 0), j * 50, j * 30, 255)) for j in range(3))
            chunks.append(chunk(0x2019, struct.pack("<III", 3, 0, 2) + bytes(8) + entries))
        data = b"".join(chunks)
        frames.append(struct.pack("<IHHH", 16 + len(data), 0xF1FA, len(chunks), 70 + i * 30) + bytes(6) + data)
    header = bytearray(128)
    struct.pack_into("<IHHHHHIH", header, 0, 128 + sum(map(len, frames)), 0xA5E0, count, 16, 16, mode, 1, 100)
    header[34] = header[35] = 1
    path.write_bytes(header + b"".join(frames))


def raw_frames(path):
    data = path.read_bytes()
    frames, offset = [], 128
    for _ in range(struct.unpack_from("<H", data, 6)[0]):
        size, _, count, duration = struct.unpack_from("<IHHH", data, offset)
        chunks, cursor = [], offset + 16
        for _ in range(count):
            length, kind = struct.unpack_from("<IH", data, cursor)
            payload = data[cursor + 6:cursor + length]
            if kind == 0x2005 and struct.unpack_from("<H", payload, 7)[0] == 2:
                payload = payload[:20] + zlib.decompress(payload[20:])
            if kind in (0x2005, 0x2020):
                chunks.append((kind, payload))
            cursor += length
        frames.append((duration, chunks))
        offset += size
    # Saving a reordered link chain may choose a different earliest frame as
    # the on-disk owner. Resolve links to equivalent cel bytes/user data rather
    # than mistaking a lossless storage-layout change for pixel corruption.
    for index, (duration, chunks) in enumerate(frames):
        for kind, payload in chunks:
            if kind == 0x2005 and struct.unpack_from("<H", payload, 7)[0] == 1:
                linked = struct.unpack_from("<H", payload, 16)[0]
                assert linked < index
                source_chunks = frames[linked][1]
                source = next(value for source_kind, value in source_chunks if source_kind == 0x2005)
                resolved = payload[:7] + struct.pack("<H", 2) + bytes(7) + source[16:]
                frames[index] = (duration, [(0x2005, resolved)] + [(k, v) for k, v in source_chunks if k == 0x2020])
    return frames


def large_fixture(path):
    fixture(path, count=8)
    data = path.read_bytes()
    layer_size = struct.unpack_from("<I", data, 144)[0]
    layer = data[144:144 + layer_size]
    payload = struct.pack("<HhhBH", 0, 0, 0, 255, 2) + bytes(7) + struct.pack("<HH", 1024, 1024) + zlib.compress(bytes((40, 150, 90, 255)) * (1024 * 1024))
    cel = struct.pack("<IH", 6 + len(payload), 0x2005) + payload
    frames = []
    for i in range(8):
        chunks = (layer if i == 0 else b"") + cel
        frames.append(struct.pack("<IHHH", 16 + len(chunks), 0xF1FA, 2 if i == 0 else 1, 100) + bytes(6) + chunks)
    header = bytearray(data[:128])
    struct.pack_into("<I", header, 0, 128 + sum(map(len, frames)))
    path.write_bytes(header + b"".join(frames))


def test_animation_workflows(client, assets, smoke):
    original_ids = {doc["documentId"] for doc in client.request("list_documents")["documents"]}
    directory = assets / "animation-workflows"
    directory.mkdir()
    doc = client.request("create", {"width": 16, "height": 16, "name": "Atomic animation tests"})
    document_id = doc["documentId"]
    base = doc["layers"][0]["layerId"]
    red = {"r": 210, "g": 40, "b": 70, "a": 255}
    blue = {"r": 40, "g": 150, "b": 210, "a": 128}

    def current():
        return canonical_inspection(client.request("inspect", {"documentId": document_id}))

    def target():
        return {"documentId": document_id, "expectedRevision": current()["revision"]}

    def image(frame=0, mask=False):
        result = client.request("render_selection" if mask else "render", {"documentId": document_id, "frame": frame, "scale": 1, "mode": "mask"})
        path = directory / "preview.png"
        path.write_bytes(base64.b64decode(result["pngBase64"]))
        return smoke.read_png(path)[2]

    def images():
        count = current()["frameCount"]
        # Limit/fixture guards inspect all cel metadata but only sample huge
        # frame-count fixtures; 256 separate preview requests add no coverage
        # for a prevalidated refusal and prolong unrelated GUI background work.
        frames = range(count) if count <= 16 else (0, count // 2, count - 1)
        return [image(i) for i in frames]

    def mutate(method, params=None, error=None):
        before, pixels = current(), images() if error else None
        response = client.request(method, {**target(), **(params or {})}, expected_error=error)
        if error:
            after, after_pixels = current(), images()
            assert canonical_inspection(after) == canonical_inspection(before), (method, error, {key: (before.get(key), after.get(key)) for key in after if after.get(key) != before.get(key)})
            assert after_pixels == pixels, (method, error, [i for i, (a, b) in enumerate(zip(pixels, after_pixels)) if a != b])
        return response

    def metadata():
        result = {key: value for key, value in current().items() if key not in ("revision", "activeFrame", "activeLayerId", "canUndo", "canRedo")}
        # Native undo intentionally advances model version counters. Compare
        # persistent semantics/IDs, not those bookkeeping counters.
        for layer in result["layers"]:
            layer.pop("version")
            for cel in layer.get("cels", []):
                cel.pop("imageVersion")
        return result

    def undo_redo(before, after, state_before=None):
        for _ in range(2):
            mutate("undo")
            assert images() == before
            if state_before is not None:
                state_after = metadata()
                assert state_after == state_before, {key: (state_before.get(key), state_after.get(key)) for key in state_after if state_after.get(key) != state_before.get(key)}
            mutate("redo")
            assert images() == after

    def select(x1=2, y1=2, x2=4, y2=3, **extra):
        return mutate("set_selection", {"x1": x1, "y1": y1, "x2": x2, "y2": y2, **extra})

    def paint(frame=0, layer=None, **extra):
        return {"layerId": base if layer is None else layer, "frame": frame, **extra}

    mutate("set_pixels", {**paint(), "pixels": [{"x": 2, "y": 2, **red}, {"x": 4, "y": 3, **blue}, {"x": 9, "y": 10, **red}]})
    mutate("add_frame", {"index": 1})
    mutate("add_frame", {"index": 2, "copyFrom": 0})
    group = mutate("create_layer", {"name": "Nested group", "type": "group"})["createdLayerId"]
    other = mutate("create_layer", {"name": "Hidden destination", "parentId": group})["createdLayerId"]
    mutate("update_layer", {"layerId": other, "visible": False})
    select()
    mutate("save", {"path": "animation-workflows/baseline.ase"})
    original, state = images(), metadata()
    mutate("copy_cel", {**paint(1), "sourceLayerId": base, "sourceFrame": 0})
    assert image(1) == original[0]
    undo_redo(original, images(), state)
    mutate("copy_cel", {**paint(1), "sourceLayerId": base, "sourceFrame": 2}, "CEL_EXISTS")
    before = current()
    mutate("copy_cel", {**paint(), "sourceLayerId": base, "sourceFrame": 0})
    assert current() == before  # No-op consumes no history/revision/focus.
    mutate("copy_cel", {**paint(1, other), "sourceLayerId": base, "sourceFrame": 0})
    mutate("set_pixels", {**paint(1), "pixels": [{"x": 2, "y": 2, **blue}]})
    assert image(0) == original[0] and image(1) != original[0]
    mutate("copy_cel", {**paint(1), "sourceLayerId": base, "sourceFrame": 0, "overwrite": True})
    assert image(1) == original[0]
    mutate("set_frame_durations", {"durations": [{"frame": 0, "durationMs": 80}, {"frame": 1, "durationMs": 130}, {"frame": 2, "durationMs": 210}]})
    print("PASS: independent whole-cel cross-layer/frame copy, explicit replacement/no-op, mask isolation, native undo/redo.")

    # Atomic heterogeneous multi-frame properties/transforms and timing batches.
    before, state = images(), metadata()
    edits = [{**paint(0), "x": -2, "y": 1, "opacity": 180, "operation": "rotate_cw"}, {**paint(2), "x": 5, "operation": "flip_horizontal"}]
    mutate("edit_cels", {"edits": edits + [{**paint(1), "opacity": 256}]}, "INVALID_PARAMS")
    mutate("edit_cels", {"edits": [edits[0], edits[0]]}, "INVALID_PARAMS")
    mutate("edit_cels", {"edits": [{**paint(1)}]}, "INVALID_PARAMS")
    params, request_id = {**target(), "edits": edits}, str(uuid.uuid4())
    batch = client.request("edit_cels", params, request_id=request_id)
    assert client.request("edit_cels", params, request_id=request_id) == batch
    assert image(0) != before[0] and image(2) != before[2] and image(1) == before[1]
    undo_redo(before, images(), state)
    mutate("undo")
    before = current()
    mutate("edit_cels", {"edits": [{**paint(), "opacity": 255}]})
    assert current() == before
    durations = [{"frame": 0, "durationMs": 1}, {"frame": 2, "durationMs": 65535}]
    mutate("set_frame_durations", {"durations": durations + [{"frame": 1, "durationMs": 0}]}, "INVALID_PARAMS")
    mutate("set_frame_durations", {"durations": [durations[0], durations[0]]}, "INVALID_PARAMS")
    before = current()
    mutate("set_frame_durations", {"durations": durations})
    assert [frame["durationMs"] for frame in current()["frames"]] == [1, 130, 65535]
    mutate("undo")
    assert current()["frames"] == before["frames"]
    mutate("redo")
    assert images() == original[:1] * 3
    after = current()
    mutate("set_frame_durations", {"durations": durations})
    assert current() == after
    mutate("undo")
    print("PASS: batch prevalidation/duplicate refusal, heterogeneous cel updates and timing in one undo step; unchanged batch preserves redo.")

    tag = mutate("create_tag", {"name": "First pair", "from": 0, "to": 1})["createdTagId"]
    before, state = images(), metadata()
    mutate("duplicate_frames", {"frames": [2, 0], "index": 1})
    assert images() == [before[0], before[2], before[0], before[1], before[2]]
    assert [frame["durationMs"] for frame in current()["frames"]] == [80, 210, 80, 130, 210]
    assert current()["tags"][0]["to"] == 3
    undo_redo(before, images(), state)
    mutate("undo")
    mutate("duplicate_frames", {"frames": [0, 0], "index": 0}, "INVALID_PARAMS")
    mutate("reorder_frames", {"order": [1, 0]}, "INVALID_PARAMS")
    mutate("reorder_frames", {"order": [1, 1, 0]}, "INVALID_PARAMS")
    mutate("reorder_frames", {"order": [0, 2, 1]}, "TAG_SPLIT")
    before = current()
    mutate("reorder_frames", {"order": [0, 1, 2]})
    assert current() == before
    state, before = metadata(), images()
    mutate("reorder_frames", {"order": [2, 0, 1]})
    assert images() == [before[2], before[0], before[1]]
    assert [frame["durationMs"] for frame in current()["frames"]] == [210, 80, 130]
    assert (current()["tags"][0]["from"], current()["tags"][0]["to"]) == (1, 2)
    undo_redo(before, images(), state)
    # A later native layer deletion reconstructs objects on undo. The reorder
    # command must re-resolve current objects rather than retaining stale pointers.
    mutate("remove_layer", {"layerId": group, "recursive": True})
    mutate("undo")
    mutate("undo")
    assert images() == before and metadata() == state
    mutate("redo")
    mutate("undo")
    print("PASS: overlapping ordered frame duplication, independent copies/timing/tags, full permutation/tag-split refusal, undo after layer recreation.")

    # Selected-pixel transforms: nonsquare anchor, sparse mask holes, overlap,
    # transparent overwrites, and all frames/mask undone by a single transaction.
    for operation in ("flip_horizontal", "flip_vertical", "rotate_cw", "rotate_ccw", "rotate_180"):
        select()
        mutate("set_selection", {"x1": 3, "y1": 2, "x2": 3, "y2": 2, "mode": "subtract"})
        before, state, old_mask = images(), metadata(), image(mask=True)
        points = {(x, y) for y in range(2, 4) for x in range(2, 5)} - {(3, 2)}
        def mapped(x, y):
            x, y = x - 2, y - 2
            if operation == "flip_horizontal": return 2 + 2 - x, 2 + y
            if operation == "flip_vertical": return 2 + x, 2 + 1 - y
            if operation == "rotate_cw": return 2 + 1 - y, 2 + x
            if operation == "rotate_ccw": return 2 + y, 2 + 2 - x
            return 2 + 2 - x, 2 + 1 - y
        expected = []
        for pixels in before:
            result = bytearray(pixels)
            for x, y in points: result[(y * 16 + x) * 4:(y * 16 + x) * 4 + 4] = bytes(4)
            for x, y in points:
                dx, dy = mapped(x, y)
                result[(dy * 16 + dx) * 4:(dy * 16 + dx) * 4 + 4] = pixels[(y * 16 + x) * 4:(y * 16 + x) * 4 + 4]
            expected.append(bytes(result))
        mutate("transform_selection", {"layerId": base, "frames": [0, 2], "operation": operation})
        assert images() == [expected[0], before[1], expected[2]], operation
        new_mask = image(mask=True)
        selected = {(x, y) for y in range(16) for x in range(16) if new_mask[(y * 16 + x) * 4 + 3]}
        assert selected == {mapped(x, y) for x, y in points}
        undo_redo(before, images(), state)
        mutate("undo")
        assert image(mask=True) == old_mask
    select(14, 2, 15, 5)
    mutate("transform_selection", {"layerId": base, "frames": [0], "operation": "rotate_cw"}, "OUTSIDE_CANVAS")
    mutate("modify_selection", {"action": "none"})
    mutate("transform_selection", {"layerId": base, "frames": [0, 1], "operation": "flip_horizontal"}, "NO_SELECTION")
    select()
    mutate("transform_selection", {"layerId": base, "frames": [0, 0], "operation": "flip_horizontal"}, "INVALID_PARAMS")
    mutate("transform_selection", {"layerId": base, "frames": [0, 3], "operation": "flip_horizontal"}, "INVALID_PARAMS")
    print("PASS: all five selected-region transforms, exact nonsquare/sparse masks and transparent overlap, multi-frame atomic undo and no clipping/fallback.")

    guarded = {
        "copy_cel": {**paint(1, other), "sourceLayerId": base, "sourceFrame": 0, "overwrite": True},
        "duplicate_frames": {"frames": [0, 1], "index": 1},
        "reorder_frames": {"order": [2, 0, 1]},
        "edit_cels": {"edits": [{**paint(0), "x": -1}, {**paint(2), "x": -2}]},
        "set_frame_durations": {"durations": [{"frame": 0, "durationMs": 50}]},
        "transform_selection": {"layerId": base, "frames": [0, 2], "operation": "rotate_cw"},
    }
    for method, params in guarded.items():
        mutate(method, {**params, "expectedRevision": current()["revision"] + 100}, "STALE_REVISION")
        mutate(method, {**params, "sessionId": "other-editor"}, "SESSION_MISMATCH")
    client.request("set_paused", {"paused": True})
    for method, params in guarded.items(): mutate(method, params, "PAUSED")
    client.request("set_paused", {"paused": False})
    inactive_id = document_id
    inactive_revision = current()["revision"]
    new = client.request("create", {"width": 8, "height": 8, "name": "Inactive guard"})
    for method, params in guarded.items():
        client.request(method, {"documentId": inactive_id, "expectedRevision": inactive_revision, **params}, expected_error="INACTIVE_DOCUMENT")
    client.request("activate_document", {"documentId": inactive_id, "expectedRevision": inactive_revision, "expectedActiveDocumentId": new["documentId"]})
    mutate("update_layer", {"layerId": group, "editable": False})
    mutate("copy_cel", guarded["copy_cel"], "LAYER_LOCKED")
    mutate("duplicate_frames", guarded["duplicate_frames"], "LAYER_LOCKED")
    mutate("reorder_frames", guarded["reorder_frames"], "LAYER_LOCKED")
    mutate("edit_cels", {"edits": [{**paint(0), "x": 1}, {**paint(1, other), "opacity": 100}]}, "LAYER_LOCKED")
    mutate("update_layer", {"layerId": group, "editable": True})
    mutate("update_layer", {"layerId": base, "editable": False})
    mutate("copy_cel", {**paint(0, other), "sourceLayerId": base, "sourceFrame": 0})
    mutate("update_layer", {"layerId": base, "editable": True})

    blank = client.request("create", {"width": 16, "height": 16, "name": "Mask-only transform"})
    document_id, base = blank["documentId"], blank["layers"][0]["layerId"]
    mutate("add_frame", {"index": 1})  # A genuinely absent image cel, not a blank image.
    select(2, 2, 4, 3)
    mutate("save", {"path": "animation-workflows/blank.ase"})
    before, mask = current(), image(mask=True)
    result = mutate("transform_selection", {"layerId": base, "frames": [1], "operation": "rotate_cw"})
    assert result["transformedFrames"] == 0 and not current()["modified"] and current()["layers"][0]["cels"] == before["layers"][0]["cels"], current()
    mutate("undo")
    assert image(mask=True) == mask and not current()["modified"]
    before_noop = current()
    result = mutate("transform_selection", {"layerId": base, "frames": [1], "operation": "flip_horizontal"})
    assert current() == before_noop
    print("PASS: locked sources can be read; transparent/missing-cel mask-only transforms preserve saved state and no-op history.")

    for filename, linked, background, mode, palettes in (("links.ase", True, False, 32, False), ("background.ase", False, True, 32, False), ("indexed.ase", False, False, 8, False), ("gray.ase", False, False, 16, False), ("palettes.ase", False, False, 8, True)):
        fixture(directory / filename, linked, background, mode, palettes)
        loaded = client.request("open", {"path": "animation-workflows/" + filename})
        document_id, base = loaded["documentId"], loaded["layers"][0]["layerId"]
        if palettes:
            mutate("copy_cel", {**paint(2), "sourceLayerId": base, "sourceFrame": 0, "overwrite": True}, "UNSUPPORTED_PALETTES")
            mutate("duplicate_frames", {"frames": [0], "index": 1}, "UNSUPPORTED_PALETTES")
            mutate("reorder_frames", {"order": [2, 1, 0]}, "UNSUPPORTED_PALETTES")
            mutate("set_frame_durations", {"durations": [{"frame": 0, "durationMs": 120}, {"frame": 1, "durationMs": 180}]})
            continue
        if background:
            mutate("copy_cel", {**paint(2), "sourceLayerId": base, "sourceFrame": 0, "overwrite": True}, "UNSUPPORTED_LAYER")
        else:
            mutate("copy_cel", {**paint(2), "sourceLayerId": base, "sourceFrame": 0, "overwrite": True})
            mutate("save", {"path": f"animation-workflows/copied-{filename}"})
            raw = raw_frames(directory / f"copied-{filename}")
            assert raw[0][1] == raw[2][1], (filename, raw)  # raw off-canvas/index/gray/user-data bytes
            if linked:
                mutate("copy_cel", {**paint(1), "sourceLayerId": base, "sourceFrame": 2, "overwrite": True}, "LINKED_CEL")
                select(0, 2, 1, 3)
                mutate("transform_selection", {"layerId": base, "frames": [2, 1], "operation": "rotate_cw"}, "LINKED_CEL")
                mutate("edit_cels", {"edits": [{**paint(2), "x": 1}, {**paint(1), "x": 2}]}, "LINKED_CEL")
        before = images()
        mutate("duplicate_frames", {"frames": [1, 0], "index": 0})
        assert images() == [before[1], before[0], *before]
        layers = current()["layers"]
        assert all(cel["links"] == 0 for cel in layers[0]["cels"] if cel["frame"] < 2)
        mutate("undo")
        mutate("reorder_frames", {"order": [2, 1, 0]})
        assert images() == list(reversed(before))
        mutate("undo")
        assert images() == before
        mutate("redo")
        mutate("save", {"path": f"animation-workflows/reordered-{filename}"})
        original_raw, saved_raw = raw_frames(directory / (f"copied-{filename}" if not background else filename)), raw_frames(directory / f"reordered-{filename}")
        for old, new_index in ((0, 2), (2, 0)):
            assert original_raw[old] == saved_raw[new_index], (filename, old)
        if linked:
            cels = current()["layers"][0]["cels"]
            assert cels[1]["links"] > 0 and cels[2]["links"] > 0
        reopened = client.request("open", {"path": f"animation-workflows/reordered-{filename}"})
        document_id, base = reopened["documentId"], reopened["layers"][0]["layerId"]
        assert images() == list(reversed(before))
    print("PASS: pause/session/revision/inactive/locked/linked guards, RGBA/indexed/grayscale raw cel/user-data preservation, background/range workflows, palette refusal and save/reopen.")

    # Frame and preallocation limits without huge images or partial insertion.
    fixture(directory / "256.ase", count=256)
    loaded = client.request("open", {"path": "animation-workflows/256.ase"})
    document_id, base = loaded["documentId"], loaded["layers"][0]["layerId"]
    mutate("duplicate_frames", {"frames": [0], "index": 256}, "LIMIT_EXCEEDED")
    mutate("update_cel", {**paint(), "x": 32767, "y": -32768})
    select(0, 0, 2, 1)
    mutate("transform_selection", {"layerId": base, "frames": [1, 0], "operation": "rotate_cw"}, "LIMIT_EXCEEDED")
    print("PASS: frame ceiling and aggregate far-off-canvas growth refusal before mutation/allocation.")

    large_fixture(directory / "32mib.ase")
    loaded = client.request("open", {"path": "animation-workflows/32mib.ase"})
    document_id, base = loaded["documentId"], loaded["layers"][0]["layerId"]
    destination = mutate("create_layer", {"name": "Empty destination"})["createdLayerId"]
    mutate("copy_cel", {**paint(0, destination), "sourceLayerId": base, "sourceFrame": 0}, "LIMIT_EXCEEDED")
    mutate("duplicate_frames", {"frames": [0, 1], "index": 0}, "LIMIT_EXCEEDED")
    assert not current()["layers"][1]["cels"] and current()["frameCount"] == 8
    print("PASS: independent-copy/range aggregate 32 MiB preallocation limits without partial images/frames.")

    # Retire only this helper's generated documents, saving any remaining work
    # before close. This lets the full suite stay below its 32-document ceiling.
    for item in client.request("list_documents")["documents"]:
        if item["documentId"] in original_ids:
            continue
        document_id = item["documentId"]
        selected = client.request("list_documents")["activeDocumentId"]
        client.request("activate_document", {**target(), "expectedActiveDocumentId": selected})
        if not item["hasFile"] or item["modified"]:
            mutate("save", {"path": f"animation-workflows/cleanup-{document_id}.ase"})
        mutate("close_document", {"confirm": True})
    assert {doc["documentId"] for doc in client.request("list_documents")["documents"]} == original_ids

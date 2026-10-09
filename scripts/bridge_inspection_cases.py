"""Read-only animation inspection in test-owned native GUI documents. GPLv2."""
import base64
import struct
import zlib
from bridge_animation_cases import canonical_inspection


def test_frame_differences(client, assets, smoke):
    document = client.request("create", {"width": 8, "height": 8, "name": "Frame difference tests"})
    document_id = document["documentId"]
    layer = document["layers"][0]["layerId"]

    def current():
        return canonical_inspection(client.request("inspect", {"documentId": document_id}))

    def edit(method, **params):
        return client.request(method, {"documentId": document_id, "expectedRevision": current()["revision"], **params})

    def decode(result):
        path = assets / "inspection-check.png"
        path.write_bytes(base64.b64decode(result["pngBase64"]))
        return smoke.read_png(path)

    def diff(a=0, b=1, **params):
        return client.request("render_frame_diff", {"documentId": document_id, "fromFrame": a, "toFrame": b, **params})

    def render(frame):
        return decode(client.request("render", {"documentId": document_id, "frame": frame, "scale": 1}))

    red = {"r": 220, "g": 50, "b": 60, "a": 255}
    green = {"r": 40, "g": 180, "b": 100, "a": 255}
    blue = {"r": 60, "g": 100, "b": 220, "a": 255}
    edit("set_pixels", layerId=layer, frame=0, pixels=[{"x": x, "y": y, **color} for x, y, color in ((1, 1, red), (2, 2, blue), (3, 3, {**red, "a": 128}), (4, 4, green), (7, 7, red))])
    edit("add_frame", index=1, copyFrom=0, durationMs=150)
    edit("add_frame", index=2, durationMs=200)
    edit("set_pixels", layerId=layer, frame=1, pixels=[{"x": x, "y": y, **color} for x, y, color in ((1, 1, {**red, "a": 0}), (0, 6, green), (2, 2, green), (3, 3, {**red, "a": 64}))])
    edit("set_bitmap_selection", x=0, y=0, width=2, height=2, bits="1001")
    edit("draw_stroke", layerId=layer, frame=0, points=[{"x": 6, "y": 6}], color=green)
    edit("undo")  # Read-only inspection must preserve a live redo branch, too.
    edit("save", path="inspection-difference.ase")
    before = current()
    saved_bytes = (assets / "inspection-difference.ase").read_bytes()
    a, b = render(0), render(1)
    client.request("set_paused", {"paused": True})
    result = diff()
    assert result["schema"] == "libresprite-frame-diff-v1" and result["revision"] == before["revision"]
    stats = result["difference"]
    assert [stats[key] for key in ("addedPixels", "removedPixels", "modifiedPixels", "changedPixels", "unchangedPixels", "totalPixels")] == [1, 1, 2, 4, 60, 64], stats
    assert stats["bounds"] == {"x": 0, "y": 1, "width": 4, "height": 6}
    assert stats["before"]["visiblePixels"] == stats["after"]["visiblePixels"] == 5
    image = decode(result)
    legend = result["legend"]
    expected = bytearray()
    for i in range(0, len(a[2]), 4):
        from_pixel, to_pixel = a[2][i:i + 4], b[2][i:i + 4]
        if (not from_pixel[3] and not to_pixel[3]) or from_pixel == to_pixel:
            expected.extend((0, 0, 0, 0))
        else:
            expected.extend(legend["added" if not from_pixel[3] else "removed" if not to_pixel[3] else "modified"])
    assert image == (8, 8, bytes(expected))
    scaled = decode(diff(scale=3))
    assert scaled[:2] == (24, 24)
    for y in range(24):
        for x in range(24):
            i, j = (y * 24 + x) * 4, ((y // 3) * 8 + x // 3) * 4
            assert scaled[2][i:i + 4] == image[2][j:j + 4]
    reverse = diff(1, 0)["difference"]
    assert reverse["addedPixels"] == stats["removedPixels"] and reverse["removedPixels"] == stats["addedPixels"]
    assert reverse["before"] == stats["after"] and reverse["after"] == stats["before"]
    for index in (0, 2):
        identical = diff(index, index)
        assert identical["difference"]["changedPixels"] == 0 and identical["difference"]["bounds"] is None
        assert decode(identical)[2] == bytes(8 * 8 * 4)
    assert diff(2, 0)["difference"]["addedPixels"] == 5
    assert diff(0, 2)["difference"]["removedPixels"] == 5
    for params, code in (({"fromFrame": -1}, "INVALID_PARAMS"), ({"toFrame": 3}, "INVALID_PARAMS"), ({"scale": 0}, "INVALID_PARAMS"), ({"scale": 17}, "INVALID_PARAMS"), ({"sessionId": "wrong"}, "SESSION_MISMATCH")):
        client.request("render_frame_diff", {"documentId": document_id, "fromFrame": 0, "toFrame": 1, **params}, expected_error=code)
    assert current() == before and (assets / "inspection-difference.ase").read_bytes() == saved_bytes
    client.request("set_paused", {"paused": False})
    other = client.request("create", {"width": 1024, "height": 1024, "name": "Difference bounds"})
    other_id = other["documentId"]
    client.request("set_paused", {"paused": True})
    assert decode(diff()) == image  # Inactive reads never select the document.
    assert client.request("list_documents")["activeDocumentId"] == other_id
    client.request("render_frame_diff", {"documentId": other_id, "fromFrame": 0, "toFrame": 0, "scale": 2}, expected_error="LIMIT_EXCEEDED")
    assert current()["revision"] == before["revision"]
    client.request("set_paused", {"paused": False})
    saved = client.request("save", {"documentId": other_id, "expectedRevision": other["revision"], "path": "inspection-large.ase"})
    client.request("close_document", {"documentId": other_id, "expectedRevision": saved["revision"], "confirm": True})
    docs = client.request("list_documents")
    if docs["activeDocumentId"] != document_id:
        client.request("activate_document", {"documentId": document_id, "expectedRevision": before["revision"], "expectedActiveDocumentId": docs["activeDocumentId"]})
    assert current() == before
    client.request("close_document", {"documentId": document_id, "expectedRevision": before["revision"], "confirm": True})
    print("PASS: exact native frame differences/counts/bounds, alpha changes, scaling, blank/same/reversed frames, paused/inactive reads, untouched selection/save/redo and limits.")

    document = client.request("create", {"width": 2, "height": 1, "name": "Indexed differences", "colorMode": "indexed"})
    document_id, layer = document["documentId"], document["layers"][0]["layerId"]
    edit("set_palette", frame=0, size=2, entries=[{"index": 0, "color": {**red, "a": 0}}, {"index": 1, "color": red}])
    edit("set_indexed_pixels", layerId=layer, frame=0, pixels=[{"x": 0, "y": 0, "index": 1}])
    edit("add_frame", index=1, copyFrom=0)
    edit("set_palette", frame=1, entries=[{"index": 1, "color": green}])
    edit("save", path="inspection-indexed.ase")
    before = current()
    client.request("set_paused", {"paused": True})
    result = diff()
    assert result["difference"]["modifiedPixels"] == 1 and result["difference"]["changedPixels"] == 1
    assert decode(result)[2] == bytes(result["legend"]["modified"]) + bytes(4)
    for frame in (0, 1):
        isolated = client.request("render_layer", {"documentId": document_id, "layerId": layer, "frame": frame})
        assert decode(isolated) == render(frame)
    assert current() == before
    client.request("set_paused", {"paused": False})
    edit("close_document", confirm=True)

    # Native grayscale-alpha PNG decoding, independent frame copy, exact flip.
    path = assets / "inspection-gray.png"
    path.write_bytes(smoke.SIGNATURE + smoke.chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, 4, 0, 0, 0)) + smoke.chunk(b"IDAT", zlib.compress(bytes((0, 80, 128, 180, 255)))) + smoke.chunk(b"IEND", b""))
    document = client.request("open", {"path": path.name})
    document_id, layer = document["documentId"], document["layers"][0]["layerId"]
    assert document["colorMode"] == "grayscale"
    edit("add_frame", index=1, copyFrom=0)
    edit("transform_cel", layerId=layer, frame=1, operation="flip_horizontal")
    edit("save", path="inspection-gray.ase")
    before = current()
    client.request("set_paused", {"paused": True})
    result = diff()
    assert result["difference"]["modifiedPixels"] == result["difference"]["changedPixels"] == 2
    assert decode(result)[2] == bytes(result["legend"]["modified"]) * 2
    assert decode(client.request("render_layer", {"documentId": document_id, "layerId": layer, "frame": 0})) == render(0)
    assert current() == before
    client.request("set_paused", {"paused": False})
    edit("close_document", confirm=True)
    print("PASS: indexed palette-only visual differences and native grayscale/alpha comparison without conversion or document edits.")


def test_isolated_previews(client, assets, smoke):
    document = client.request("create", {"width": 8, "height": 8, "name": "Isolated preview tests"})
    document_id, base = document["documentId"], document["layers"][0]["layerId"]

    def current():
        return canonical_inspection(client.request("inspect", {"documentId": document_id}))

    def edit(method, **params):
        return client.request(method, {"documentId": document_id, "expectedRevision": current()["revision"], **params})

    def preview(layer, frame=0, **params):
        return client.request("render_layer", {"documentId": document_id, "layerId": layer, "frame": frame, **params})

    def decode(result):
        path = assets / "isolated-check.png"
        path.write_bytes(base64.b64decode(result["pngBase64"]))
        return smoke.read_png(path)

    blue = {"r": 60, "g": 100, "b": 220, "a": 255}
    red = {"r": 220, "g": 50, "b": 60, "a": 255}
    green = {"r": 40, "g": 180, "b": 100, "a": 255}
    edit("flood_fill", layerId=base, frame=0, x=0, y=0, color=blue)
    edit("add_frame", index=1, copyFrom=0)
    outer = edit("create_layer", name="Outer", type="group")["createdLayerId"]
    group = edit("create_layer", name="Inner", type="group", parentId=outer)["createdLayerId"]
    moving = edit("create_layer", name="Moving", parentId=group)["createdLayerId"]
    overlay = edit("create_layer", name="Overlay", parentId=group)["createdLayerId"]
    hidden = edit("create_layer", name="Hidden study", parentId=group)["createdLayerId"]
    for frame in (0, 1):
        edit("draw_stroke", layerId=moving, frame=frame, points=[{"x": 1 + frame, "y": 1}], color=red)
        edit("draw_stroke", layerId=overlay, frame=frame, points=[{"x": 1, "y": 1}], color=green)
        edit("draw_stroke", layerId=hidden, frame=frame, points=[{"x": 4, "y": 4}], color=green)
    edit("update_layer", layerId=overlay, opacity=128, blendMode="screen")
    edit("update_layer", layerId=hidden, visible=False)
    # Reference native composite with only this group visible, restored before
    # the read-only probes. This checks ordering, native blend and opacity.
    edit("update_layer", layerId=base, visible=False)
    references = [decode(client.request("render", {"documentId": document_id, "frame": frame, "scale": 1})) for frame in (0, 1)]
    edit("undo")
    edit("set_bitmap_selection", x=0, y=0, width=2, height=2, bits="1001")
    edit("save", path="inspection-isolated.ase")
    before = current()
    client.request("set_paused", {"paused": True})
    for frame in (0, 1):
        result = preview(group, frame)
        assert result["schema"] == "libresprite-layer-preview-v1" and result["layerId"] == group
        assert result["includeHidden"] is False and decode(result) == references[frame]
        assert decode(preview(outer, frame)) == references[frame]
    moving_image = decode(preview(moving))
    assert moving_image[2][(1 * 8 + 1) * 4:(1 * 8 + 1) * 4 + 4] == bytes(red.values())
    assert sum(moving_image[2][3::4]) == 255
    assert preview(hidden)["analysis"] == {"visiblePixels": 0, "bounds": None, "centroid": None}
    assert preview(hidden, includeHidden=True)["analysis"]["bounds"] == {"x": 4, "y": 4, "width": 1, "height": 1}
    assert preview(group, includeHidden=True)["analysis"]["visiblePixels"] == 2
    difference = client.request("render_frame_diff", {"documentId": document_id, "fromFrame": 0, "toFrame": 1, "layerId": moving})
    assert difference["layerId"] == moving and difference["difference"]["addedPixels"] == difference["difference"]["removedPixels"] == 1
    assert difference["difference"]["modifiedPixels"] == 0
    sheet = client.request("contact_sheet", {"documentId": document_id, "layerId": group, "frames": [1, 0], "columns": 2})
    assert sheet["layerId"] == group and sheet["includeHidden"] is False
    pixels = decode(sheet)[2]
    for y in range(8):
        row = references[1][2][y * 8 * 4:(y + 1) * 8 * 4] + references[0][2][y * 8 * 4:(y + 1) * 8 * 4]
        assert pixels[y * 16 * 4:(y + 1) * 16 * 4] == row
    hidden_sheet = client.request("contact_sheet", {"documentId": document_id, "layerId": hidden, "frames": [0], "includeHidden": True})
    assert decode(hidden_sheet) == decode(preview(hidden, includeHidden=True))
    for method, params in (("render_layer", {"layerId": group, "frame": 2}), ("render_layer", {"layerId": 2147483647, "frame": 0}), ("render_frame_diff", {"fromFrame": 0, "toFrame": 1, "includeHidden": True}), ("contact_sheet", {"includeHidden": True})):
        client.request(method, {"documentId": document_id, **params}, expected_error="LAYER_NOT_FOUND" if params.get("layerId") == 2147483647 else "INVALID_PARAMS")
    assert current() == before
    client.request("set_paused", {"paused": False})
    edit("update_layer", layerId=outer, visible=False, editable=False)
    edit("save", path="inspection-hidden-isolated.ase")
    before = current()
    saved_bytes = (assets / "inspection-hidden-isolated.ase").read_bytes()
    client.request("set_paused", {"paused": True})
    assert decode(preview(group))[2] == bytes(8 * 8 * 4)  # Ancestor visibility.
    assert decode(preview(moving))[2] == bytes(8 * 8 * 4)
    assert preview(group, includeHidden=True)["analysis"]["visiblePixels"] == 2
    assert decode(preview(moving, includeHidden=True)) == moving_image
    assert current() == before and (assets / "inspection-hidden-isolated.ase").read_bytes() == saved_bytes
    client.request("set_paused", {"paused": False})
    other = client.request("create", {"width": 1024, "height": 1024, "name": "Isolated preview limits"})
    client.request("set_paused", {"paused": True})
    assert decode(preview(moving, includeHidden=True)) == moving_image
    assert client.request("list_documents")["activeDocumentId"] == other["documentId"]
    client.request("render_layer", {"documentId": other["documentId"], "layerId": other["layers"][0]["layerId"], "frame": 0, "scale": 2}, expected_error="LIMIT_EXCEEDED")
    client.request("set_paused", {"paused": False})
    saved = client.request("save", {"documentId": other["documentId"], "expectedRevision": other["revision"], "path": "inspection-isolated-large.ase"})
    client.request("close_document", {"documentId": other["documentId"], "expectedRevision": saved["revision"], "confirm": True})
    docs = client.request("list_documents")
    if docs["activeDocumentId"] != document_id:
        client.request("activate_document", {"documentId": document_id, "expectedRevision": before["revision"], "expectedActiveDocumentId": docs["activeDocumentId"]})
    edit("close_document", confirm=True)
    print("PASS: isolated native layers/nested groups/blends/opacity, hidden/locked ancestors with renderer-only override, scoped sheets/differences, paused/inactive reads and limits.")

    # Native indexed background index zero is opaque, unlike transparent layers.
    def chunk(kind, payload):
        return struct.pack("<IH", len(payload) + 6, kind) + payload

    layer_chunk = struct.pack("<6H", 15, 0, 0, 2, 1, 0) + b"\xff\0\0\0" + struct.pack("<H", 4) + b"Base"
    palette_chunk = struct.pack("<III", 2, 0, 1) + bytes(8) + struct.pack("<H", 0) + bytes(blue.values()) + struct.pack("<H", 0) + bytes(red.values())
    cel_chunk = struct.pack("<HhhBH", 0, 0, 0, 255, 2) + bytes(7) + struct.pack("<HH", 2, 1) + zlib.compress(bytes((0, 1)))
    payload = chunk(0x2004, layer_chunk) + chunk(0x2019, palette_chunk) + chunk(0x2005, cel_chunk)
    frame = struct.pack("<IHHH", 16 + len(payload), 0xF1FA, 3, 100) + bytes(6) + payload
    header = bytearray(128)
    struct.pack_into("<IHHHHHIH", header, 0, 128 + len(frame), 0xA5E0, 1, 2, 1, 8, 1, 100)
    struct.pack_into("<H", header, 32, 2)
    header[34] = header[35] = 1
    (assets / "inspection-indexed-background.ase").write_bytes(header + frame)
    document = client.request("open", {"path": "inspection-indexed-background.ase"})
    document_id, base = document["documentId"], document["layers"][0]["layerId"]
    assert document["colorMode"] == "indexed" and document["layers"][0]["background"]
    before = current()
    client.request("set_paused", {"paused": True})
    full = decode(client.request("render", {"documentId": document_id, "frame": 0, "scale": 1}))
    assert decode(preview(base)) == full and full[2] == bytes(blue.values()) + bytes(red.values())
    assert current() == before
    client.request("set_paused", {"paused": False})
    edit("close_document", confirm=True)
    print("PASS: isolated indexed background retains the native opaque background/transparent-index semantics.")


def test_animation_diagnostics(client, assets, smoke):
    document = client.request("create", {"width": 4, "height": 4, "name": "Animation diagnostic tests"})
    document_id, base = document["documentId"], document["layers"][0]["layerId"]

    def current():
        return canonical_inspection(client.request("inspect", {"documentId": document_id}))

    def edit(method, **params):
        return client.request(method, {"documentId": document_id, "expectedRevision": current()["revision"], **params})

    def analyze(**params):
        return client.request("analyze_animation", {"documentId": document_id, **params})

    blue = {"r": 60, "g": 100, "b": 220, "a": 255}
    red = {"r": 220, "g": 50, "b": 60, "a": 255}
    edit("draw_stroke", layerId=base, frame=0, points=[{"x": 2, "y": 2}], color=blue)
    edit("set_frame_duration", frame=0, durationMs=91)
    for index, duration in ((1, 9), (2, 120), (3, 200)):
        edit("add_frame", index=index, copyFrom=0, durationMs=duration)
    group = edit("create_layer", name="Motion", type="group")["createdLayerId"]
    moving = edit("create_layer", name="Moving", parentId=group)["createdLayerId"]
    hidden = edit("create_layer", name="Hidden motion", parentId=group)["createdLayerId"]
    for frame, (x, y) in enumerate(((0, 0), (1, 0), (3, 3), (0, 0))):
        edit("draw_stroke", layerId=moving, frame=frame, points=[{"x": x, "y": y}], color=red)
        edit("draw_stroke", layerId=hidden, frame=frame, points=[{"x": 3, "y": 0}], color=blue)
    edit("update_layer", layerId=hidden, visible=False)
    tags = {direction: edit("create_tag", name=direction, to=2, direction=direction, **{"from": 0})["createdTagId"] for direction in ("forward", "reverse", "pingpong")}
    single = edit("create_tag", name="Single", to=1, **{"from": 1})["createdTagId"]
    edit("set_bitmap_selection", x=0, y=0, width=2, height=2, bits="1001")
    edit("draw_stroke", layerId=base, frame=0, points=[{"x": 0, "y": 3}], color=red)
    edit("undo")
    edit("save", path="inspection-diagnostics.ase")
    before = current()
    saved_bytes = (assets / "inspection-diagnostics.ase").read_bytes()
    client.request("set_paused", {"paused": True})
    result = analyze()
    assert result["schema"] == "libresprite-animation-analysis-v1" and result["revision"] == before["revision"]
    assert result["timing"]["totalDurationMs"] == 420 and result["timing"]["stepCount"] == 4
    assert [step["startMs"] for step in result["steps"]] == [0, 91, 100, 220]
    assert [step["endMs"] for step in result["steps"]] == [91, 100, 220, 420]
    assert [warning["code"] for warning in result["warnings"]] == ["GIF_DELAY_QUANTIZED", "GIF_DELAY_TOO_SHORT"]
    assert not result["gif"]["exportable"] and result["gif"]["encodedTotalDurationMs"] is None
    assert result["loopBoundary"]["fromFrame"] == 3 and result["loopBoundary"]["toFrame"] == 0
    assert result["loopBoundary"]["difference"]["changedPixels"] == 0
    assert result["transitionSummary"] == {"internalTransitions": 3, "identicalTransitions": 1, "meanInternalChangedPixels": 2, "maxInternalChangedPixels": 2, "loopChangedPixels": 0, "loopToInternalMeanRatio": 0}
    for transition in result["transitions"]:
        diff = client.request("render_frame_diff", {"documentId": document_id, "fromFrame": transition["fromFrame"], "toFrame": transition["toFrame"]})
        assert transition["difference"] == diff["difference"]
    for item in result["frames"]:
        assert item["visiblePixels"] == 2 and item["bounds"] is not None
    for direction, order, duration in (("forward", [0, 1, 2], 220), ("reverse", [2, 1, 0], 220), ("pingpong", [0, 1, 2, 1], 229)):
        tagged = analyze(tagId=tags[direction], layerId=group)
        assert [step["frame"] for step in tagged["steps"]] == order and tagged["timing"]["totalDurationMs"] == duration
        assert tagged["sequenceSource"] == "tag" and tagged["tagId"] == tags[direction]
        assert tagged["loopBoundary"]["fromFrame"] == order[-1] and tagged["loopBoundary"]["toFrame"] == order[0]
        for item in tagged["frames"]:
            rendered = client.request("render_layer", {"documentId": document_id, "layerId": group, "frame": item["frame"]})
            assert {key: item[key] for key in ("visiblePixels", "bounds", "centroid")} == rendered["analysis"]
        for transition in tagged["transitions"]:
            diff = client.request("render_frame_diff", {"documentId": document_id, "layerId": group, "fromFrame": transition["fromFrame"], "toFrame": transition["toFrame"]})
            assert transition["difference"] == diff["difference"]
    singleton = analyze(tagId=single)
    assert len(singleton["steps"]) == len(singleton["transitions"]) == 1
    assert singleton["loopBoundary"]["difference"]["changedPixels"] == 0
    assert singleton["transitionSummary"]["loopToInternalMeanRatio"] is None
    once = analyze(frames=[2, 0, 2], loop=False)
    assert [step["frame"] for step in once["steps"]] == [2, 0, 2]
    assert once["timing"]["totalDurationMs"] == 331 and once["loopBoundary"] is None
    assert once["gif"]["encodedTotalDurationMs"] == 330 and once["gif"]["totalShorteningMs"] == 1
    assert len(once["transitions"]) == 2 and not any(t["closing"] for t in once["transitions"])
    single_once = analyze(frames=[0], loop=False)
    assert single_once["transitions"] == [] and single_once["transitionSummary"]["meanInternalChangedPixels"] is None
    repeated = analyze(frames=[0, 0, 1, 1, 0])
    assert repeated["analyzedPixels"] == 16 * 6 and repeated["transitionSummary"]["identicalTransitions"] == 3
    assert all(item["visiblePixels"] == 0 for item in analyze(layerId=hidden)["frames"])
    assert all(item["visiblePixels"] == 1 for item in analyze(layerId=hidden, includeHidden=True)["frames"])
    for params, code in (({"frames": []}, "INVALID_PARAMS"), ({"frames": [0], "tagId": tags["forward"]}, "INVALID_PARAMS"), ({"frames": [4]}, "INVALID_PARAMS"), ({"frames": [0] * 257}, "INVALID_PARAMS"), ({"includeHidden": True}, "INVALID_PARAMS"), ({"loop": "yes"}, "INVALID_PARAMS"), ({"tagId": 2147483647}, "TAG_NOT_FOUND"), ({"layerId": 2147483647}, "LAYER_NOT_FOUND"), ({"sessionId": "wrong"}, "SESSION_MISMATCH")):
        client.request("analyze_animation", {"documentId": document_id, **params}, expected_error=code)
    assert current() == before and (assets / "inspection-diagnostics.ase").read_bytes() == saved_bytes
    client.request("set_paused", {"paused": False})
    other = client.request("create", {"width": 1024, "height": 1024, "name": "Analysis work limits"})
    other_id = other["documentId"]
    for index in range(1, 5):
        state = client.request("inspect", {"documentId": other_id})
        client.request("add_frame", {"documentId": other_id, "expectedRevision": state["revision"], "index": index})
    other_before = canonical_inspection(client.request("inspect", {"documentId": other_id}))
    client.request("set_paused", {"paused": True})
    assert analyze()["timing"] == result["timing"]  # Inactive reads.
    assert client.request("list_documents")["activeDocumentId"] == other_id
    client.request("analyze_animation", {"documentId": other_id}, expected_error="LIMIT_EXCEEDED")
    bounded = client.request("analyze_animation", {"documentId": other_id, "frames": [0] * 256})
    assert bounded["analyzedPixels"] == 2 * 1024 * 1024 and len(bounded["steps"]) == 256
    assert len(bounded["frames"]) == 1 and bounded["frames"][0]["bounds"] is None
    boundary = client.request("analyze_animation", {"documentId": other_id, "frames": [0, 1, 2, 3]})
    assert boundary["analyzedPixels"] == 8 * 1024 * 1024
    assert canonical_inspection(client.request("inspect", {"documentId": other_id})) == other_before
    client.request("set_paused", {"paused": False})
    saved = client.request("save", {"documentId": other_id, "expectedRevision": other_before["revision"], "path": "inspection-analysis-large.ase"})
    client.request("close_document", {"documentId": other_id, "expectedRevision": saved["revision"], "confirm": True})
    docs = client.request("list_documents")
    if docs["activeDocumentId"] != document_id:
        client.request("activate_document", {"documentId": document_id, "expectedRevision": before["revision"], "expectedActiveDocumentId": docs["activeDocumentId"]})
    assert current() == before
    edit("close_document", confirm=True)
    print("PASS: exact cumulative timing/GIF diagnostics, forward/reverse/pingpong/tag/explicit/repeated/once/single-frame loop analysis, scoped metrics/diffs, cache/work ceilings and read-only state preservation.")

    document = client.request("create", {"width": 1, "height": 1, "name": "Maximum tag diagnostics"})
    document_id = document["documentId"]
    for count in (1, 2, 4, 8, 16, 32, 64, 128):
        edit("duplicate_frames", frames=list(range(count)), index=count)
    tag = edit("create_tag", name="Full pingpong", to=255, direction="pingpong", **{"from": 0})["createdTagId"]
    edit("save", path="inspection-analysis-max-tag.ase")
    before = current()
    client.request("set_paused", {"paused": True})
    result = analyze(tagId=tag)
    assert len(result["steps"]) == len(result["transitions"]) == 510
    assert len(result["frames"]) == 256 and result["timing"]["totalDurationMs"] == 51000
    assert [step["frame"] for step in result["steps"]] == list(range(256)) + list(range(254, 0, -1))
    assert result["loopBoundary"]["fromFrame"] == 1 and result["loopBoundary"]["toFrame"] == 0
    assert current() == before
    client.request("set_paused", {"paused": False})
    edit("close_document", confirm=True)
    print("PASS: maximum 256-frame native pingpong tag expands to exactly 510 endpoint-unduplicated playback steps.")

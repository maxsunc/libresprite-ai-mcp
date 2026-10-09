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
    assert current() == before
    client.request("set_paused", {"paused": False})
    edit("close_document", confirm=True)
    print("PASS: indexed palette-only visual differences and native grayscale/alpha comparison without conversion or document edits.")

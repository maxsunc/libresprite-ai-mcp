"""Exact pixel regions in NEW, disposable native GUI editors. GPL-2.0-only."""
import base64
import struct
import zlib
from bridge_animation_cases import canonical_inspection, fixture, raw_frames


class RegionCase:
    def __init__(self, client, assets, smoke):
        self.client, self.assets, self.smoke = client, assets, smoke
        self.original_ids = {d["documentId"] for d in client.request("list_documents")["documents"]}

    def use(self, document):
        self.document_id = document["documentId"]
        self.layer = document["layers"][0]["layerId"]
        return document

    def current(self):
        return canonical_inspection(self.client.request("inspect", {"documentId": self.document_id}))

    def edit(self, method, **params):
        return self.client.request(method, {"documentId": self.document_id, "expectedRevision": self.current()["revision"], **params})

    def read(self, **params):
        return self.client.request("read_pixels", {"documentId": self.document_id, "layerId": self.layer, "frame": 0,
            "x": 0, "y": 0, "width": 16, "height": 16, "encoding": "values", **params})

    def decode(self, result):
        path = self.assets / "region-check.png"
        path.write_bytes(base64.b64decode(result["pngBase64"]))
        return self.smoke.read_png(path)

    def close(self):
        ours = [d["documentId"] for d in self.client.request("list_documents")["documents"] if d["documentId"] not in self.original_ids]
        self.client.request("set_paused", {"paused": False})
        for identity in reversed(ours):
            self.document_id = identity
            state = self.current()
            active = self.client.request("list_documents")["activeDocumentId"]
            if active != identity:
                self.client.request("activate_document", {"documentId": identity, "expectedRevision": state["revision"], "expectedActiveDocumentId": active})
            saved = self.edit("save", path=f"region-closed-{identity}.ase")
            self.client.request("close_document", {"documentId": identity, "expectedRevision": saved["revision"], "confirm": True})


def replace_payload(path, value):
    """Insert otherwise-invisible RGBA bytes in the first cel's transparent sample."""
    data = path.read_bytes(); offset = 128; frames = []
    for frame in range(struct.unpack_from("<H", data, 6)[0]):
        size, _, count, _ = struct.unpack_from("<IHHH", data, offset)
        cursor = offset + 16; chunks = []
        for _ in range(count):
            length, kind = struct.unpack_from("<IH", data, cursor)
            payload = data[cursor + 6:cursor + length]
            if frame == 0 and kind == 0x2005:
                pixels = bytearray(zlib.decompress(payload[20:])); pixels[8:12] = value
                payload = payload[:20] + zlib.compress(pixels)
            chunks.append(struct.pack("<IH", len(payload) + 6, kind) + payload); cursor += length
        contents = b"".join(chunks); header = bytearray(data[offset:offset + 16])
        struct.pack_into("<I", header, 0, len(contents) + 16)
        frames.append(header + contents); offset += size
    header = bytearray(data[:128]); struct.pack_into("<I", header, 0, 128 + sum(map(len, frames)))
    path.write_bytes(header + b"".join(frames))


def test_pixel_reads(client, assets, smoke):
    case = RegionCase(client, assets, smoke)
    for mode, linked, background in ((32, False, False), (8, False, False), (16, False, False), (32, True, False), (8, False, True)):
        name = f"raw-read-{mode}-{linked}-{background}.ase"
        fixture(assets / name, mode=mode, linked=linked, background=background, palettes=mode == 8)
        if mode == 32 and not linked:
            replace_payload(assets / name, bytes((11, 22, 33, 0)))
        document = case.use(client.request("open", {"path": name}))
        original = raw_frames(assets / name)
        empty = case.edit("create_layer", name="Absent cel")["createdLayerId"]
        if not background:
            case.edit("update_layer", layerId=case.layer, opacity=111, visible=False, editable=False)
        case.edit("set_bitmap_selection", x=8, y=8, width=2, height=2, bits="1001")
        case.edit("draw_stroke", layerId=empty, frame=0, points=[{"x": 15, "y": 15}], color={"r": 9, "g": 8, "b": 7, "a": 255}) if mode == 32 else case.edit("update_layer", layerId=empty, name="Redo sentinel")
        case.edit("undo")
        case.edit("save", path=f"raw-saved-{mode}-{linked}-{background}.ase")
        before = case.current(); assert before["canRedo"]
        saved_bytes = (assets / f"raw-saved-{mode}-{linked}-{background}.ase").read_bytes()
        client.request("set_paused", {"paused": True})
        for frame in range(3):
            payload = next(v for k, v in original[frame][1] if k == 0x2005)
            stride = mode // 8
            values = [int.from_bytes(payload[20 + i * stride:20 + (i + 1) * stride], "little") for i in range(6)]
            expected = [values[:3] + [0], values[3:] + [0], [0] * 4]
            result = case.read(frame=frame, x=-1, y=2, width=4, height=3)
            assert result["rows"] == expected, (mode, frame, result["rows"], expected)
            assert result["schema"] == "libresprite-pixel-read-v1" and result["sampleCount"] == 12
            assert result["cel"]["opacity"] == 192 and result["cel"]["x"] == -1
            if mode == 8:
                effective = next(p for p in reversed(before["palettes"]) if p["frame"] <= frame)
                assert result["paletteRgbaPacked"] == effective["rgbaPacked"]
            runs = case.read(frame=frame, x=-1, y=2, width=4, height=3, encoding="runs")
            reconstructed = [[value for length, value in row for _ in range(length)] for row in runs["rows"]]
            assert reconstructed == expected
        missing = case.read(layerId=empty, width=2, height=2)
        assert missing["cel"] is None and missing["rows"] == [[0, 0], [0, 0]]
        assert case.read(x=32767, y=-32768, width=1, height=1)["rows"] == [[0]]
        for params, code in (({"width": 1024, "height": 17}, "LIMIT_EXCEEDED"), ({"width": 0}, "INVALID_PARAMS"), ({"frame": 3}, "INVALID_PARAMS"), ({"layerId": 2147483647}, "LAYER_NOT_FOUND"), ({"encoding": "bad"}, "INVALID_PARAMS"), ({"sessionId": "bad"}, "SESSION_MISMATCH")):
            client.request("read_pixels", {"documentId": case.document_id, "layerId": case.layer, "frame": 0, "x": 0, "y": 0, "width": 1, "height": 1, **params}, expected_error=code)
        assert case.current() == before and saved_bytes == (assets / f"raw-saved-{mode}-{linked}-{background}.ase").read_bytes()
        client.request("set_paused", {"paused": False})
        other = client.request("create", {"width": 1, "height": 1, "name": "Inactive raw read"})
        client.request("set_paused", {"paused": True})
        assert case.read(x=-1, y=2, width=3, height=2)["revision"] == before["revision"]
        assert client.request("list_documents")["activeDocumentId"] == other["documentId"]
        client.request("set_paused", {"paused": False})
    case.use(client.request("create", {"width": 1, "height": 1, "name": "Nonzero transparent", "colorMode": "indexed"}))
    group = case.edit("create_layer", name="Group", type="group")["createdLayerId"]
    client.request("read_pixels", {"documentId": case.document_id, "layerId": group, "frame": 0, "x": 0, "y": 0, "width": 1, "height": 1}, expected_error="UNSUPPORTED_LAYER")
    name = "raw-read-transparent7.ase"; fixture(assets / name, mode=8)
    data = bytearray((assets / name).read_bytes()); data[28] = 7; (assets / name).write_bytes(data)
    case.use(client.request("open", {"path": name}))
    assert case.read(x=-2, y=2, width=4, height=1)["rows"] == [[7, 1, 2, 0]]
    case.close()
    print("PASS: exact raw RGBA/indexed/grayscale values and runs, invisible payloads/off-canvas/padding, palettes/opacity, hidden/locked/linked/background/missing cels, paused/inactive reads and unchanged save/redo/mask/focus with bounds/validation guards.")


def test_pixel_masks(client, assets, smoke):
    case = RegionCase(client, assets, smoke)
    doc = case.use(client.request("create", {"width": 8, "height": 8, "name": "Mask extraction"}))
    red = {"r": 200, "g": 50, "b": 60, "a": 255}
    case.edit("set_pixels", layerId=case.layer, frame=0, pixels=[{"x": x, "y": y, **color} for x, y, color in ((1, 1, red), (2, 2, {**red, "a": 128}), (3, 3, red), (6, 6, red))])
    case.edit("add_frame", index=1)
    case.edit("set_bitmap_selection", x=0, y=0, width=2, height=2, bits="1001")
    case.edit("draw_stroke", layerId=case.layer, frame=0, points=[{"x": 0, "y": 7}], color=red)
    case.edit("undo")
    case.edit("update_layer", layerId=case.layer, visible=False, editable=False)
    case.edit("save", path="mask-before.ase")
    # Put a separate edit into redo after the saved baseline.
    case.edit("create_layer", name="Redo"); case.edit("undo")
    before = case.current(); stored = (assets / "mask-before.ase").read_bytes()

    def extract(error=None, **params):
        return client.request("extract_mask", {"documentId": case.document_id, "layerId": case.layer, "frame": 0,
            "x": 0, "y": 0, "width": 8, "height": 8, **params}, expected_error=error)

    client.request("set_paused", {"paused": True})
    result = extract()
    expected = "".join("1" if (i % 8, i // 8) in ((1, 1), (2, 2), (3, 3), (6, 6)) else "0" for i in range(64))
    assert result["mask"]["bits"] == expected and result["selectedPixels"] == 4
    assert result["bounds"] == {"x": 1, "y": 1, "width": 6, "height": 6}
    assert case.decode(result) == (8, 8, b"".join(bytes((255, 255, 255, 255)) if b == "1" else bytes(4) for b in expected))
    assert extract(minAlpha=129)["selectedPixels"] == 3
    assert extract(criterion="value", value=int.from_bytes(bytes((200, 50, 60, 128)), "little"))["selectedPixels"] == 1
    four = extract(seed={"x": 1, "y": 1}, preview=False)
    assert four["selectedPixels"] == 1 and "pngBase64" not in four
    eight = extract(seed={"x": 1, "y": 1}, connectivity=8)
    assert eight["selectedPixels"] == 3 and eight["mask"]["bits"][6 * 8 + 6] == "0"
    assert extract(seed={"x": 0, "y": 0})["bounds"] is None
    assert extract(frame=1)["mask"]["bits"] == "0" * 64
    for params, code in (({"x": 7, "width": 2}, "OUTSIDE_CANVAS"), ({"seed": {"x": 7, "y": 7}, "width": 4}, "INVALID_PARAMS"), ({"connectivity": 8}, "INVALID_PARAMS"), ({"criterion": "value"}, "INVALID_PARAMS"), ({"criterion": "value", "value": 0, "minAlpha": 1}, "INVALID_PARAMS"), ({"value": 0}, "INVALID_PARAMS"), ({"criterion": "value", "value": 4294967296}, "INVALID_PARAMS"), ({"preview": "yes"}, "INVALID_PARAMS"), ({"sessionId": "bad"}, "SESSION_MISMATCH")):
        extract(error=code, **params)
    assert case.current() == before and (assets / "mask-before.ase").read_bytes() == stored
    client.request("set_paused", {"paused": False})
    other = client.request("create", {"width": 1024, "height": 1024, "name": "Mask limits"})
    client.request("set_paused", {"paused": True})
    assert extract()["mask"] == result["mask"] and case.current()["revision"] == before["revision"]
    assert client.request("list_documents")["activeDocumentId"] == other["documentId"]
    client.request("extract_mask", {"documentId": other["documentId"], "layerId": other["layers"][0]["layerId"], "frame": 0, "x": 0, "y": 0, "width": 1024, "height": 257}, expected_error="LIMIT_EXCEEDED")
    client.request("set_paused", {"paused": False})
    for mode, background in ((8, False), (8, True), (16, False), (32, False)):
        name = f"mask-raw-{mode}-{background}.ase"
        fixture(assets / name, mode=mode, background=background, linked=True)
        if mode == 32:
            # This fixture is linked, so only its owner needs the payload replacement.
            replace_payload(assets / name, bytes((11, 22, 33, 0)))
        case.use(client.request("open", {"path": name}))
        client.request("set_paused", {"paused": True})
        result = extract(x=0, y=2, width=2, height=2, frame=1)
        assert result["mask"]["bits"] == ("1111" if background else "1011")
        if mode == 8:
            assert extract(criterion="value", value=2)["selectedPixels"] == 2  # Off-canvas third index isn't counted.
            extract(error="INVALID_PARAMS", minAlpha=2)
            extract(error="INVALID_PARAMS", criterion="value", value=256)
        if mode == 16:
            assert extract(x=0, y=2, width=2, height=2, minAlpha=129)["mask"]["bits"] == "0011"
        if mode == 32:
            assert extract(criterion="value", value=int.from_bytes(bytes((11, 22, 33, 0)), "little"))["selectedPixels"] == 1
        client.request("set_paused", {"paused": False})
    case.close()
    print("PASS: raw alpha/value bitmap masks and exact PNGs/counts/bounds, seeded 4/8 components/empty seeds, missing/hidden/locked/linked/background/indexed/grayscale cels, JSON-only previews, paused/inactive reads and selection/save/redo/focus/resource preservation.")

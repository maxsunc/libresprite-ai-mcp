"""Read-only browsing/animation previews and atomic export GUI regressions. GPLv2."""
import base64
import struct
import zlib


def test_assets_previews_exports(client, assets, smoke):
    directory = assets / "preview-assets"
    directory.mkdir()
    (directory / "child").mkdir()
    document = client.request("create", {"width": 8, "height": 8, "name": "Preview and export tests"})
    document_id = document["documentId"]
    base = document["layers"][0]["layerId"]
    green = {"r": 40, "g": 180, "b": 100, "a": 255}
    blue = {"r": 60, "g": 100, "b": 220, "a": 255}

    def current():
        return client.request("inspect", {"documentId": document_id})

    def mutate(method, params):
        return client.request(method, {"documentId": document_id, "expectedRevision": current()["revision"], **params})

    def pixels(result):
        path = assets / "preview-check.png"
        path.write_bytes(base64.b64decode(result["pngBase64"]))
        return smoke.read_png(path)

    def render(frame, scale=1):
        return client.request("render", {"documentId": document_id, "frame": frame, "scale": scale})

    def at(image, x, y):
        width, _, data = image
        start = (y * width + x) * 4
        return tuple(data[start:start + 4])

    def stroke(layer, frame, x, y, color):
        return mutate("draw_stroke", {"layerId": layer, "frame": frame, "points": [{"x": x, "y": y}], "color": color})

    for index in (1, 2):
        mutate("add_frame", {"index": index, "durationMs": [100, 150, 200][index]})
    group = mutate("create_layer", {"name": "Motion", "type": "group"})["createdLayerId"]
    moving = mutate("create_layer", {"name": "Moving", "parentId": group})["createdLayerId"]
    for frame in range(3):
        stroke(base, frame, 7, 7 - frame, blue)
        stroke(moving, frame, 1 + 2 * frame, 1, green)
    mutate("save", {"path": "preview-assets/a.ase"})
    before = current()
    frame_images = [pixels(render(i)) for i in range(3)]

    client.request("set_paused", {"paused": True})
    sheet = client.request("contact_sheet", {"documentId": document_id, "frames": [2, 0, 1], "columns": 2, "scale": 2, "padding": 1})
    image = pixels(sheet)
    assert image[:2] == (35, 35)
    manifest = sheet["sheet"]
    assert manifest["schema"] == "libresprite-sheet-v1"
    assert [item["frame"] for item in manifest["frames"]] == [2, 0, 1]
    assert [item["durationMs"] for item in manifest["frames"]] == [200, 100, 150]
    for cell in manifest["frames"]:
        source = frame_images[cell["frame"]]
        for dy in range(16):
            for dx in range(16):
                assert at(image, cell["x"] + dx, cell["y"] + dy) == at(source, dx // 2, dy // 2)
    for y in range(35):
        for x in range(35):
            inside = any(cell["x"] <= x < cell["x"] + 16 and cell["y"] <= y < cell["y"] + 16 for cell in manifest["frames"])
            if not inside:
                assert at(image, x, y) == (0, 0, 0, 0)
    defaults = client.request("contact_sheet", {"documentId": document_id})
    assert defaults["sheet"]["columns"] == 2 and defaults["sheet"]["rows"] == 2
    assert [cell["frame"] for cell in defaults["sheet"]["frames"]] == [0, 1, 2]
    for params in ({"frames": []}, {"frames": [0, 0]}, {"frames": [3]}, {"frames": [0], "columns": 2}, {"scale": 17}, {"padding": -1}):
        client.request("contact_sheet", {"documentId": document_id, **params}, expected_error="INVALID_PARAMS")
    assert current() == before
    print("PASS: read-only contact sheets, reordered/subset frames, exact scaled tiles, timing, transparent padding, validation.")

    def onion(frame=1, **params):
        return client.request("render_onion_skin", {"documentId": document_id, "frame": frame, **params})

    tinted = pixels(onion())
    assert at(tinted, 1, 1)[0] > at(tinted, 1, 1)[1] and at(tinted, 1, 1)[3] == 128
    assert at(tinted, 5, 1)[2] > at(tinted, 5, 1)[0] and at(tinted, 5, 1)[3] == 128
    assert at(tinted, 3, 1) == tuple(green.values())
    filtered = pixels(onion(layerId=group))
    assert at(filtered, 7, 7) == (0, 0, 0, 0) and at(filtered, 7, 5) == (0, 0, 0, 0)
    assert at(filtered, 7, 6) == tuple(blue.values())  # Current frame remains the full composite.
    assert pixels(onion(layerId=moving)) == filtered
    merged = pixels(onion(mode="merge", layerId=group))
    assert at(merged, 1, 1) == (40, 180, 100, 128) and at(merged, 5, 1) == (40, 180, 100, 128)
    stepped = pixels(onion(0, previous=0, next=2, mode="merge", opacity=128, opacityStep=32, layerId=group))
    assert at(stepped, 3, 1)[3] == 128 and at(stepped, 5, 1)[3] == 96
    assert pixels(onion(previous=0, next=0)) == frame_images[1]
    assert pixels(onion(opacity=0)) == frame_images[1]
    assert pixels(onion(0, previous=8, next=0)) == frame_images[0]
    assert pixels(onion(2, previous=0, next=8)) == frame_images[2]
    for params, code in (({"mode": "bad"}, "INVALID_PARAMS"), ({"position": "bad"}, "INVALID_PARAMS"), ({"previous": 9}, "INVALID_PARAMS"), ({"frame": 3}, "INVALID_PARAMS"), ({"layerId": 2147483647}, "LAYER_NOT_FOUND")):
        client.request("render_onion_skin", {"documentId": document_id, "frame": 1, **params}, expected_error=code)
    assert current() == before
    client.request("set_paused", {"paused": False})
    backdrop = mutate("create_layer", {"name": "Opaque backdrop", "afterLayerId": None})["createdLayerId"]
    mutate("flood_fill", {"layerId": backdrop, "frame": 1, "x": 0, "y": 0, "color": blue})
    assert pixels(onion(position="behind")) == pixels(render(1))
    assert pixels(onion(position="front")) != pixels(render(1))
    mutate("undo", {})
    mutate("undo", {})
    before = current()
    assert pixels(render(1)) == frame_images[1]
    print("PASS: native red/blue and merge onion skins, layer/group filtering, opacity falloff, end clipping, front/behind, no state changes.")

    (directory / "b.png").write_bytes(base64.b64decode(render(1)["pngBase64"]))
    (directory / "ignore.txt").write_text("not an asset")
    (directory / "linked.png").symlink_to(directory / "b.png")
    (directory / "escape").symlink_to(assets.parent, target_is_directory=True)
    (directory / "escape.png").symlink_to(assets.parent / "editor.log")
    listed = client.request("list_assets", {"path": "preview-assets", "limit": 1})
    assert listed["total"] == 3 and listed["nextOffset"] == 1
    assert listed["entries"][0]["path"] == "preview-assets/child" and listed["entries"][0]["type"] == "directory"
    second = client.request("list_assets", {"path": "preview-assets", "offset": 1, "limit": 1})
    third = client.request("list_assets", {"path": "preview-assets", "offset": 2, "limit": 1})
    assert second["entries"][0]["name"] == "a.ase" and third["entries"][0]["name"] == "b.png"
    assert third["nextOffset"] is None and third["entries"][0]["bytes"] == (directory / "b.png").stat().st_size
    assert client.request("list_assets", {"path": "preview-assets", "offset": 3})["entries"] == []
    assert "preview-assets" in [entry["name"] for entry in client.request("list_assets")["entries"]]
    for params, code in (({"path": ".."}, "PATH_OUTSIDE_ROOT"), ({"path": "preview-assets/escape"}, "PATH_OUTSIDE_ROOT"), ({"path": "preview-assets/a.ase"}, "INVALID_PATH"), ({"path": "preview-assets", "offset": 4}, "INVALID_PARAMS"), ({"limit": 101}, "INVALID_PARAMS")):
        client.request("list_assets", params, expected_error=code)
    client.request("set_paused", {"paused": True})
    documents = client.request("list_documents")
    for path, frame in (("preview-assets/a.ase", 1), ("preview-assets/b.png", 0), ("preview-assets/linked.png", 0)):
        preview = client.request("preview_asset", {"path": path, "frame": frame})
        assert pixels(preview) == frame_images[1]
        assert "documentId" not in preview and "revision" not in preview
        assert preview["outputWidth"] == 8 and preview["outputHeight"] == 8
    assert client.request("list_documents") == documents and current() == before
    for path, code in (("preview-assets/escape.png", "PATH_OUTSIDE_ROOT"), ("preview-assets/ignore.txt", "UNSUPPORTED_FORMAT"), ("preview-assets/missing.png", "IO_ERROR")):
        client.request("preview_asset", {"path": path}, expected_error=code)
    (directory / "bad.png").write_bytes(b"not PNG")
    client.request("preview_asset", {"path": "preview-assets/bad.png"}, expected_error="OPEN_FAILED")
    client.request("preview_asset", {"path": "preview-assets/a.ase", "frame": 3}, expected_error="INVALID_PARAMS")
    client.request("preview_asset", {"path": "preview-assets/a.ase", "scale": 0}, expected_error="INVALID_PARAMS")
    # A valid, highly compressible PNG exceeds the canvas limit before postLoad.
    header = struct.pack(">IIBBBBB", 1025, 1, 8, 6, 0, 0, 0)
    (directory / "wide.png").write_bytes(smoke.SIGNATURE + smoke.chunk(b"IHDR", header) + smoke.chunk(b"IDAT", zlib.compress(bytes(1 + 1025 * 4))) + smoke.chunk(b"IEND", b""))
    client.request("preview_asset", {"path": "preview-assets/wide.png"}, expected_error="LIMIT_EXCEEDED")
    with (directory / "big.png").open("wb") as large_input:
        large_input.truncate(32 * 1024 * 1024 + 1)
    client.request("preview_asset", {"path": "preview-assets/big.png"}, expected_error="LIMIT_EXCEEDED")
    crowded = directory / "crowded"
    crowded.mkdir()
    for index in range(4096):
        (crowded / str(index)).write_bytes(b"")
    assert client.request("list_assets", {"path": "preview-assets/crowded"})["entries"] == []
    (crowded / "one-too-many").write_bytes(b"")
    client.request("list_assets", {"path": "preview-assets/crowded"}, expected_error="LIMIT_EXCEEDED")
    after_documents, after = client.request("list_documents"), current()
    assert after_documents == documents, ("Documents changed during detached preview/browsing", documents, after_documents)
    assert after == before, ("Sprite changed during detached preview/browsing", before, after)
    print("PASS: bounded root asset browsing/pagination, symlink filtering/escape guards, detached native/PNG thumbnails while paused.")

    target = {"documentId": document_id, "expectedRevision": before["revision"]}
    for method, params in (("export_png", {"frame": 1, "path": "preview-assets/export.png"}), ("export_sprite_sheet", {"path": "preview-assets/sheet.png"})):
        client.request(method, {**target, **params}, expected_error="PAUSED")
        assert not (assets / params["path"]).exists()
    client.request("set_paused", {"paused": False})
    exported = client.request("export_png", {**target, "frame": 1, "scale": 2, "path": "preview-assets/export.png"})
    assert smoke.read_png(directory / "export.png") == pixels(render(1, 2))
    assert exported["bytes"] == (directory / "export.png").stat().st_size and "pngBase64" not in exported
    layout = {"frames": [2, 0, 1], "columns": 2, "scale": 2, "padding": 1}
    exported_sheet = client.request("export_sprite_sheet", {**target, **layout, "path": "preview-assets/sheet.png"})
    assert exported_sheet["sheet"] == manifest and smoke.read_png(directory / "sheet.png") == image
    assert not (directory / "sheet.json").exists()
    (directory / "not-file.png").mkdir()
    for method, params in (("export_png", {"frame": 1, "path": "preview-assets/export.png"}), ("export_sprite_sheet", {"path": "preview-assets/sheet.png"})):
        saved = (assets / params["path"]).read_bytes()
        client.request(method, {**target, **params}, expected_error="FILE_EXISTS")
        assert (assets / params["path"]).read_bytes() == saved
        client.request(method, {**target, **params, "overwrite": True})
        client.request(method, {**target, **params, "expectedRevision": before["revision"] - 1}, expected_error="STALE_REVISION")
        client.request(method, {**target, **params, "sessionId": "other-process"}, expected_error="SESSION_MISMATCH")
        for path, code in (("../export.png", "PATH_OUTSIDE_ROOT"), ("preview-assets/escape/export.png", "PATH_OUTSIDE_ROOT"), ("preview-assets/linked.png", "INVALID_PATH"), ("preview-assets/not-file.png", "INVALID_PATH"), ("preview-assets/wrong.ase", "INVALID_PATH")):
            client.request(method, {**target, **params, "path": path, "overwrite": True}, expected_error=code)
    client.request("export_png", {**target, "frame": 3, "path": "preview-assets/invalid.png"}, expected_error="INVALID_PARAMS")
    client.request("export_sprite_sheet", {**target, "frames": [0, 0], "path": "preview-assets/invalid.png"}, expected_error="INVALID_PARAMS")
    assert not (directory / "invalid.png").exists() and not list(directory.glob(".libresprite-export-*"))
    replay_params = {**target, "frame": 1, "path": "preview-assets/replay.png"}
    published = client.request("export_png", replay_params, request_id="test-png-export-once")
    (directory / "replay.png").write_bytes(b"manual change in a TEST-OWNED file")
    assert client.request("export_png", replay_params, request_id="test-png-export-once") == published
    assert (directory / "replay.png").read_bytes() == b"manual change in a TEST-OWNED file"
    assert current() == before  # Filename, saved state, revisions, selection and history all preserved.
    other = client.request("create", {"width": 1024, "height": 1024, "name": "Preview bounds"})
    for method in ("export_png", "export_sprite_sheet"):
        params = {**target, "frame": 1, "path": "preview-assets/inactive.png"}
        client.request(method, params, expected_error="INACTIVE_DOCUMENT")
    large_id = other["documentId"]
    for method, params in (("contact_sheet", {"scale": 2}), ("render_onion_skin", {"frame": 0, "scale": 2}), ("export_png", {"frame": 0, "scale": 2, "path": "preview-assets/large.png", "expectedRevision": other["revision"]}), ("export_sprite_sheet", {"padding": 1, "path": "preview-assets/large.png", "expectedRevision": other["revision"]})):
        client.request(method, {"documentId": large_id, **params}, expected_error="LIMIT_EXCEEDED")
    client.request("set_paused", {"paused": True})
    assert pixels(client.request("contact_sheet", {"documentId": document_id, "frames": [1]})) == frame_images[1]
    assert client.request("list_documents")["activeDocumentId"] == large_id
    assert not (directory / "large.png").exists() and not (directory / "inactive.png").exists()
    assert current()["revision"] == before["revision"]
    client.request("set_paused", {"paused": False})
    # The workflow suite leaves a two-frame native fixture with a Walk tag.
    # Subset/reordered sheet tags retain source indices, not tile positions.
    tagged = client.request("open", {"path": "tagged.ase"})
    tagged_id = tagged["documentId"]
    tagged_sheet = client.request("contact_sheet", {"documentId": tagged_id, "frames": [1, 0], "columns": 2})
    assert [cell["frame"] for cell in tagged_sheet["sheet"]["frames"]] == [1, 0]
    assert tagged_sheet["sheet"]["tags"] == [{"name": "Walk", "from": 0, "to": 1, "direction": 0}]
    no_wrap = client.request("render_onion_skin", {"documentId": tagged_id, "frame": 0, "previous": 1, "next": 0, "position": "front"})
    regular = client.request("render", {"documentId": tagged_id, "frame": 0, "scale": 1})
    assert pixels(no_wrap) == pixels(regular)
    assert client.request("inspect", {"documentId": tagged_id}) == tagged
    print("PASS: atomic PNG/sheet exports, exact layout metadata, no overwrite/retry/state changes, session/revision/pause/active-document/path/pixel limits.")

"""Prepared corrections in new disposable GUI documents. GPL-2.0-only."""
import base64
from bridge_animation_cases import canonical_inspection, fixture


def test_cooperative_edits(client, assets, smoke):
    document = client.request("create", {"width": 16, "height": 16, "name": "Cooperative correction tests"})
    identity = document["documentId"]; layer = document["layers"][0]["layerId"]
    owned = [identity]
    red = {"r": 230, "g": 60, "b": 70, "a": 255}
    blue = {"r": 50, "g": 80, "b": 220, "a": 255}

    def state():
        return canonical_inspection(client.request("inspect", {"documentId": identity}))

    def edit(method, **params):
        return client.request(method, {"documentId": identity, "expectedRevision": state()["revision"], **params})

    def read(x=0, y=0, width=16, height=16, **params):
        return client.request("read_pixels", {"documentId": identity, "layerId": layer, "frame": 0, "x": x, "y": y, "width": width, "height": height, "encoding": "values", **params})["rows"]

    def prepare(operation):
        before = state()
        result = edit("prepare_edit", operation=operation)
        assert result["status"] == "prepared" and result["applied"] is False and result["editedCels"] == 0
        assert result["expiresInMs"] == 300000 and state() == before
        return result["editToken"]

    def apply(token, error=None):
        return client.request("apply_edit", {"documentId": identity, "editToken": token}, expected_error=error)

    def pixels(x, y, color=red, **params):
        return edit("set_pixels", layerId=layer, frame=0, pixels=[{"x": x, "y": y, **color}], **params)

    def operation(x=1, y=1, color=blue):
        return {"method": "edit_pixels", "edits": [{"layerId": layer, "frame": 0, "pixels": [{"x": x, "y": y, **color}]}]}

    edit("save", path="cooperative-before.ase")
    token = prepare(operation())
    pixels(12, 12)  # Native transaction representing a disjoint manual stroke; creates the formerly missing cel.
    edit("set_bitmap_selection", x=9, y=9, width=2, height=2, bits="1001")
    before = state(); manual = read()
    result = apply(token)
    assert result["status"] == "applied" and result["rebased"] and result["changedPixels"] == 1
    assert result["selection"] == before["selection"] and result["activeLayerId"] == before["activeLayerId"]
    assert read()[12][12] == manual[12][12] and read()[1][1] != 0
    apply(token, "EDIT_TOKEN_USED")
    for _ in range(2):
        edit("undo"); assert read() == manual
        edit("redo"); assert read()[12][12] == manual[12][12]
    edit("undo")
    token = prepare(operation())
    pixels(1, 1, red)
    before = state(); unchanged = read()
    result = apply(token)
    assert result["status"] == "conflict" and result["applied"] is False and state() == before and read() == unchanged
    apply(token, "EDIT_TOKEN_USED")
    edit("undo"); assert read() == manual  # Conflict added no Undo step.
    token = prepare(operation(12, 12, red))
    before = state(); result = apply(token)
    assert result["changedPixels"] == 0 and state() == before and result["status"] == "applied"
    print("PASS: prepared exact-pixel corrections rebase across disjoint native edits/new cels/GUI masks, preserve manual pixels and separate repeated Undo/Redo; overlapping edits conflict with no mutation/history, single-use and no-op guards.")

    for method in ("translate_regions", "stamp_region"):
        op = {"method": method, "edits": [{"layerId": layer, "frame": 0}]}
        if method == "translate_regions":
            op["edits"][0].update(mask={"x": 11, "y": 11, "width": 2, "height": 2, "bits": "0001"}, dx=-3, dy=0)
        else:
            op.update(source={"layerId": layer, "frame": 0, "x": 11, "y": 11, "width": 2, "height": 2}, mode="replace", maskBits="0001")
            op["edits"][0].update(x=6, y=3)
        token = prepare(op); pixels(15, 15)
        before = read(); result = apply(token)
        assert result["status"] == "applied" and result["rebased"] and read()[15][15] == before[15][15]
        edit("undo"); assert read() == before
        token = prepare(op)
        pixels(11 if method == "translate_regions" else 6, 11 if method == "translate_regions" else 3)
        before = state(); result = apply(token)
        assert result["status"] == "conflict" and state() == before  # Protect holes too, conservatively.
        edit("undo")
        if method == "stamp_region":
            token = prepare(op); pixels(12, 12, blue)
            before = state(); assert apply(token)["status"] == "conflict" and state() == before
            edit("undo")
    print("PASS: prepared move/copy/stamp destination guards preserve disjoint user work, protect transparent holes and source samples, and refuse overlaps/source changes without partial edits.")

    for change, kwargs in (("set_frame_duration", {"frame": 0, "durationMs": 200}), ("update_layer", {"layerId": layer, "editable": False}), ("resize_canvas", {"width": 17, "height": 16})):
        token = prepare(operation()); edit(change, **kwargs); before = state()
        assert apply(token)["status"] == "conflict" and state() == before
        edit("undo")
    token = prepare(operation())
    client.request("set_paused", {"paused": True}); apply(token, "PAUSED")
    assert client.request("interaction_state", {"documentId": identity})["paused"]
    client.request("set_paused", {"paused": False}); assert apply(token)["status"] == "applied"
    edit("undo")
    edit("add_frame", index=1, copyFrom=0, durationMs=100)
    token = prepare(operation())
    edit("reorder_frames", order=[1, 0]); before = state()
    assert apply(token)["status"] == "conflict" and state() == before
    edit("undo")
    batch = {"method": "edit_pixels", "edits": [
        {"layerId": layer, "frame": frame, "pixels": [{"x": 1, "y": 1, **blue}]} for frame in (0, 1)]}
    token = prepare(batch); pixels(15, 14, red); before = read()
    result = apply(token); assert result["status"] == "applied" and result["editedCels"] == 2
    edit("undo"); assert read() == before
    token = prepare(batch)
    edit("set_pixels", layerId=layer, frame=1, pixels=[{"x": 1, "y": 1, **red}])
    before = state(); original = read()
    assert apply(token)["status"] == "conflict" and state() == before and read() == original
    edit("undo")
    print("PASS: equal-looking frame permutations still conflict on existing cel/frame identity; prepared multi-frame batches rebase atomically and later-target overlaps cannot partially apply earlier targets.")
    png_path = assets / "cooperative-source.png"
    png_path.write_bytes(base64.b64decode(client.request("render", {"documentId": identity, "frame": 0, "scale": 1})["pngBase64"]))
    png_op = {"method": "stamp_region", "source": {"path": png_path.name, "x": 11, "y": 11, "width": 2, "height": 2},
        "mode": "replace", "edits": [{"layerId": layer, "frame": 0, "x": 6, "y": 3}]}
    token = prepare(png_op); pixels(15, 15, blue); before = read()
    assert apply(token)["status"] == "applied"
    edit("undo"); assert read() == before
    token = prepare(png_op); pixels(12, 12, blue)
    png_path.write_bytes(base64.b64decode(client.request("render", {"documentId": identity, "frame": 0, "scale": 1})["pngBase64"]))
    before = state()
    assert apply(token)["status"] == "conflict" and state() == before
    edit("undo")
    print("PASS: detached prepared PNG stamps rebase with immutable file samples, and changed decoded PNG sources conflict with no document/history side effects.")
    tickets = [prepare(operation()) for _ in range(8)]
    client.request("prepare_edit", {"documentId": identity, "expectedRevision": state()["revision"], "operation": operation()}, expected_error="LIMIT_EXCEEDED")
    client.request("apply_edit", {"documentId": identity, "editToken": tickets[0], "sessionId": "wrong"}, expected_error="SESSION_MISMATCH")
    other = client.request("create", {"width": 1, "height": 1, "name": "Other cooperative doc"})
    owned.append(other["documentId"])
    apply(tickets[0], "INACTIVE_DOCUMENT")
    client.request("apply_edit", {"documentId": other["documentId"], "editToken": tickets[0]}, expected_error="EDIT_TOKEN_INVALID")
    client.request("activate_document", {"documentId": identity, "expectedRevision": state()["revision"], "expectedActiveDocumentId": other["documentId"]})
    assert apply(tickets[0])["status"] == "applied"
    endpoint = client.socket.getpeername(); client.close()
    reconnected = type(client)(endpoint); client.__dict__.update(reconnected.__dict__)
    assert client.request("status")["paused"]
    client.request("set_paused", {"paused": False}); apply(tickets[1], "EDIT_TOKEN_INVALID")
    print("PASS: conservative topology/timing/lock/canvas dependency conflicts, bounded tickets, authoritative pause, inactive/session/document guards and disconnect invalidation with no delayed edits.")

    for mode in (8, 16):
        name = f"cooperative-native-{mode}.ase"; fixture(assets / name, mode=mode)
        doc = client.request("open", {"path": name}); identity = doc["documentId"]; layer = doc["layers"][0]["layerId"]
        owned.append(identity)
        op = {"method": "translate_regions", "edits": [{"layerId": layer, "frame": 0, "mask": {"x": 0, "y": 2, "width": 2, "height": 2, "bits": "1111"}, "dx": 4, "dy": 3}]}
        token = prepare(op)
        edit("set_bitmap_selection", x=12, y=12, width=1, height=1, bits="1")
        before = read(); assert apply(token)["status"] == "applied"
        edit("undo"); assert read() == before
    print("PASS: exact indexed/grayscale prepared native corrections and preserved selections/raw samples through Undo.")

    gui_id = test_cooperative_gui_gestures(client, assets)
    if gui_id: owned.append(gui_id)
    # Respect the existing 32-tab limit: only save/close this suite's generated
    # documents, not older tests' tabs, and never increase/weaken the limit.
    for document_id in owned:
        info = client.request("inspect", {"documentId": document_id})
        active = client.request("list_documents")["activeDocumentId"]
        if active != document_id:
            client.request("activate_document", {"documentId": document_id, "expectedRevision": info["revision"], "expectedActiveDocumentId": active})
        saved = client.request("save", {"documentId": document_id, "expectedRevision": info["revision"], "path": f"cooperative-cleanup-{document_id}.ase"})
        client.request("close_document", {"documentId": document_id, "expectedRevision": saved["revision"], "confirm": True})
    print("PASS: cooperative fixtures are saved/closed through guarded native tools, keeping the existing 32-document ceiling for the full regression suite.")


def test_cooperative_gui_gestures(client, assets):
    from gui_test_input import NativeInput
    status = client.request("status")
    if not NativeInput.available():
        print("SKIP: OS gestures are opt-in (LIBRESPRITE_TEST_GUI_INPUT=1), require existing macOS Accessibility permission and an unused desktop. No permission prompt was requested; manual review remains required.")
        return
    doc = client.request("create", {"width": 16, "height": 16, "name": "Real cooperative GUI gestures"})
    identity = doc["documentId"]; layer = doc["layers"][0]["layerId"]
    input = NativeInput(status["pid"])
    try:
        input.activate()
        exercise_gui_gestures(client, identity, layer, input)
    finally:
        input.restore_pointer()
    return identity


def exercise_gui_gestures(client, identity, layer, input):

    def state(): return client.request("interaction_state", {"documentId": identity})
    def current(): return client.request("inspect", {"documentId": identity})
    def edit(method, **params): return client.request(method, {"documentId": identity, "expectedRevision": current()["revision"], **params})
    def pixel(x, y): return client.request("read_pixels", {"documentId": identity, "layerId": layer, "frame": 0, "x": x, "y": y, "width": 1, "height": 1, "encoding": "values"})["rows"][0][0]
    red = {"r": 230, "g": 60, "b": 70, "a": 255}
    op = {"method": "edit_pixels", "edits": [{"layerId": layer, "frame": 0, "pixels": [{"x": 1, "y": 1, **red}]}]}
    edit("set_pixels", layerId=layer, frame=0, pixels=[{"x": 0, "y": 0, **red}])
    input.mouse(5, input.canvas_point(state(), 8, 8), 0)
    input.key(21)  # 4: native 800% zoom; hit real pixels, not 1px transform handles.
    assert state()["view"]["zoom"] == 8, state()
    input.key(11)  # B: native pencil tool in the default bindings.
    point = input.canvas_point(state(), 8, 8)
    try:
        input.mouse(25, point, 2); input.mouse(27, (point[0] + 24, point[1] + 12), 2)
        pan = state(); assert pan["viewOnlyPanning"] and pan["ready"], pan
        before_view = pan["view"]
        prepared = edit("prepare_edit", operation=op)
        applied = client.request("apply_edit", {"documentId": identity, "editToken": prepared["editToken"]})
        assert applied["status"] == "applied" and pixel(1, 1) != 0
        after_view = state()["view"]
        assert after_view == before_view, {"beforeView": before_view, "afterView": after_view}
        client.request("set_active_site", {"documentId": identity, "expectedRevision": applied["revision"], "frame": 0}, expected_error="BUSY")
    finally:
        input.mouse(26, (point[0] + 24, point[1] + 12), 2)
    edit("undo")
    prepared = edit("prepare_edit", operation=op)
    point = input.canvas_point(state(), 12, 12)
    try:
        input.mouse(1, point, 0)
        assert not state()["ready"], state()
        refused = client.request("apply_edit", {"documentId": identity, "editToken": prepared["editToken"]}, expected_error="BUSY")
        assert refused["error"]["data"]["notStarted"] is True and not client.request("status")["paused"]
    finally:
        input.mouse(2, point, 0)
    manual = pixel(12, 12); assert manual != 0, "Native pencil stroke did not paint; check tool/color/keybindings for this test profile."
    applied = client.request("apply_edit", {"documentId": identity, "editToken": prepared["editToken"]})
    assert applied["status"] == "applied" and applied["rebased"] and pixel(12, 12) == manual
    edit("undo"); assert pixel(12, 12) == manual and pixel(1, 1) == 0
    edit("undo"); assert pixel(12, 12) == 0
    # Native overlapping paint, not a bridge-simulated pixel transaction.
    prepared = edit("prepare_edit", operation=op)
    point = input.canvas_point(state(), 1, 1)
    input.click(point)
    before = canonical_inspection(current()); manual = pixel(1, 1)
    conflict = client.request("apply_edit", {"documentId": identity, "editToken": prepared["editToken"]})
    assert manual != 0 and conflict["status"] == "conflict" and canonical_inspection(current()) == before
    edit("undo"); assert pixel(1, 1) == 0
    # Rectangular selection capture is not view-only panning. After releasing,
    # a prepared correction ignores (and preserves) the new GUI selection.
    prepared = edit("prepare_edit", operation=op)
    input.key(46)  # M: native rectangular marquee tool.
    point = input.canvas_point(state(), 8, 8); end = input.canvas_point(state(), 10, 10)
    try:
        input.mouse(1, point, 0); input.mouse(6, end, 0)
        assert not state()["ready"] and not state()["viewOnlyPanning"]
        client.request("apply_edit", {"documentId": identity, "editToken": prepared["editToken"]}, expected_error="BUSY")
    finally:
        input.mouse(2, end, 0)
    mask = current()["selection"]; assert mask["selectedPixels"] > 0, mask
    result = client.request("apply_edit", {"documentId": identity, "editToken": prepared["editToken"]})
    assert result["status"] == "applied" and current()["selection"] == mask
    edit("undo")
    # Pan over an unfinished MovingPixelsState must NEVER get the Standby
    # exception, even after the selection mouse button was released.
    edit("modify_selection", action="none")
    edit("set_pixels", layerId=layer, frame=0, pixels=[{"x": 8, "y": 8, **red}])
    edit("set_bitmap_selection", x=6, y=6, width=6, height=6, bits="1"*36)
    point = input.canvas_point(state(), 8, 8); end = input.canvas_point(state(), 10, 8)
    try:
        input.mouse(1, point, 0); input.mouse(6, end, 0)
        assert not state()["ready"], state()
    finally:
        input.mouse(2, end, 0)
    assert not state()["ready"], "Native selection transform should remain pending until Return/Escape."
    try:
        input.mouse(25, end, 2); input.mouse(27, (end[0]+12, end[1]), 2)
        assert not state()["viewOnlyPanning"] and not state()["ready"], state()
        client.request("inspect", {"documentId": identity}, expected_error="BUSY")
    finally:
        input.mouse(26, (end[0]+12, end[1]), 2)
        input.key(53)  # Escape the native floating transform.
    assert state()["ready"], state()
    edit("modify_selection", action="none")
    prepared = edit("prepare_edit", operation=op)
    input.key(9)  # V: native Move tool/cel drag.
    point = input.canvas_point(state(), 8, 8); end = input.canvas_point(state(), 9, 8)
    try:
        input.mouse(1, point, 0); input.mouse(6, end, 0)
        assert not state()["ready"], state()
        client.request("apply_edit", {"documentId": identity, "editToken": prepared["editToken"]}, expected_error="BUSY")
    finally:
        input.mouse(2, end, 0)
    assert state()["ready"], state()
    result = client.request("apply_edit", {"documentId": identity, "editToken": prepared["editToken"]})
    assert result["status"] in ("applied", "conflict") and not client.request("status")["paused"]
    # Use the real editor Pause/Resume control, not a remotely manufactured latch.
    input.click(input.control_point(state()))
    assert client.request("status")["pausedByUser"]
    client.request("set_paused", {"paused": False}, expected_error="USER_PAUSED")
    input.click(input.control_point(state()))
    assert not client.request("status")["paused"]
    print("PASS: real held middle-button pan preserves viewport through prepare/apply; native pencil/selection/cel captures wait without pausing, disjoint edits rebase, overlaps conflict, Undo separates user/AI; pan over unfinished selection transform remains guarded; actual local Pause/Resume latch is authoritative.")

"""Guarded document closing/switching and non-editing site focus. GPLv2-only."""
import base64
from bridge_animation_cases import canonical_inspection
import uuid


def test_navigation(client, assets, smoke):
    original_ids = {doc["documentId"] for doc in client.request("list_documents")["documents"]}
    first = client.request("create", {"width": 16, "height": 16, "name": "Navigation A"})
    a = first["documentId"]
    ink = first["layers"][0]["layerId"]

    def inspect(doc):
        return canonical_inspection(client.request("inspect", {"documentId": doc}))

    def target(doc):
        return {"documentId": doc, "expectedRevision": inspect(doc)["revision"]}

    def active():
        return client.request("list_documents")["activeDocumentId"]

    def switch(doc, **extra):
        return canonical_inspection(client.request("activate_document", {**target(doc), "expectedActiveDocumentId": active(), **extra}))

    def pixels(doc):
        result = []
        for frame in range(inspect(doc)["frameCount"]):
            image = client.request("render", {"documentId": doc, "frame": frame, "scale": 1})
            path = assets / "navigation-preview.png"
            path.write_bytes(base64.b64decode(image["pngBase64"]))
            result.append(smoke.read_png(path))
        return result

    def state(doc):
        return {key: value for key, value in inspect(doc).items() if key not in ("activeFrame", "activeLayerId")}

    def reject(method, params, error, docs):
        before = [(inspect(doc), pixels(doc)) for doc in docs]
        selected = active()
        client.request(method, params, expected_error=error)
        assert [(inspect(doc), pixels(doc)) for doc in docs] == before, (method, error)
        assert active() == selected, (method, error)

    # A newly created blank document may not be marked modified but still has
    # no saved source. Closing must NOT interpret that as permission to discard.
    assert not first["hasFile"]
    reject("close_document", {**target(a), "confirm": True}, "UNSAVED_CHANGES", [a])
    client.request("set_pixels", {**target(a), "layerId": ink, "frame": 0, "pixels": [{"x": 3, "y": 4, "r": 210, "g": 50, "b": 90, "a": 255}]})
    client.request("add_frame", {**target(a), "index": 1, "copyFrom": 0, "durationMs": 135})
    group = client.request("create_layer", {**target(a), "type": "group", "name": "Review group"})["createdLayerId"]
    child = client.request("create_layer", {**target(a), "parentId": group, "name": "Hidden locked review layer"})["createdLayerId"]
    client.request("update_layer", {**target(a), "layerId": child, "visible": False, "editable": False})
    client.request("set_selection", {**target(a), "x1": 3, "y1": 4, "x2": 3, "y2": 4})
    client.request("save", {**target(a), "path": "navigation-a.ase"})
    a_state, a_pixels = state(a), pixels(a)
    saved_bytes = (assets / "navigation-a.ase").read_bytes()

    for params, expected_layer, expected_frame in (({"layerId": ink, "frame": 0}, ink, 0), ({"frame": 1}, ink, 1), ({"layerId": group}, group, 1), ({"layerId": child}, child, 1)):
        focused = client.request("set_active_site", {**target(a), **params})
        assert (focused["activeLayerId"], focused["activeFrame"]) == (expected_layer, expected_frame)
        assert state(a) == a_state and pixels(a) == a_pixels
    assert not focused["modified"] and focused["canUndo"] and focused["hasFile"]
    reject("set_active_site", target(a), "INVALID_PARAMS", [a])
    reject("set_active_site", {**target(a), "layerId": ink, "frame": 2}, "INVALID_PARAMS", [a])
    reject("set_active_site", {**target(a), "layerId": 2147483647, "frame": 0}, "LAYER_NOT_FOUND", [a])
    reject("set_active_site", {**target(a), "expectedRevision": a_state["revision"] + 100, "frame": 0}, "STALE_REVISION", [a])

    second = client.request("create", {"width": 8, "height": 8, "name": "Navigation B"})
    b = second["documentId"]
    b_state, b_pixels = state(b), pixels(b)
    reject("activate_document", {**target(a), "expectedActiveDocumentId": a}, "ACTIVE_DOCUMENT_CHANGED", [a, b])
    reject("activate_document", {**target(a), "expectedActiveDocumentId": None}, "ACTIVE_DOCUMENT_CHANGED", [a, b])
    reject("activate_document", target(a), "INVALID_PARAMS", [a, b])
    reject("activate_document", {**target(a), "expectedActiveDocumentId": b, "expectedRevision": a_state["revision"] + 100}, "STALE_REVISION", [a, b])
    reject("set_active_site", {**target(a), "frame": 0}, "INACTIVE_DOCUMENT", [a, b])
    reject("close_document", {**target(a), "confirm": True}, "INACTIVE_DOCUMENT", [a, b])
    switched = switch(a)
    assert active() == a and (switched["activeLayerId"], switched["activeFrame"]) == (child, 1)
    assert state(a) == a_state and pixels(a) == a_pixels and state(b) == b_state and pixels(b) == b_pixels
    before = inspect(a)
    assert switch(a) == before  # Already active preserves its view and history.
    client.request("set_paused", {"paused": True})
    assert client.request("status")["controlText"] == "AI: Paused | Resume"
    for method, params in (("activate_document", {**target(b), "expectedActiveDocumentId": a}), ("set_active_site", {**target(a), "frame": 0}), ("close_document", {**target(a), "confirm": True})):
        reject(method, params, "PAUSED", [a, b])
    client.request("set_paused", {"paused": False})
    assert client.request("status")["controlText"] == "AI: Enabled | Pause"
    print("PASS: revision/active-document/paused guards; site focus preserves pixels, masks, timing, saved state, and undo history.")

    # Close cannot force-discard, open dialogs, or accept stale state. A changed
    # document remains open, while undo back to saved permits explicit closing.
    reject("close_document", target(a), "INVALID_PARAMS", [a, b])
    reject("close_document", {**target(a), "confirm": False}, "INVALID_PARAMS", [a, b])
    client.request("update_layer", {**target(a), "layerId": ink, "name": "Unsaved rename"})
    assert inspect(a)["modified"]
    reject("close_document", {**target(a), "confirm": True}, "UNSAVED_CHANGES", [a, b])
    client.request("undo", target(a))
    assert not inspect(a)["modified"]
    reject("close_document", {**target(a), "expectedRevision": a_state["revision"], "confirm": True}, "STALE_REVISION", [a, b])
    assert (assets / "navigation-a.ase").read_bytes() == saved_bytes
    close_params, request_id = {**target(a), "confirm": True}, str(uuid.uuid4())
    closed = client.request("close_document", close_params, request_id=request_id)
    assert closed["closedDocumentId"] == a and active() != a
    assert client.request("close_document", close_params, request_id=request_id) == closed
    client.request("inspect", {"documentId": a}, expected_error="DOCUMENT_NOT_FOUND")
    assert a not in [item["documentId"] for item in client.request("list_documents")["documents"]]
    assert (assets / "navigation-a.ase").read_bytes() == saved_bytes
    assert state(b) == b_state and pixels(b) == b_pixels
    reopened = client.request("open", {"path": "navigation-a.ase"})
    assert reopened["documentId"] != a and reopened["hasFile"] and pixels(reopened["documentId"]) == a_pixels
    client.request("close_document", {**target(reopened["documentId"]), "confirm": True})
    switch(b)
    client.request("save", {**target(b), "path": "navigation-b.ase"})
    client.request("close_document", {**target(b), "confirm": True})
    assert {doc["documentId"] for doc in client.request("list_documents")["documents"]} == original_ids
    assert (assets / "navigation-a.ase").read_bytes() == saved_bytes
    print("PASS: never-saved/modified/stale/inactive close refusal; explicit native close/replay/reopen leaves saved files and other sprites intact.")

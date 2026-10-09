#!/usr/bin/env python3
"""Integration test against a NEW real GUI process, never the user's editor."""
import base64
import argparse
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import uuid
from bridge_workflow_cases import test_layers_frames_drawing
from bridge_preview_cases import test_assets_previews_exports
from bridge_metadata_cases import test_palettes_tags_animation
from bridge_selection_cases import test_cels_and_selection
from bridge_navigation_cases import test_navigation
from bridge_animation_cases import test_animation_workflows
from bridge_editing_cases import test_editing_workflows
from bridge_inspection_cases import test_frame_differences, test_isolated_previews

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("smoke", ROOT / "scripts/smoke-test-libresprite.py")
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)
BUILD = Path(os.environ.get("LIBRESPRITE_BUILD_DIR", ROOT / "build/libresprite"))


class Client:
    def __init__(self, path):
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.settimeout(15)
        self.socket.connect(str(path))
        self.reader = self.socket.makefile("rb")
        self.session = None

    def close(self):
        self.reader.close()
        self.socket.close()

    def request(self, method, params=None, request_id=None, expected_error=None):
        params = dict(params or {})
        if method != "status":
            params.setdefault("sessionId", self.session)
        request = {"jsonrpc": "2.0", "id": request_id or str(uuid.uuid4()), "method": method, "params": params}
        self.socket.sendall((json.dumps(request) + "\n").encode())
        response = json.loads(self.reader.readline())
        assert response["id"] == request["id"], response
        if expected_error:
            assert response["error"]["data"]["code"] == expected_error, response
            return response
        assert "error" not in response, response
        if method == "status":
            self.session = response["result"]["sessionId"]
        return response["result"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--navigation-only", action="store_true", help="Run step 1 checks in a fresh GUI, including closing the last sprite.")
    parser.add_argument("--animation-only", action="store_true", help="Run step 2 animation/selection checks in a fresh GUI.")
    parser.add_argument("--editing-only", action="store_true", help="Run step 3 canvas/layer/mask/brush/index checks in a fresh GUI.")
    parser.add_argument("--inspection-only", action="store_true", help="Run read-only animation inspection checks in a fresh GUI.")
    options = parser.parse_args()
    runtime = ROOT / ".runtime"
    runtime.mkdir(mode=0o700, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="test-", dir=runtime) as temporary:
        directory = Path(temporary)
        endpoint = directory / "b.sock"
        assets = directory / "assets"
        assets.mkdir()
        log_path = directory / "editor.log"
        with log_path.open("w") as log:
            environment = os.environ.copy()
            environment.pop("SDL_VIDEODRIVER", None)
            process = subprocess.Popen([str(SMOKE.EXECUTABLE), "--automation-socket", str(endpoint), "--automation-root", str(assets)], stdout=log, stderr=log, env=environment)
            client = None
            try:
                deadline = time.monotonic() + 20
                while not endpoint.exists():
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("GUI failed to start:\n" + log_path.read_text())
                    time.sleep(0.05)
                assert endpoint.stat().st_mode & 0o777 == 0o600
                client = Client(endpoint)
                status = client.request("status")
                assert status["paused"] and status["pid"] == process.pid
                assert status["bridgeVersion"] == "0.10.0" and "render_frame_diff" in status["methods"]
                assert status["connected"] and not status["pausedByUser"] and status["controlText"] == "AI: Paused | Resume"
                client.request("no_such_method", expected_error="METHOD_NOT_FOUND")
                client.socket.sendall(b"not-json\n")
                malformed = json.loads(client.reader.readline())
                assert malformed["id"] is None and malformed["error"]["code"] == -32700
                assert client.request("list_documents")["documents"] == []
                client.request("create", {"width": 16, "height": 16, "name": "Test"}, expected_error="PAUSED")
                client.request("set_paused", {"paused": False})
                if options.inspection_only:
                    test_frame_differences(client, assets, SMOKE)
                    test_isolated_previews(client, assets, SMOKE)
                    return
                if options.editing_only:
                    test_editing_workflows(client, assets, SMOKE)
                    return
                if options.animation_only:
                    test_animation_workflows(client, assets, SMOKE)
                    return
                if options.navigation_only:
                    test_navigation(client, assets, SMOKE)
                    assert client.request("list_documents")["activeDocumentId"] is None
                    assert client.request("status")["pid"] == process.pid
                    print("PASS: closing the last saved sprite leaves an empty, connected editor rather than quitting.")
                    return
                test_frame_differences(client, assets, SMOKE)
                test_isolated_previews(client, assets, SMOKE)
                test_animation_workflows(client, assets, SMOKE)
                test_editing_workflows(client, assets, SMOKE)
                document = client.request("create", {"width": 16, "height": 16, "name": "Live bridge test"})
                document_id = document["documentId"]
                layer_id = document["layers"][0]["layerId"]
                assert document["frameCount"] == 1 and document["width"] == 16
                assert client.request("list_documents")["activeDocumentId"] == document_id
                print("PASS: opt-in GUI session, private socket, pause, create, inspect.")

                def current():
                    return client.request("inspect", {"documentId": document_id})

                def target():
                    return {"documentId": document_id, "expectedRevision": current()["revision"]}

                def rendered():
                    result = client.request("render", {"documentId": document_id, "frame": 0, "scale": 1})
                    preview = assets / "preview.png"
                    preview.write_bytes(base64.b64decode(result["pngBase64"]))
                    return SMOKE.read_png(preview)[2]

                blank = rendered()
                assert blank == bytes(16 * 16 * 4)
                initial_revision = current()["revision"]
                params = {**target(), "layerId": layer_id, "frame": 0, "label": "Test atomic pixels", "pixels": [
                    {"x": 2, "y": 3, "r": 220, "g": 50, "b": 60, "a": 255},
                    {"x": 10, "y": 12, "r": 40, "g": 180, "b": 100, "a": 255},
                ]}
                request_id = str(uuid.uuid4())
                edited = client.request("set_pixels", params, request_id=request_id)
                assert edited["revision"] > initial_revision and edited["canUndo"]
                painted = rendered()
                assert painted[(3 * 16 + 2) * 4:(3 * 16 + 2) * 4 + 4] == bytes((220, 50, 60, 255))
                assert painted[(12 * 16 + 10) * 4:(12 * 16 + 10) * 4 + 4] == bytes((40, 180, 100, 255))
                assert sum(value != 0 for value in painted) == 8
                assert client.request("set_pixels", params, request_id=request_id) == edited
                client.request("set_pixels", {**params, "label": "Changed"}, request_id=request_id, expected_error="REQUEST_ID_REUSED")
                client.request("set_pixels", params, expected_error="STALE_REVISION")
                client.request("set_pixels", {**params, **target(), "pixels": params["pixels"] + [{"x": 16, "y": 0, "r": 1, "g": 2, "b": 3, "a": 255}]}, expected_error="INVALID_PARAMS")
                assert rendered() == painted
                assert client.request("undo", target())["canRedo"]
                assert rendered() == blank
                client.request("redo", target())
                assert rendered() == painted
                print("PASS: composited PNG, atomic native edits, stale/invalid rejection, replay deduplication, undo/redo.")

                # Patch a cropped, non-origin cel and grow it back out.
                updated = {**params, **target(), "pixels": [{"x": 0, "y": 0, "r": 1, "g": 2, "b": 3, "a": 255}]}
                client.request("set_pixels", updated)
                assert rendered()[:4] == bytes((1, 2, 3, 255))
                client.request("undo", target())
                assert rendered() == painted
                client.request("set_pixels", {**params, **target(), "pixels": [{"x": 2, "y": 3, "r": 0, "g": 0, "b": 0, "a": 0}, {"x": 10, "y": 12, "r": 0, "g": 0, "b": 0, "a": 0}]})
                assert rendered() == blank and not current()["layers"][0]["cels"]
                client.request("set_pixels", {**params, **target(), "pixels": [{"x": 7, "y": 8, "r": 8, "g": 7, "b": 6, "a": 255}]})
                assert rendered()[(8 * 16 + 7) * 4:(8 * 16 + 7) * 4 + 4] == bytes((8, 7, 6, 255))
                client.request("undo", target())
                assert rendered() == blank
                client.request("undo", target())
                assert rendered() == painted
                print("PASS: cropped cel growth, transparent clearing, missing-cel creation and undo.")

                client.request("save", {**target(), "path": "roundtrip.ase", "overwrite": False})
                assert (assets / "roundtrip.ase").is_file() and not current()["modified"]
                client.request("save", {**target(), "path": "roundtrip.ase"}, expected_error="FILE_EXISTS")
                client.request("save", {**target(), "path": "roundtrip.ase", "overwrite": True})
                client.request("save", {**target(), "path": "../escape.ase"}, expected_error="PATH_OUTSIDE_ROOT")
                (assets / "escape").symlink_to(directory, target_is_directory=True)
                client.request("save", {**target(), "path": "escape/escape.ase"}, expected_error="PATH_OUTSIDE_ROOT")
                client.request("open", {"path": "escape/editor.log"}, expected_error="PATH_OUTSIDE_ROOT")
                assert not list(assets.glob(".libresprite-save-*"))
                reopened = client.request("open", {"path": "roundtrip.ase"})
                preview = client.request("render", {"documentId": reopened["documentId"], "frame": 0, "scale": 1})
                image_path = assets / "reopened.png"
                image_path.write_bytes(base64.b64decode(preview["pngBase64"]))
                assert SMOKE.read_png(image_path)[2] == painted
                client.request("undo", target(), expected_error="INACTIVE_DOCUMENT")
                client.request("inspect", {"documentId": 2147483647}, expected_error="DOCUMENT_NOT_FOUND")
                client.request("set_paused", {"sessionId": "old-process", "paused": False}, expected_error="SESSION_MISMATCH")
                print("PASS: atomic native save/reopen, no accidental overwrite, root/symlink isolation, explicit IDs.")

                client.close()
                client = Client(endpoint)
                assert client.request("status")["paused"]
                client.request("create", {"width": 16, "height": 16, "name": "No"}, expected_error="PAUSED")
                # Same session, same known ID: replay is safe even after reconnect.
                assert client.request("set_pixels", params, request_id=request_id) == edited
                client.request("set_paused", {"paused": True})
                assert current()["documentId"] == document_id
                print("PASS: disconnect pauses editing, reconnect/reads work, retained replay does not reapply edits.")
                client.request("set_paused", {"paused": False})
                test_layers_frames_drawing(client, assets, SMOKE)
                test_assets_previews_exports(client, assets, SMOKE)
                test_palettes_tags_animation(client, assets, SMOKE)
                test_cels_and_selection(client, assets, SMOKE)
                test_navigation(client, assets, SMOKE)
            finally:
                if client:
                    client.close()
                # Terminate only the test-owned disposable process. Never locate
                # or kill another running LibreSprite instance.
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    main()

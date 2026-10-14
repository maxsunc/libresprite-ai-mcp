#!/usr/bin/env python3
"""JSON-line input helper for the disposable real-MCP gesture test. GPL-2.0-only."""
import argparse
import json
import sys
from gui_test_input import NativeInput

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--pid", type=int, required=True)
options = parser.parse_args()
if not NativeInput.available():
    print(json.dumps({"available": False}), flush=True)
    sys.exit(0)
input = NativeInput(options.pid)
print(json.dumps({"available": True}), flush=True)
try:
    for line in sys.stdin:
        command = json.loads(line)
        try:
            action = command["action"]
            if action == "activate": input.activate()
            elif action == "mouse": input.mouse(command["kind"], tuple(command["point"]), command["button"])
            elif action == "key": input.key(command["code"])
            elif action == "canvas_point":
                print(json.dumps({"point": input.canvas_point(command["state"], command["x"], command["y"])}), flush=True)
                continue
            elif action == "control_point":
                print(json.dumps({"point": input.control_point(command["state"])}), flush=True)
                continue
            else: raise ValueError("Unknown gesture action")
            print(json.dumps({"ok": True}), flush=True)
        except Exception as error:
            print(json.dumps({"error": str(error)}), flush=True)
finally:
    input.restore_pointer()

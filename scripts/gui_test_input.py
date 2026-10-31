"""Opt-in macOS input over foreground test-owned windows. GPL-2.0-only; no prompts."""
import ctypes
import os
import plistlib
import sys
import time


class Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class NativeInput:
    @staticmethod
    def available():
        if sys.platform != "darwin" or os.environ.get("LIBRESPRITE_TEST_GUI_INPUT") != "1": return False
        app = ctypes.CDLL('/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')
        app.AXIsProcessTrusted.restype = ctypes.c_bool
        cg = ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
        cg.CGPreflightPostEventAccess.restype = ctypes.c_bool
        return bool(app.AXIsProcessTrusted() and cg.CGPreflightPostEventAccess())

    def __init__(self, pid):
        self.pid = pid
        self.cg = ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
        self.cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        self.ax = ctypes.CDLL('/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')
        self.cg.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, Point, ctypes.c_uint32]; self.cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
        self.cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]; self.cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
        self.cg.CGEventPostToPid.argtypes = [ctypes.c_int, ctypes.c_void_p]
        self.cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        self.cg.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        self.cg.CGWarpMouseCursorPosition.argtypes = [Point]
        self.cg.CGEventCreate.argtypes = [ctypes.c_void_p]; self.cg.CGEventCreate.restype = ctypes.c_void_p
        self.cg.CGEventGetLocation.argtypes = [ctypes.c_void_p]; self.cg.CGEventGetLocation.restype = Point
        event = self.cg.CGEventCreate(None)
        self.original_point = self.cg.CGEventGetLocation(event)
        self.cf.CFRelease.argtypes = [ctypes.c_void_p]
        self.cf.CFRelease(event)
        self.cf.CFRelease.argtypes = [ctypes.c_void_p]
        self.cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]; self.cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        self.ax.AXUIElementCreateApplication.argtypes = [ctypes.c_int]; self.ax.AXUIElementCreateApplication.restype = ctypes.c_void_p
        self.ax.AXUIElementSetAttributeValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]; self.ax.AXUIElementSetAttributeValue.restype = ctypes.c_int

    def activate(self):
        app = self.ax.AXUIElementCreateApplication(self.pid)
        key = self.cf.CFStringCreateWithCString(None, b'AXFrontmost', 0x08000100)
        try:
            result = self.ax.AXUIElementSetAttributeValue(app, key, ctypes.c_void_p.in_dll(self.cf, 'kCFBooleanTrue'))
            assert result == 0, result
        finally: self.cf.CFRelease(key); self.cf.CFRelease(app)
        time.sleep(.2)

    def windows(self, all_processes=False):
        self.cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]; self.cg.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p
        self.cf.CFPropertyListCreateData.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_ulong, ctypes.c_void_p]; self.cf.CFPropertyListCreateData.restype = ctypes.c_void_p
        self.cf.CFDataGetLength.argtypes = [ctypes.c_void_p]; self.cf.CFDataGetLength.restype = ctypes.c_long
        self.cf.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]; self.cf.CFDataGetBytePtr.restype = ctypes.c_void_p
        array = self.cg.CGWindowListCopyWindowInfo(1 if all_processes else 0, 0)
        blob = self.cf.CFPropertyListCreateData(None, array, 100, 0, None)
        try:
            rows = plistlib.loads(ctypes.string_at(self.cf.CFDataGetBytePtr(blob), self.cf.CFDataGetLength(blob)))
            return [v for v in rows if all_processes or (v.get('kCGWindowOwnerPID') == self.pid and v.get('kCGWindowLayer') == 0)]
        finally: self.cf.CFRelease(blob); self.cf.CFRelease(array)

    def screen_point(self, state, x, y):
        window = max(self.windows(), key=lambda v: v['kCGWindowBounds']['Width'] * v['kCGWindowBounds']['Height'])['kCGWindowBounds']
        native = state['view']['windowBounds']; scale = window['Width'] / native['width']
        title = max(0, window['Height'] - native['height'] * scale)
        return (window['X'] + (x-native['x']) * scale, window['Y'] + title + (y-native['y']) * scale)

    def canvas_point(self, state, x, y):
        view = state['view']; origin = view['canvasOrigin']; step = view['pixelStep']
        return self.screen_point(state, origin['x'] + (x+.5)*step['x'], origin['y'] + (y+.5)*step['y'])

    def control_point(self, state):
        b = state['controlBounds']; return self.screen_point(state, b['x']+b['width']/2, b['y']+b['height']/2)

    def mouse(self, kind, point, button):
        if kind in (1, 3, 25):
            self.mouse(5, point, 0)  # Native UI hit-testing is driven by motion.
        # SDL3 Cocoa drops PostToPid mouse clicks here. Opt-in OS input instead
        # verifies the frontmost window at EVERY event belongs to our test PID.
        at_point = [v for v in self.windows(all_processes=True) if v.get('kCGWindowLayer') == 0 and
            v['kCGWindowBounds']['X'] <= point[0] < v['kCGWindowBounds']['X'] + v['kCGWindowBounds']['Width'] and
            v['kCGWindowBounds']['Y'] <= point[1] < v['kCGWindowBounds']['Y'] + v['kCGWindowBounds']['Height']]
        assert at_point and at_point[0]['kCGWindowOwnerPID'] == self.pid, str({
            "message": "Test window no longer frontmost; refusing OS input.", "point": point,
            "testPid": self.pid, "topPid": at_point[0]['kCGWindowOwnerPID'] if at_point else None,
            "testWindowBounds": [v['kCGWindowBounds'] for v in self.windows() if v.get('kCGWindowIsOnscreen')]})
        event = self.cg.CGEventCreateMouseEvent(None, kind, Point(*point), button)
        self.cg.CGEventSetFlags(event, 0)
        try: self.cg.CGEventPost(0, event)
        finally: self.cf.CFRelease(event)
        time.sleep(.12)

    def restore_pointer(self):
        self.cg.CGWarpMouseCursorPosition(self.original_point)

    def click(self, point):
        self.mouse(1, point, 0); self.mouse(2, point, 0)

    def key(self, code):
        for down in (True, False):
            event = self.cg.CGEventCreateKeyboardEvent(None, code, down)
            self.cg.CGEventSetFlags(event, 0)
            try: self.cg.CGEventPostToPid(self.pid, event)
            finally: self.cf.CFRelease(event)
            time.sleep(.08)

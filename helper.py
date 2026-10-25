"""PCDials: desktop dials fed by HWiNFO.

Reads HWiNFO's Gadget values from the registry, serves them on
http://127.0.0.1:8765 and opens one small see-through window per dial.

  /data        live HWiNFO readings as JSON
  /dials.json  dial settings (edit this to change the dials)
  /dial.html   the dial page (?i=0 for the first dial; add &preview for a dark background)

Run "python helper.py --server" to serve the data only, without opening windows.
"""
import ctypes
import json
import subprocess
import sys
import threading
import time
import winreg
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8765
HERE = Path(__file__).parent
DIALS_FILE = HERE / "dials.json"
POSITIONS_FILE = HERE / "positions.json"  # written by the app: where each dial sits
HWINFO_KEY = r"Software\HWiNFO64\VSB"


# ---------------------------------------------------------------- HWiNFO data

def read_hwinfo():
    """Return HWiNFO readings as a list of {sensor, label, value, text}."""
    raw = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, HWINFO_KEY) as key:
            i = 0
            while True:
                try:
                    name, data, _ = winreg.EnumValue(key, i)
                except OSError:
                    break
                raw[name] = data
                i += 1
    except OSError:
        return []  # HWiNFO not running or Gadget reporting is off

    readings = []
    n = 0
    while f"Label{n}" in raw:
        try:
            value = float(raw.get(f"ValueRaw{n}", ""))
        except ValueError:
            value = None
        readings.append({
            "sensor": raw.get(f"Sensor{n}", ""),
            "label": raw[f"Label{n}"],
            "value": value,
            "text": raw.get(f"Value{n}", ""),
        })
        n += 1
    return readings


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HERE), **kwargs)

    def do_GET(self):
        if self.path.split("?")[0] == "/data":
            body = json.dumps(read_hwinfo()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):
        pass  # keep quiet


class Server(ThreadingHTTPServer):
    allow_reuse_address = False  # a second copy fails to start instead of sharing the port


# ---------------------------------------------------------------- dial windows

user32 = ctypes.windll.user32
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x80      # no taskbar button, not in Alt+Tab
WS_EX_NOACTIVATE = 0x8000000  # clicking it never steals focus (e.g. from a game)
HWND_BOTTOM = 1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


class Api:
    """Functions the dial pages can call (right-click menu)."""

    def __init__(self, dials):
        self._dials = dials
        self._windows = []
        self._positions = load_json(POSITIONS_FILE, {})
        self._dirty = False
        self.restart_requested = False

    def _pos(self, i):
        return self._positions.setdefault(self._dials[i]["title"], {})

    def _save_soon(self):
        self._dirty = True

    def _save(self):
        if self._dirty:
            self._dirty = False
            POSITIONS_FILE.write_text(json.dumps(self._positions, indent=2), encoding="utf-8")

    def _save_loop(self):
        while True:
            time.sleep(1)
            self._save()

    def _moved(self, i, x, y):
        self._pos(i).update(x=x, y=y)
        self._save_soon()

    def is_locked(self, i):
        return self._pos(i).get("locked", False)

    def toggle_lock(self, i):
        self._pos(i)["locked"] = not self.is_locked(i)
        self._save_soon()
        return self._pos(i)["locked"]

    def _size(self, i):
        return self._pos(i).get("size") or self._dials[i].get("size", 330)

    def _url(self, i):
        return f"http://127.0.0.1:{PORT}/dial.html?i={i}&size={self._size(i)}"

    def set_size(self, i, size):
        self._pos(i)["size"] = size
        self._save_soon()
        w = self._windows[i]
        to_desktop_layer(w, size)
        w.load_url(self._url(i))

    def reload_all(self):
        for w in self._windows:
            w.evaluate_js("location.reload()")

    def restart(self):
        self.restart_requested = True
        self.quit()

    def quit(self):
        for w in list(self._windows):
            w.destroy()


def to_desktop_layer(window, size=None):
    """Hide from taskbar/Alt+Tab, never take focus, and sit behind normal windows.
    With size: also set the exact window size (pywebview shrinks frameless windows)."""
    hwnd = window.native.Handle.ToInt64()
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
    flags = SWP_NOMOVE | SWP_NOACTIVATE
    px = 0
    if size:
        px = round(size * user32.GetDpiForWindow(hwnd) / 96)
    else:
        flags |= SWP_NOSIZE
    user32.SetWindowPos(hwnd, HWND_BOTTOM, 0, 0, px, px, flags)


def keep_at_bottom(windows):
    while True:
        time.sleep(2)
        for w in windows:
            try:
                to_desktop_layer(w)
            except Exception:
                pass  # window closing


def run_windows():
    import webview

    dials = load_json(DIALS_FILE, [])
    api = Api(dials)
    for i, dial in enumerate(dials):
        size = api._size(i)
        pos = api._pos(i)
        w = webview.create_window(
            f"PCDials - {dial['title']}",
            api._url(i),
            js_api=api, width=size, height=size,
            x=pos.get("x", 40 + i * 340), y=pos.get("y", 40),
            frameless=True, easy_drag=False, transparent=True, shadow=False,
            resizable=False, focus=False,
        )
        w.events.moved += lambda x, y, i=i: api._moved(i, x, y)
        w.events.shown += lambda w=w, size=size: to_desktop_layer(w, size)
        api._windows.append(w)

    threading.Thread(target=api._save_loop, daemon=True).start()
    threading.Thread(target=keep_at_bottom, args=(api._windows,), daemon=True).start()
    webview.start()
    api._save()
    return api.restart_requested


if __name__ == "__main__":
    try:
        server = Server(("127.0.0.1", PORT), Handler)
    except OSError:
        sys.exit("PCDials is already running.")

    if "--server" in sys.argv:
        server.serve_forever()
    else:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        restart = run_windows()
        server.shutdown()
        server.server_close()
        if restart:
            subprocess.Popen([sys.executable, __file__])

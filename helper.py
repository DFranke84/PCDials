"""PCDials: desktop dials fed by HWiNFO.

Reads HWiNFO's Gadget values from the registry, serves them on
http://127.0.0.1:8765 and opens one small see-through window per dial.

  /data        live HWiNFO readings as JSON
  /dials.json  dial settings (edit this to change the dials)
  /dial.html   the dial page (?i=0 for the first dial; add &preview for a dark background)

Run "python helper.py --server" to serve the data only, without opening windows.
"""
import ctypes
import ctypes.wintypes
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
DIALS_APP = None  # the running dial windows (set in run_windows)


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

    def do_POST(self):
        # POST /quit closes the dials (used by the setup app's Stop button)
        if self.path == "/quit" and DIALS_APP:
            self.send_response(204)
            self.end_headers()
            DIALS_APP.quit()
        else:
            self.send_error(404)

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
WS_EX_APPWINDOW = 0x40000     # forces a taskbar button
HWND_BOTTOM = 1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10
MONITOR_DEFAULTTONULL = 0
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
RECT, POINT = ctypes.wintypes.RECT, ctypes.wintypes.POINT


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
        self._hidden = set()  # dial windows hidden because their monitor is off
        self._dragging = set()  # dials being dragged right now
        self._tray = None  # the system tray icon
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

    def dragging(self, i, on):
        """Called by the dial page when you start/stop dragging it."""
        if on:
            self._dragging.add(i)
        else:
            self._moved(i, force=True)  # the spot you let go at
            self._dragging.discard(i)

    def _moved(self, i, force=False):
        # Only save moves you make by dragging. Other moves (Windows pushing a dial
        # off a monitor that turned off, or our own repositioning) don't count.
        if i not in self._dragging and not force:
            return
        # Real screen pixels (not DPI-scaled units), so dials on monitors with
        # different scaling come back in exactly the same place.
        r = RECT()
        user32.GetWindowRect(self._windows[i].native.Handle.ToInt64(), ctypes.byref(r))
        self._pos(i).update(x=r.left, y=r.top)
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
        to_desktop_layer(self._windows[i], size)  # the page then reloads itself at the new size

    def set_all_locked(self, locked):
        for i, w in enumerate(self._windows):
            self._pos(i)["locked"] = locked
            w.evaluate_js(f"setLocked({'true' if locked else 'false'})")
        self._save_soon()

    def reload_all(self):
        for w in self._windows:
            w.evaluate_js("location.reload()")

    def restart(self):
        self.restart_requested = True
        self.quit()

    def quit(self):
        if self._tray:
            self._tray.Visible = False  # otherwise a dead icon lingers in the tray
        for w in list(self._windows):
            w.destroy()


def monitor_connected(pos, size=330):
    """True if any part of the dial at its saved spot (screen pixels) is on a connected
    monitor. Dials with no saved spot yet count as connected."""
    if "x" not in pos:
        return True
    r = RECT(pos["x"], pos["y"], pos["x"] + size, pos["y"] + size)
    return bool(user32.MonitorFromRect(ctypes.byref(r), MONITOR_DEFAULTTONULL))


def no_background(window):
    """Never paint a window background behind the dial. pywebview's see-through
    windows only stay see-through until the window first paints its background
    (a resize, or moving to another monitor, triggers that: you'd get a grey square)."""
    from System import Action, Array, Object
    from System.Reflection import BindingFlags
    from System.Windows.Forms import ControlStyles
    form = window.native
    styles = ControlStyles.Opaque | ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint

    def apply():
        stack = [form]
        while stack:
            c = stack.pop()
            c.GetType().GetMethod("SetStyle", BindingFlags.NonPublic | BindingFlags.Instance) \
                .Invoke(c, Array[Object]([styles, True]))
            stack.extend(list(c.Controls))
    form.Invoke(Action(apply))


def to_desktop_layer(window, size=None):
    """Hide from taskbar/Alt+Tab, never take focus, and sit behind normal windows.
    With size: also set the exact window size (pywebview shrinks frameless windows)."""
    hwnd = window.native.Handle.ToInt64()
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    # pywebview adds WS_EX_APPWINDOW, which forces a taskbar button; take it off
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                          (style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE) & ~WS_EX_APPWINDOW)
    flags = SWP_NOMOVE | SWP_NOACTIVATE
    px = 0
    if size:
        px = round(size * user32.GetDpiForWindow(hwnd) / 96)
    else:
        flags |= SWP_NOSIZE
    user32.SetWindowPos(hwnd, HWND_BOTTOM, 0, 0, px, px, flags)


def place(window, pos, hidden):
    """Show the dial at its saved spot, or hide it while that monitor is off.
    hidden: set of windows we hid. Only those are shown again; pywebview shows the
    others itself (showing them early breaks their see-through background)."""
    hwnd = window.native.Handle.ToInt64()
    r = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    if not monitor_connected(pos, r.right - r.left):
        user32.ShowWindow(hwnd, SW_HIDE)
        hidden.add(hwnd)
        return
    if "x" in pos:
        if (r.left, r.top) != (pos["x"], pos["y"]):
            user32.SetWindowPos(hwnd, HWND_BOTTOM, pos["x"], pos["y"], 0, 0,
                                SWP_NOSIZE | SWP_NOACTIVATE)
    if hwnd in hidden:
        hidden.discard(hwnd)
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)


def watch_monitors(api):
    """Every 2s: keep dials behind other windows, and hide/show them as monitors
    are turned off and on."""
    while True:
        time.sleep(2)
        for i, w in enumerate(list(api._windows)):
            if i in api._dragging:
                continue  # don't fight a drag in progress
            try:
                to_desktop_layer(w)
                place(w, api._pos(i), api._hidden)
            except Exception:
                pass  # window closing


def tray_icon(api, window):
    """The dials' icon in the system tray (they have no taskbar button), with a menu.
    Created on the window's UI thread, which runs the tray icon's messages."""
    import System.Drawing.Drawing2D as Drawing2D
    from System import Action, EventHandler
    from System.Drawing import Bitmap, Color, Graphics, Icon, Pen, SolidBrush
    from System.Windows.Forms import ContextMenuStrip, NotifyIcon, ToolStripSeparator

    def draw_icon():
        # a small gauge: dark disc, grey track, green arc
        bmp = Bitmap(32, 32)
        g = Graphics.FromImage(bmp)
        g.SmoothingMode = Drawing2D.SmoothingMode.AntiAlias
        g.FillEllipse(SolidBrush(Color.FromArgb(40, 40, 40)), 3, 3, 26, 26)
        g.DrawArc(Pen(Color.FromArgb(90, 90, 90), 4), 4, 4, 24, 24, 135, 270)
        g.DrawArc(Pen(Color.FromArgb(70, 210, 60), 4), 4, 4, 24, 24, 135, 170)
        g.Dispose()
        return Icon.FromHandle(bmp.GetHicon())

    def later(fn):  # run menu actions off the UI thread so they can't block it
        return EventHandler(lambda s, e: threading.Thread(target=fn, daemon=True).start())

    def open_setup():
        subprocess.Popen([sys.executable, str(HERE / "setup.py")], cwd=HERE)

    def create():
        menu = ContextMenuStrip()
        for text, fn in [("Open PCDials Setup", open_setup),
                         ("Lock all dials", lambda: api.set_all_locked(True)),
                         ("Unlock all dials", lambda: api.set_all_locked(False)),
                         ("Reload all dials", api.reload_all),
                         ("Restart", api.restart),
                         (None, None),
                         ("Close dials", api.quit)]:
            if text is None:
                menu.Items.Add(ToolStripSeparator())
            else:
                menu.Items.Add(text).Click += later(fn)
        tray = NotifyIcon()
        tray.Icon = draw_icon()
        tray.Text = "PCDials"
        tray.ContextMenuStrip = menu
        tray.DoubleClick += later(open_setup)
        tray.Visible = True
        api._tray = tray

    window.native.Invoke(Action(create))


def watch_dials_file(api, count):
    """Pick up changes to dials.json (from the setup app or by hand) automatically."""
    last = DIALS_FILE.stat().st_mtime
    while True:
        time.sleep(2)
        try:
            now = DIALS_FILE.stat().st_mtime
        except OSError:
            continue
        if now != last:
            last = now
            if len(load_json(DIALS_FILE, [])) != count:
                api.restart()  # dials added or removed: reopen the windows
                return
            api.reload_all()


def run_windows():
    import webview

    dials = load_json(DIALS_FILE, [])
    global DIALS_APP
    api = DIALS_APP = Api(dials)
    for i, dial in enumerate(dials):
        size = api._size(i)
        pos = api._pos(i)
        # Open in a default spot on the main monitor, then move to the saved
        # screen position once shown (or hide it if that monitor is off).
        w = webview.create_window(
            f"PCDials - {dial['title']}",
            api._url(i),
            js_api=api, width=size, height=size, x=40 + i * 340, y=40,
            frameless=True, easy_drag=False, transparent=True, shadow=False,
            resizable=False, focus=False,
        )
        def on_shown(w=w, i=i, size=size):
            no_background(w)  # first, before anything can repaint it
            to_desktop_layer(w, size)
            place(w, api._pos(i), api._hidden)
            if i == 0:
                tray_icon(api, w)
            w.events.moved += lambda x, y: api._moved(i)  # only track moves after placing

        w.events.shown += on_shown
        api._windows.append(w)

    threading.Thread(target=api._save_loop, daemon=True).start()
    threading.Thread(target=watch_dials_file, args=(api, len(dials)), daemon=True).start()
    threading.Thread(target=watch_monitors, args=(api,), daemon=True).start()
    webview.start()
    api._save()
    return api.restart_requested


def log_to_file():
    """With no console (pythonw), write messages and errors to pcdials.log so a dial
    that stops or misbehaves leaves a reason behind. Kept under ~1 MB."""
    log = HERE / "pcdials.log"
    if log.exists() and log.stat().st_size > 1_000_000:
        log.replace(HERE / "pcdials.old.log")
    sys.stdout = sys.stderr = open(log, "a", encoding="utf-8", buffering=1)
    threading.excepthook = lambda a: print(time.strftime("%Y-%m-%d %H:%M:%S"), "error in",
                                           a.thread.name, "".join(
                                               __import__("traceback").format_exception(a.exc_value)))


def note(*msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *msg)


if __name__ == "__main__":
    if sys.stdout is None:
        log_to_file()
    try:
        server = Server(("127.0.0.1", PORT), Handler)
    except OSError:
        note("Not started: PCDials is already running.")
        sys.exit(0)

    if "--server" in sys.argv:
        server.serve_forever()
    else:
        note("Dials started.")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            restart = run_windows()
        except Exception:
            import traceback
            note("Dials stopped by an error:\n" + traceback.format_exc())
            raise
        note("Dials restarting." if restart else "Dials closed.")
        server.shutdown()
        server.server_close()
        if restart:
            subprocess.Popen([sys.executable, __file__])
